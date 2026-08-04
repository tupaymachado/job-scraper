"""Conector Careerjet via API v4 — HTTP puro, sem browser.

A Careerjet é ela própria uma agregadora: puxa de dezenas de boards, que
é justamente a amplitude que se queria do Google Jobs, mas por API JSON
e sem anti-bot.

  GET https://search.api.careerjet.net/v4/query
      ?keywords=&location=&locale_code=pt_BR&pagesize=<=99&page=<n>
  Auth: HTTP Basic — usuário = API key, senha = vazia

PRECISA DE CHAVE. Registro grátis de publisher em
https://www.careerjet.com/partners/api/ — coloque em CAREERJET_AFFID no
worker/.env. Sem chave o conector se desabilita sozinho (não é erro).

## Por que NÃO usamos a API legada

A API legada (public.api.careerjet.net/search) responde 200 para alguns
Referer de domínios antigos e 401 para os demais:

    "The legacy Job Search API is only accessible for authenticated
     legacy users. Please use the new API (v4) instead."

Ou seja, é allowlist por domínio. Fazê-la funcionar exigiria forjar o
Referer de um terceiro allowlistado — contornar controle de acesso se
passando por outro, e revogável a qualquer momento. Não é uma base para
construir; a v4 com chave própria é.

## Limitações (medidas na API legada, provavelmente valem na v4)

A `url` é redirect de tracking (jobviewtrack.com) resolvido por
JavaScript — `curl -L` dá 0 redirects. Não dá para saber de qual board a
vaga veio nem deduplicar por URL, e o campo `site` vem vazio. Por isso o
dedup é por título+empresa (worker/dedup.py) e a Careerjet roda por
ÚLTIMO no pipeline: LinkedIn e Gupy, que têm URL direta, viram as
canônicas e ficam com o link bom.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from config import CAREERJET_AFFID
from connectors.base import register
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import sanitize_html

log = logging.getLogger(__name__)

API_URL = "https://search.api.careerjet.net/v4/query"

PAGE_SIZE = 99
MAX_PAGES = 4

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TRACKER_HOST = "jobviewtrack.com"


class MissingApiKey(Exception):
    """Sem chave configurada. O conector se omite em vez de falhar o run."""


def _parse_date(value: str | None) -> datetime | None:
    """RFC 2822 ('Tue, 04 Aug 2026 07:52:33 GMT') ou ISO, conforme a versão."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _job_id(url: str, title: str, company: str) -> str:
    """Sem ID estável na resposta, derivamos do token do tracker.

    O token do jobviewtrack é único por vaga e estável entre chamadas.
    """
    token = url.rstrip("/").rsplit("/", 1)[-1]
    if token and len(token) > 12:
        return token[:120]
    return re.sub(r"\W+", "-", f"{title}-{company}".lower())[:120]


class CareerjetConnector:
    name = "careerjet"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        if CAREERJET_AFFID:
            # Basic auth: chave como usuário, senha vazia.
            self.session.auth = (CAREERJET_AFFID, "")

    def search(self, profile: SearchProfile, limit: int = 100) -> list[RawJob]:
        if not CAREERJET_AFFID:
            raise MissingApiKey(
                "CAREERJET_AFFID não configurada — registre em "
                "https://www.careerjet.com/partners/api/ e ponha em worker/.env"
            )

        jobs: list[RawJob] = []
        seen: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            if len(jobs) >= limit:
                break

            params: dict[str, Any] = {
                "keywords": profile.keywords,
                "location": profile.location or "Brasil",
                "locale_code": "pt_BR",
                "pagesize": PAGE_SIZE,
                "page": page,
            }

            resp = self.session.get(API_URL, params=params, timeout=30)

            if resp.status_code == 401:
                raise SourceBlocked(f"Careerjet rejeitou a chave: {resp.text[:200]}")
            if resp.status_code in (403, 429):
                log.warning("Careerjet HTTP %d na página %d", resp.status_code, page)
                if not jobs:
                    raise SourceBlocked(f"Careerjet respondeu HTTP {resp.status_code}")
                break
            if resp.status_code != 200:
                log.warning("Careerjet HTTP %d na página %d", resp.status_code, page)
                if not jobs:
                    raise SourceBlocked(f"Careerjet respondeu HTTP {resp.status_code}")
                break

            payload = resp.json() or {}
            if payload.get("type") == "ERROR":
                raise SourceBlocked(f"Careerjet: {payload.get('error')}")

            # A v4 pode aninhar em "results"; a legada usava "jobs".
            items = payload.get("jobs") or payload.get("results") or []
            if not items:
                break

            for item in items:
                job = self._to_raw_job(item)
                if job and job.source_job_id not in seen:
                    seen.add(job.source_job_id)
                    jobs.append(job)

            if len(items) < PAGE_SIZE:
                break

            time.sleep(random.uniform(1.0, 2.0))

        return jobs[:limit]

    def _to_raw_job(self, item: dict[str, Any]) -> RawJob | None:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url:
            return None

        company = (item.get("company") or "").strip()
        description = item.get("description")

        return RawJob(
            source=self.name,
            source_job_id=_job_id(url, title, company),
            url=url,
            title=title,
            company=company or None,
            location=(item.get("locations") or item.get("location") or "").strip() or None,
            posted_at=_parse_date(item.get("date")),
            description_html=sanitize_html(description),
            description_text=description,
            raw={
                # Salário em texto livre ("9000 - 10000 per month");
                # quem normaliza para número é o ai/enrich.
                "salary": item.get("salary"),
                "site": item.get("site"),
                "tracker_url": url if TRACKER_HOST in url else None,
            },
        )


@register("careerjet")
def _factory() -> CareerjetConnector:
    return CareerjetConnector()


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o conector Careerjet isoladamente")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default="Brasil")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    profile = SearchProfile(id=None, keywords=args.keywords, location=args.location)
    try:
        jobs = CareerjetConnector().search(profile, limit=args.limit)
    except MissingApiKey as exc:
        print(f"\n{exc}")
        return

    with_salary = sum(1 for j in jobs if j.raw.get("salary"))
    print(f"\n{len(jobs)} vagas ({with_salary} com salário)\n")
    for job in jobs:
        posted = job.posted_at.date().isoformat() if job.posted_at else "?"
        print(f"{job.title[:70]}")
        print(f"    {job.company or '?'} — {job.location or '?'} — {posted}")
        print(
            f"    salário: {job.raw.get('salary') or '-'} "
            f"| desc: {len(job.description_text or '')} chars"
        )


if __name__ == "__main__":
    main()
