"""Conector Ampla Gestão — consultoria de RH de Pelotas, portal LinkVagas.

O portal (amplagestao.linkvagas.com.br) é HTML renderizado no servidor e
lista TODAS as vagas abertas numa página só, sem paginação nem busca:

  lista   GET /
          -> <a class="lv-job-row" href=".../home/view/<id>/4/<slug>"
                data-search="<título> <local> <cidade> <uf> <jornada> <contrato>">
             com <h3> (título) e <p> ("Pelotas/RS")
  detalhe GET /home/view/<id>/4/<slug>
          -> div.lv-job-view__description (HTML formatado),
             div.lv-job-view__info (Regime, Jornada, Quantidade) e um
             <script type="application/ld+json"> JobPosting (datePosted)

Validado out/2026 desta VM: HTTP 200 via requests, 19 vagas na home, a
maioria em Pelotas e região sul do RS (Rio Grande, Santa Vitória do Palmar).

Como não há busca no servidor, o filtro do perfil é nosso:
  - keywords: a vaga entra se QUALQUER palavra do perfil (3+ letras, sem
    acento) aparecer no data-search. Um perfil "administrativo financeiro
    fiscal" pega as três áreas;
  - location: com cidade no perfil, só vagas daquela cidade;
  - remote_only: só vagas que mencionem remoto/home office.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

from connectors.base import register
from location import fold, matches_keywords, parse_location, same_place
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import html_to_text, sanitize_html

log = logging.getLogger(__name__)

BASE_URL = "https://amplagestao.linkvagas.com.br"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# /home/view/6050/4/assistente-administrativo-... -> 6050
JOB_PATH_RE = re.compile(r"/home/view/(\d+)/")

# "Pelotas/RS", "Pelotas / RS"
CITY_UF_RE = re.compile(r"^\s*(.+?)\s*/\s*([A-Za-z]{2})\s*$")

REMOTE_WORDS = ("remoto", "home office", "teletrabalho")

# Regime do LinkVagas -> nosso vocabulário de contrato (o enrich normaliza o resto).
CONTRACT_MAP = {"clt": "clt", "estagio": "estagio", "autonomo - pj": "pj", "pj": "pj"}


def _sleep() -> None:
    """1,5–2,5s entre requests: portal pequeno, sem CDN — é sobre não pesar nele."""
    time.sleep(random.uniform(1.5, 2.5))


def _split_city(text: str | None) -> tuple[str | None, str | None]:
    """'Pelotas/RS' -> ('Pelotas', 'RS')."""
    if not text:
        return None, None
    match = CITY_UF_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2).upper()
    return text.strip() or None, None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class AmplaGestaoConnector:
    name = "amplagestao"

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
        try:
            resp = self.session.get(f"{BASE_URL}/", timeout=30)
        except requests.RequestException as exc:
            raise SourceBlocked(f"Ampla Gestão inacessível: {exc}") from exc

        if resp.status_code != 200:
            raise SourceBlocked(f"Ampla Gestão respondeu HTTP {resp.status_code}")

        all_jobs = self._parse_list(resp.text)
        if not all_jobs:
            # Portal no ar mas sem nenhuma linha: mais provável mudança de
            # layout do que "zero vagas abertas" numa consultoria ativa.
            log.warning("Ampla Gestão: nenhuma div.lv-job-row — layout pode ter mudado")

        city, state = parse_location(profile.location)

        jobs: list[RawJob] = []
        for job in all_jobs:
            haystack = fold(job.raw.get("search_text"))
            if not matches_keywords(profile.keywords, haystack):
                continue
            if profile.remote_only:
                if not any(w in haystack for w in REMOTE_WORDS):
                    continue
            elif city:
                job_city, job_uf = _split_city(job.location)
                if not same_place(job_city, job_uf, city, state):
                    continue
            jobs.append(job)

        log.info("Ampla Gestão: %d vagas no portal, %d passam no perfil", len(all_jobs), len(jobs))
        return jobs[:limit]

    def _parse_list(self, html: str) -> list[RawJob]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[RawJob] = []
        seen: set[str] = set()

        for row in soup.select("a.lv-job-row[href]"):
            href = row["href"]
            match = JOB_PATH_RE.search(href)
            title_el = row.select_one("h3")
            if not match or not title_el:
                continue

            job_id = match.group(1)
            if job_id in seen:
                continue
            seen.add(job_id)

            title = " ".join(title_el.get_text(strip=True).split())
            location_el = row.select_one(".lv-job-row__content p")
            search_text = row.get("data-search") or ""

            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=job_id,
                    url=href if href.startswith("http") else f"{BASE_URL}{href}",
                    title=title,
                    # O portal é da consultoria: a empresa contratante às vezes
                    # aparece só na descrição. Ampla Gestão é o anunciante.
                    company="Ampla Gestão",
                    location=location_el.get_text(strip=True) if location_el else None,
                    work_model="remoto" if any(w in fold(search_text) for w in REMOTE_WORDS) else None,
                    raw={"search_text": search_text},
                )
            )

        return jobs

    # -- detalhe -----------------------------------------------------

    def fetch_detail(self, job: RawJob) -> RawJob:
        """Descrição formatada + Regime/Jornada. Falha aqui não derruba a vaga."""
        _sleep()
        try:
            resp = self.session.get(job.url, timeout=30)
        except requests.RequestException as exc:
            log.warning("detalhe %s falhou: %s", job.source_job_id, exc)
            return job

        if resp.status_code == 429:
            raise SourceBlocked("Ampla Gestão 429 ao buscar detalhe")
        if resp.status_code != 200:
            log.warning("detalhe %s: HTTP %d", job.source_job_id, resp.status_code)
            return job

        soup = BeautifulSoup(resp.text, "html.parser")

        description = soup.select_one("div.lv-job-view__description")
        if description:
            # Sanitiza antes de gravar: o front renderiza com dangerouslySetInnerHTML.
            job.description_html = sanitize_html(str(description))
            job.description_text = html_to_text(str(description))

        info: dict[str, str] = {}
        for block in soup.select("div.lv-job-view__info"):
            key_el, val_el = block.select_one("small"), block.select_one("span")
            if key_el and val_el:
                info[key_el.get_text(strip=True)] = " ".join(val_el.get_text(strip=True).split())
        if info:
            job.raw["info"] = info
            regime = fold(info.get("Regime"))
            job.raw["contract_label"] = CONTRACT_MAP.get(regime, info.get("Regime"))
            job.raw["salary_label"] = info.get("Salário")

        posting = self._job_posting(soup)
        if posting:
            job.posted_at = _parse_date(posting.get("datePosted")) or job.posted_at
            job.raw["employment_type"] = posting.get("employmentType")
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


@register("amplagestao")
def _factory() -> AmplaGestaoConnector:
    return AmplaGestaoConnector()


# -- CLI de verificação ----------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o conector Ampla Gestão isoladamente")
    parser.add_argument("--keywords", default="", help="vazio = todas as vagas do portal")
    parser.add_argument("--location", default=None, help='ex: "Pelotas, RS"')
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--detail", action="store_true", help="busca o detalhe da 1ª vaga")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    connector = AmplaGestaoConnector()
    profile = SearchProfile(
        id=None, keywords=args.keywords, location=args.location, remote_only=args.remote_only
    )
    jobs = connector.search(profile, limit=args.limit)

    print(f"\n{len(jobs)} vagas\n")
    for job in jobs:
        print(f"[{job.source_job_id}] {job.title[:70]}")
        print(f"    {job.location or '?'} — {job.url}")

    if args.detail and jobs:
        connector.fetch_detail(jobs[0])
        print(f"\ninfo: {jobs[0].raw.get('info')} | contrato: {jobs[0].raw.get('contract_label')}")
        print(f"postada: {jobs[0].posted_at}")
        print(f"descrição: {len(jobs[0].description_text or '')} chars")
        print((jobs[0].description_text or "")[:300])


if __name__ == "__main__":
    main()
