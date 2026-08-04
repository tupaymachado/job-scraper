"""Conector Gupy via API pública do portal — HTTP puro, sem browser.

A Gupy é o ATS dominante no Brasil; milhares de empresas publicam por ela.
O portal de vagas expõe uma API JSON sem autenticação:

  GET https://employability-portal.gupy.io/api/v1/jobs
      ?jobName=<termo>&limit=<=100&offset=<n>&workplaceType=remote|hybrid|on-site

Validado ago/2026 desta VM: 554 vagas para "desenvolvedor", HTTP 200,
paginação por offset conferida (offsets 0/100/200 retornam resultados
distintos), `workplaceType` filtra de verdade.

Esta API é MUITO melhor estruturada do que o que raspamos do LinkedIn:
já vem com modalidade, skills, descrição e URL direta para a página da
empresa — sem tracker no meio.

Substitui a receita antiga do job-sites-pattern.md ("Gupy não tem busca
pública, ir via Google site:gupy.io"), que herdava o captcha do Google.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import time
from datetime import datetime
from typing import Any

import requests

from connectors.base import register
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import sanitize_html

log = logging.getLogger(__name__)

API_URL = "https://employability-portal.gupy.io/api/v1/jobs"

PAGE_SIZE = 100  # máximo aceito; limit=1000 devolve HTTP 400
MAX_PAGES = 5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Vocabulário da Gupy -> nosso vocabulário.
WORKPLACE_MAP = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial"}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _location(item: dict[str, Any]) -> str | None:
    parts = [item.get("city"), item.get("state"), item.get("country")]
    joined = ", ".join(p for p in parts if p and str(p).strip())
    return joined or None


SUBDOMAIN_RE = re.compile(r"https?://([^.]+)\.gupy\.io")

# careerPageName às vezes é slogan, não empresa: "VENHA SER #SANGUELARANJA 🧡🚀".
# Hashtag ou emoji denunciam isso.
MARKETING_RE = re.compile(r"[#\U0001F300-\U0001FAFF☀-➿]")


def _company(item: dict[str, Any]) -> str | None:
    """Empresa para exibição e dedup.

    O subdomínio da career page ("fcamara.gupy.io") é o identificador
    estável; o careerPageName é o que o usuário reconhece. Preferimos o
    nome, mas caímos no subdomínio quando ele é slogan — senão o dedup
    contra Careerjet/LinkedIn nunca casaria.
    """
    name = (item.get("careerPageName") or "").strip()
    if name and not MARKETING_RE.search(name):
        return name

    for url_field in ("jobUrl", "careerPageUrl"):
        match = SUBDOMAIN_RE.match(item.get(url_field) or "")
        if match:
            return match.group(1)

    return name or None


class GupyConnector:
    name = "gupy"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    def search(self, profile: SearchProfile, limit: int = 100) -> list[RawJob]:
        jobs: list[RawJob] = []
        seen: set[str] = set()

        for page in range(MAX_PAGES):
            if len(jobs) >= limit:
                break

            params: dict[str, Any] = {
                "jobName": profile.keywords,
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
            }
            if profile.remote_only:
                params["workplaceType"] = "remote"

            resp = self.session.get(API_URL, params=params, timeout=30)

            if resp.status_code == 429:
                log.warning("Gupy 429 na página %d (%d colhidas)", page, len(jobs))
                if not jobs:
                    raise SourceBlocked("Gupy respondeu 429 já na primeira página")
                break
            if resp.status_code != 200:
                log.warning("Gupy HTTP %d na página %d", resp.status_code, page)
                if not jobs:
                    raise SourceBlocked(f"Gupy respondeu HTTP {resp.status_code}")
                break

            items = (resp.json() or {}).get("data") or []
            if not items:
                break

            for item in items:
                job = self._to_raw_job(item)
                if job and job.source_job_id not in seen:
                    seen.add(job.source_job_id)
                    jobs.append(job)

            if len(items) < PAGE_SIZE:
                break  # última página

            time.sleep(random.uniform(1.0, 2.0))

        return jobs[:limit]

    def _to_raw_job(self, item: dict[str, Any]) -> RawJob | None:
        job_id = item.get("id")
        title = item.get("name")
        url = item.get("jobUrl")
        if not job_id or not title or not url:
            return None

        description = item.get("description")
        raw_workplace = item.get("workplaceType")

        return RawJob(
            source=self.name,
            source_job_id=str(job_id),
            url=url,
            title=title.strip(),
            company=_company(item),
            location=_location(item),
            work_model=WORKPLACE_MAP.get(raw_workplace, raw_workplace),
            posted_at=_parse_date(item.get("publishedDate")),
            # A descrição vem como HTML — sanitiza na escrita, igual ao LinkedIn.
            description_html=sanitize_html(description),
            description_text=description,
            raw={
                "skills": item.get("skills"),
                "type": item.get("type"),
                "disabilities": item.get("disabilities"),
                "careerPageUrl": item.get("careerPageUrl"),
                "careerPageName": item.get("careerPageName"),
                "applicationDeadline": item.get("applicationDeadline"),
            },
        )


@register("gupy")
def _factory() -> GupyConnector:
    return GupyConnector()


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o conector Gupy isoladamente")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    profile = SearchProfile(id=None, keywords=args.keywords, remote_only=args.remote_only)
    jobs = GupyConnector().search(profile, limit=args.limit)

    print(f"\n{len(jobs)} vagas\n")
    for job in jobs:
        posted = job.posted_at.date().isoformat() if job.posted_at else "?"
        desc = len(job.description_text or "")
        print(f"[{job.source_job_id}] {job.title[:70]}")
        print(f"    {job.company} — {job.location or '?'} — {job.work_model or '?'} — {posted}")
        print(f"    descrição: {desc} chars | skills: {(job.raw.get('skills') or [])[:4]}")


if __name__ == "__main__":
    main()
