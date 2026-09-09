"""Conector Programathor — board brasileiro só de vagas de TI, HTML puro.

Não há API pública: é um Rails que renderiza no servidor, então raspamos
o HTML. Em compensação o HTML é estável e a listagem já vem rica:

  busca   GET /jobs?search=<termo>&page=<n>
          -> 15 cards <div class="cell-list">, cada um com empresa, local,
             modalidade, senioridade, contrato, faixa salarial e tags
  detalhe GET /jobs/<id>-<slug>
          -> <script type="application/ld+json"> com um JobPosting completo

Validado ago/2026 desta VM: páginas 1, 2 e 3 de "react" devolveram 15 ids
cada, com interseção zero — a paginação é real. robots.txt libera /jobs
(só bloqueia /admin, /user, /users, /company).

Duas armadilhas medidas, ambas tratadas abaixo:
  - vaga individual pode devolver HTTP 500 (a 33685 devolvia) sem que o
    board esteja fora do ar. É defeito do registro, não bloqueio;
  - o JSON-LD tem \\n literal dentro da string de description, o que é JSON
    inválido no modo estrito — daí o json.loads(..., strict=False).

Vale mais que LinkedIn/Careerjet para o nosso caso porque a senioridade e
o tipo de contrato vêm declarados pelo anunciante, não inferidos pela IA.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

from connectors.base import register
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import sanitize_html

log = logging.getLogger(__name__)

BASE_URL = "https://programathor.com.br"
SEARCH_URL = f"{BASE_URL}/jobs"

PAGE_SIZE = 15  # o board pagina de 15 em 15; não é configurável por query
MAX_PAGES = 5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# O id da vaga é o prefixo numérico do slug: /jobs/33704-analista-de-...
JOB_PATH_RE = re.compile(r"^/jobs/(\d+)(?:-|$)")

# Modalidade vem entre parênteses colada ao local: "São Paulo/SP  (Híbrido)".
WORK_MODEL_RE = re.compile(r"\(([^)]+)\)\s*$")

WORK_MODEL_MAP = {
    "remoto": "remoto",
    "home office": "remoto",
    "hibrido": "hibrido",
    "presencial": "presencial",
}

# Cada linha do card é identificada pelo ícone, não pela posição: vaga sem
# faixa salarial simplesmente não traz a linha do cifrão, e ler por índice
# faria o contrato virar senioridade.
ICON_FIELDS = {
    "fa-briefcase": "company",
    "fa-map-marker-alt": "location",
    "fa-building": "company_size",
    "fa-money-bill-alt": "salary",
    "fa-chart-bar": "seniority",
    "fa-file-alt": "contract_type",
}


def _sleep() -> None:
    """1,5–2,5s entre requests.

    O Programathor é um site pequeno e sem CDN na frente: aqui a pausa é
    menos sobre não ser bloqueado e mais sobre não pesar no servidor deles.
    """
    time.sleep(random.uniform(1.5, 2.5))


def _strip_accents_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _split_location(raw: str | None) -> tuple[str | None, str | None]:
    """'São Paulo/SP (Híbrido)' -> ('São Paulo/SP', 'hibrido')."""
    if not raw:
        return None, None

    text = " ".join(raw.split())
    work_model = None

    match = WORK_MODEL_RE.search(text)
    if match:
        work_model = WORK_MODEL_MAP.get(_strip_accents_lower(match.group(1).strip()))
        text = text[: match.start()].strip()

    # "Remoto" ocupa o lugar do local quando não há cidade nenhuma.
    if not work_model and _strip_accents_lower(text) in WORK_MODEL_MAP:
        work_model = WORK_MODEL_MAP[_strip_accents_lower(text)]

    return (text or None), work_model


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _card_fields(card) -> dict[str, str]:
    """Lê as linhas do card indexadas pelo ícone do Font Awesome."""
    fields: dict[str, str] = {}
    for span in card.select("div.cell-list-content-icon > span"):
        icon = span.select_one("i")
        classes = icon.get("class", []) if icon else []
        for cls in classes:
            field = ICON_FIELDS.get(cls)
            if field:
                fields[field] = " ".join(span.get_text(strip=True).split())
                break
    return fields


def _card_title(card) -> str | None:
    heading = card.select_one("h3")
    if not heading:
        return None

    # O selo "NOVA" é um <span> dentro do h3 e gruda no título sem separador.
    for badge in heading.select("span, small"):
        badge.decompose()

    title = " ".join(heading.get_text(strip=True).split())
    return title or None


class ProgramathorConnector:
    name = "programathor"

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
        jobs: list[RawJob] = []
        seen: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            if len(jobs) >= limit:
                break

            params = {"search": profile.keywords, "page": page}
            try:
                resp = self.session.get(SEARCH_URL, params=params, timeout=30)
            except requests.RequestException as exc:
                if not jobs:
                    raise SourceBlocked(f"Programathor inacessível: {exc}") from exc
                log.warning("Programathor falhou na página %d: %s", page, exc)
                break

            if resp.status_code == 429:
                if not jobs:
                    raise SourceBlocked("Programathor respondeu 429 já na primeira página")
                log.warning("Programathor 429 na página %d (%d colhidas)", page, len(jobs))
                break
            if resp.status_code != 200:
                if not jobs:
                    raise SourceBlocked(f"Programathor respondeu HTTP {resp.status_code}")
                log.warning("Programathor HTTP %d na página %d", resp.status_code, page)
                break

            page_jobs = self._parse_list(resp.text)
            if not page_jobs:
                break  # acabaram os resultados da busca

            for job in page_jobs:
                if job.source_job_id in seen:
                    continue
                # O board não tem filtro de remoto na URL (?place=... redireciona),
                # então o corte é nosso, depois de parsear.
                if profile.remote_only and job.work_model != "remoto":
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

        for card in soup.select("div.cell-list"):
            link = card.select_one('a[href^="/jobs/"]')
            if not link:
                continue  # cards de publicidade da própria plataforma

            path_match = JOB_PATH_RE.match(link["href"].split("?", 1)[0])
            title = _card_title(card)
            if not path_match or not title:
                continue

            fields = _card_fields(card)
            location, work_model = _split_location(fields.get("location"))
            tags = [t.get_text(strip=True) for t in card.select("span.tag-list")]

            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=path_match.group(1),
                    url=f"{BASE_URL}{link['href'].split('?', 1)[0]}",
                    title=title,
                    company=fields.get("company"),
                    location=location,
                    work_model=work_model,
                    raw={
                        # Senioridade, contrato e salário vêm DECLARADOS pelo
                        # anunciante. O enrich ainda normaliza, mas partindo
                        # daqui em vez de adivinhar pelo texto.
                        "seniority_label": fields.get("seniority"),
                        "contract_label": fields.get("contract_type"),
                        "salary_label": fields.get("salary"),
                        "company_size": fields.get("company_size"),
                        "tags": tags,
                    },
                )
            )

        return jobs

    # -- detalhe -----------------------------------------------------

    def fetch_detail(self, job: RawJob) -> RawJob:
        """Preenche a descrição a partir do JSON-LD da página da vaga.

        Falha aqui não derruba a vaga: ela entra sem descrição e o enrich
        trabalha com menos. Em particular, HTTP 500 numa vaga é registro
        quebrado do board — segue para a próxima em vez de virar bloqueio.
        """
        _sleep()
        try:
            resp = self.session.get(job.url, timeout=30)
        except requests.RequestException as exc:
            log.warning("detalhe %s falhou: %s", job.source_job_id, exc)
            return job

        if resp.status_code == 429:
            raise SourceBlocked("Programathor 429 ao buscar detalhe")
        if resp.status_code != 200:
            log.warning("detalhe %s: HTTP %d", job.source_job_id, resp.status_code)
            return job

        posting = self._job_posting(resp.text)
        if not posting:
            log.warning("detalhe %s: sem JSON-LD JobPosting", job.source_job_id)
            return job

        description = posting.get("description")
        if description:
            # Sanitiza antes de gravar: o front renderiza com
            # dangerouslySetInnerHTML e o conteúdo é de terceiros.
            job.description_html = sanitize_html(description)
            job.description_text = BeautifulSoup(description, "html.parser").get_text(
                "\n", strip=True
            )

        job.posted_at = _parse_date(posting.get("datePosted")) or job.posted_at

        organization = posting.get("hiringOrganization") or {}
        if not job.company and organization.get("name"):
            job.company = organization["name"].strip()

        job.raw["employment_type"] = posting.get("employmentType")
        job.raw["valid_through"] = posting.get("validThrough")

        return job

    @staticmethod
    def _job_posting(html: str) -> dict[str, Any] | None:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                # strict=False: a descrição traz \n literal dentro da string,
                # o que o parser estrito recusa.
                data = json.loads(script.string or "", strict=False)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                return data
        return None


@register("programathor")
def _factory() -> ProgramathorConnector:
    return ProgramathorConnector()


# -- CLI de verificação ----------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o conector Programathor isoladamente")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--detail", action="store_true", help="busca a descrição da 1ª vaga")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    connector = ProgramathorConnector()
    profile = SearchProfile(id=None, keywords=args.keywords, remote_only=args.remote_only)
    jobs = connector.search(profile, limit=args.limit)

    print(f"\n{len(jobs)} vagas\n")
    for job in jobs:
        print(f"[{job.source_job_id}] {job.title[:70]}")
        print(f"    {job.company} — {job.location or '?'} — {job.work_model or '?'}")
        print(
            f"    {job.raw.get('seniority_label') or '?'} | "
            f"{job.raw.get('contract_label') or '?'} | "
            f"{job.raw.get('salary_label') or 'salário n/d'} | "
            f"tags: {(job.raw.get('tags') or [])[:5]}"
        )

    if args.detail and jobs:
        connector.fetch_detail(jobs[0])
        print(f"\ndescrição da 1ª: {len(jobs[0].description_text or '')} chars")
        print((jobs[0].description_text or "")[:400])


if __name__ == "__main__":
    main()
