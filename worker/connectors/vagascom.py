"""Conector Vagas.com.br — board generalista grande, HTML renderizado no servidor.

Não há API pública (robots.txt bloqueia /api/ e /v1/), mas a busca é HTML
estável e liberada no robots:

  busca   GET /vagas-de-<termo>?e[]=<Estado por extenso>&m[]=100%25+Home+Office&pagina=<n>
          -> 40 <li class="vaga"> por página: a.link-detalhes-vaga[data-id-vaga],
             span.emprVaga (empresa), span.nivelVaga, .vaga-local ("Pelotas / RS"),
             span.data-publicacao ("27/07/2026") e um trecho da descrição
  detalhe GET /vagas/v<id>/<slug>
          -> div.job-description__text (descrição), .info-modelo-contratual
             ("Regime CLT"), .job-hierarchylist (nível), salário, e um
             JSON-LD JobPosting (datePosted, validThrough, empresa, local)

Validado out/2026 desta VM: HTTP 200 via requests, sem cookie; pagina=2
devolve ids distintos da 1; acento no termo é indiferente ("contabil" e
"contábil" dão as mesmas 242 vagas).

LOCALIZAÇÃO: só existe faceta de ESTADO (e[]); "vagas-de-x-em-pelotas" e
c[]=Pelotas devolvem zero. Para perfil com cidade: buscamos pelo estado e
pós-filtramos a cidade; depois `m[]=100% Home Office` completa o limite
com as remotas, como no conector da Gupy.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from connectors.base import register
from location import fold, parse_location, same_place
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import html_to_text, sanitize_html

log = logging.getLogger(__name__)

BASE_URL = "https://www.vagas.com.br"

PAGE_SIZE = 40  # fixo no board
MAX_PAGES = 5

REMOTE_FACET = "100% Home Office"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# "Regime CLT" / "Estágio" / "Pessoa Jurídica" -> nosso vocabulário (o enrich normaliza o resto).
CONTRACT_MAP = {
    "regime clt": "clt",
    "estagio": "estagio",
    "pessoa juridica": "pj",
    "temporario": "temporario",
}


def _sleep() -> None:
    """1,5–2,5s entre requests — mesma cortesia dos outros conectores HTML."""
    time.sleep(random.uniform(1.5, 2.5))


def _slug(keywords: str) -> str:
    """'assistente administrativo' -> 'assistente-administrativo' (o board aceita acento)."""
    return quote("-".join(keywords.strip().lower().split()))


def _split_city(text: str | None) -> tuple[str | None, str | None]:
    """'Pelotas / RS' -> ('Pelotas', 'RS')."""
    if not text or "/" not in text:
        return (text or None), None
    city, _, uf = text.rpartition("/")
    return city.strip() or None, uf.strip() or None


def _parse_br_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _text(el) -> str | None:
    if el is None:
        return None
    return " ".join(el.get_text(" ", strip=True).split()) or None


class VagasComConnector:
    name = "vagascom"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
        )

    # -- busca -------------------------------------------------------

    def search(self, profile: SearchProfile, limit: int = 50) -> list[RawJob]:
        path = f"/vagas-de-{_slug(profile.keywords)}"
        city, state = parse_location(profile.location)

        if profile.remote_only:
            return self._collect(path, {"m[]": REMOTE_FACET}, limit, keep=None)
        if not state:
            # Sem estado não há faceta para usar; cidade sozinha é pós-filtro puro.
            keep = (lambda j: self._in_city(j, city, None)) if city else None
            return self._collect(path, {}, limit, keep=keep)

        def keep(job: RawJob) -> bool:
            return job.work_model == "remoto" or not city or self._in_city(job, city, state)

        jobs = self._collect(path, {"e[]": state}, limit, keep=keep)
        log.info("Vagas.com: %d vagas em %s", len(jobs), city or state)

        if len(jobs) < limit:
            seen = {j.source_job_id for j in jobs}
            remote = self._collect(
                path, {"m[]": REMOTE_FACET}, limit - len(jobs),
                keep=None, seen=seen, has_results=bool(jobs),
            )
            log.info("Vagas.com: + %d remotas", len(remote))
            jobs.extend(remote)

        return jobs[:limit]

    @staticmethod
    def _in_city(job: RawJob, city: str, state: str | None) -> bool:
        job_city, job_uf = _split_city(job.location)
        return same_place(job_city, job_uf, city, state)

    def _collect(
        self,
        path: str,
        facets: dict[str, str],
        limit: int,
        keep: Callable[[RawJob], bool] | None,
        seen: set[str] | None = None,
        has_results: bool = False,
    ) -> list[RawJob]:
        """Pagina uma busca. `has_results`: uma busca anterior do perfil já colheu algo."""
        jobs: list[RawJob] = []
        seen = set(seen or ())

        for page in range(1, MAX_PAGES + 1):
            if len(jobs) >= limit:
                break

            params = dict(facets)
            if page > 1:
                params["pagina"] = page
            collected = bool(jobs) or has_results

            try:
                resp = self.session.get(f"{BASE_URL}{path}", params=params, timeout=30)
            except requests.RequestException as exc:
                if not collected:
                    raise SourceBlocked(f"Vagas.com inacessível: {exc}") from exc
                log.warning("Vagas.com falhou na página %d: %s", page, exc)
                break

            if resp.status_code != 200:
                log.warning("Vagas.com HTTP %d na página %d", resp.status_code, page)
                if not collected:
                    raise SourceBlocked(f"Vagas.com respondeu HTTP {resp.status_code}")
                break

            page_jobs = self._parse_list(resp.text)
            if not page_jobs:
                break  # busca sem resultado, ou acabaram as páginas

            for job in page_jobs:
                if job.source_job_id in seen or (keep is not None and not keep(job)):
                    continue
                seen.add(job.source_job_id)
                jobs.append(job)

            if len(page_jobs) < PAGE_SIZE:
                break  # última página

            _sleep()

        return jobs[:limit]

    def _parse_list(self, html: str) -> list[RawJob]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[RawJob] = []

        for card in soup.select("li.vaga"):
            link = card.select_one("a.link-detalhes-vaga[data-id-vaga]")
            if not link or not link.get("href"):
                continue

            # O title do <a> é o cargo limpo; o texto vem picado em <mark> do destaque.
            title = (link.get("title") or _text(link) or "").strip()
            if not title:
                continue

            local_el = card.select_one(".vaga-local")
            tooltip = local_el.select_one(".tooltip-place") if local_el else None
            if tooltip:
                tooltip.decompose()  # "A empresa aceita candidaturas de..." não é o local
            location = _text(local_el)

            work_model = None
            if location and "home office" in fold(location):
                work_model = "remoto"

            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=link["data-id-vaga"],
                    url=f"{BASE_URL}{link['href'].split('?', 1)[0]}",
                    title=title,
                    company=_text(card.select_one(".emprVaga")),
                    location=location,
                    work_model=work_model,
                    posted_at=_parse_br_date(_text(card.select_one(".data-publicacao"))),
                    raw={
                        "level_label": _text(card.select_one(".nivelVaga")),
                        "snippet": _text(card.select_one(".detalhes")),
                    },
                )
            )

        return jobs

    # -- detalhe -----------------------------------------------------

    def fetch_detail(self, job: RawJob) -> RawJob:
        """Descrição, regime, nível e salário. Falha aqui não derruba a vaga."""
        _sleep()
        try:
            resp = self.session.get(job.url, timeout=30)
        except requests.RequestException as exc:
            log.warning("detalhe %s falhou: %s", job.source_job_id, exc)
            return job

        if resp.status_code == 429:
            raise SourceBlocked("Vagas.com 429 ao buscar detalhe")
        if resp.status_code != 200:
            log.warning("detalhe %s: HTTP %d", job.source_job_id, resp.status_code)
            return job

        soup = BeautifulSoup(resp.text, "html.parser")

        description = soup.select_one("div.job-description__text")
        if description:
            # Sanitiza antes de gravar: o front renderiza com dangerouslySetInnerHTML.
            job.description_html = sanitize_html(str(description))
            job.description_text = html_to_text(str(description))

        contract = _text(soup.select_one(".info-modelo-contratual"))
        if contract:
            job.raw["contract_label"] = CONTRACT_MAP.get(fold(contract), contract)
        level = _text(soup.select_one(".job-hierarchylist"))
        if level:
            job.raw["level_label"] = level
        salary_icon = soup.select_one(".icone-salario")
        if salary_icon is not None:
            job.raw["salary_label"] = _text(salary_icon.parent)

        posting = self._job_posting(soup)
        if posting:
            job.posted_at = _parse_iso_date(posting.get("datePosted")) or job.posted_at
            job.raw["valid_through"] = posting.get("validThrough")
            organization = posting.get("hiringOrganization") or {}
            if (not job.company or job.company == "Confidencial") and organization.get("name"):
                job.company = organization["name"].strip()
            if not job.description_text and posting.get("description"):
                job.description_text = posting["description"]

        return job

    @staticmethod
    def _job_posting(soup: BeautifulSoup) -> dict[str, Any] | None:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "", strict=False)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                return data
        return None


@register("vagascom")
def _factory() -> VagasComConnector:
    return VagasComConnector()


# -- CLI de verificação ----------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o conector Vagas.com isoladamente")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default=None, help='ex: "Pelotas, RS"')
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--detail", action="store_true", help="busca o detalhe da 1ª vaga")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    connector = VagasComConnector()
    profile = SearchProfile(
        id=None, keywords=args.keywords, location=args.location, remote_only=args.remote_only
    )
    jobs = connector.search(profile, limit=args.limit)

    print(f"\n{len(jobs)} vagas\n")
    for job in jobs:
        posted = job.posted_at.date().isoformat() if job.posted_at else "?"
        print(f"[{job.source_job_id}] {job.title[:70]}")
        print(f"    {job.company or '?'} — {job.location or '?'} — {job.work_model or '?'} — {posted}")

    if args.detail and jobs:
        connector.fetch_detail(jobs[0])
        first = jobs[0]
        print(
            f"\ncontrato: {first.raw.get('contract_label')} | nível: {first.raw.get('level_label')}"
            f" | salário: {first.raw.get('salary_label')} | até: {first.raw.get('valid_through')}"
        )
        print(f"descrição: {len(first.description_text or '')} chars")
        print((first.description_text or "")[:300])


if __name__ == "__main__":
    main()
