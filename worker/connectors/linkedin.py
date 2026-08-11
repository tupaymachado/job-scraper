"""Conector LinkedIn via API jobs-guest — HTTP puro, sem browser.

Os endpoints `jobs-guest` são os que a página pública de vagas usa para
carregar resultados sem login. Respondem a `requests` com um User-Agent
de browser: nada de Cloudflare, nada de Botasaurus.

Endpoints (validados ago/2026 desta VM):
  busca   GET /jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=&location=&start=
          -> HTML com 10 <div class="base-card" data-entity-urn="urn:li:jobPosting:ID">
  detalhe GET /jobs-guest/jobs/api/jobPosting/<id>
          -> HTML com .show-more-less-html__markup + li.description__job-criteria-item

O 429 aparece por volta da 10ª página num mesmo IP; paramos bem antes.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from connectors.base import register
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import sanitize_html

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

PAGE_SIZE = 10
MAX_PAGES = 5  # ~50 vagas/rodada, bem abaixo do limite observado (~10 páginas)

# f_WT: 1=presencial, 2=remoto, 3=híbrido
REMOTE_FILTER = "2"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

URN_RE = re.compile(r"urn:li:jobPosting:(\d+)")


def _sleep() -> None:
    """2–3s entre requests. É o que mantém o IP limpo — não remover."""
    time.sleep(random.uniform(2.0, 3.0))


def _parse_posted_at(card) -> datetime | None:
    el = card.select_one("time[datetime]")
    if not el:
        return None
    try:
        return datetime.strptime(el["datetime"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return None


def _clean_url(href: str) -> str:
    """Tira os parâmetros de tracking (position, pageNum, refId, trackingId)."""
    return href.split("?", 1)[0]


class LinkedInConnector:
    name = "linkedin"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            }
        )

    # -- busca -------------------------------------------------------

    def search(self, profile: SearchProfile, limit: int = 50) -> list[RawJob]:
        jobs: list[RawJob] = []
        seen: set[str] = set()

        for page in range(MAX_PAGES):
            if len(jobs) >= limit:
                break

            params = {"keywords": profile.keywords, "start": page * PAGE_SIZE}
            if profile.location:
                params["location"] = profile.location
            if profile.remote_only:
                params["f_WT"] = REMOTE_FILTER

            url = f"{SEARCH_URL}?{urlencode(params)}"
            resp = self.session.get(url, timeout=30)

            if resp.status_code == 429:
                # Rate limit no meio da paginação: devolvemos o que já veio.
                # Só é bloqueio de verdade se não colhemos nada.
                log.warning("LinkedIn 429 na página %d (%d vagas colhidas)", page, len(jobs))
                if not jobs:
                    raise SourceBlocked("LinkedIn respondeu 429 já na primeira página")
                break
            if resp.status_code != 200:
                log.warning("LinkedIn HTTP %d na página %d", resp.status_code, page)
                if not jobs:
                    raise SourceBlocked(f"LinkedIn respondeu HTTP {resp.status_code}")
                break

            page_jobs = self._parse_cards(resp.text)
            if not page_jobs:
                break  # fim dos resultados

            for job in page_jobs:
                if job.source_job_id not in seen:
                    seen.add(job.source_job_id)
                    jobs.append(job)

            if len(page_jobs) < PAGE_SIZE:
                break  # última página

            _sleep()

        return jobs[:limit]

    def _parse_cards(self, html: str) -> list[RawJob]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[RawJob] = []

        for card in soup.select("div.base-card[data-entity-urn]"):
            urn_match = URN_RE.search(card.get("data-entity-urn", ""))
            if not urn_match:
                continue

            title_el = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle")
            location_el = card.select_one("span.job-search-card__location")
            link_el = card.select_one("a.base-card__full-link")

            if not title_el or not link_el:
                continue

            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=urn_match.group(1),
                    url=_clean_url(link_el["href"]),
                    title=title_el.get_text(strip=True),
                    company=company_el.get_text(strip=True) if company_el else None,
                    location=location_el.get_text(strip=True) if location_el else None,
                    posted_at=_parse_posted_at(card),
                )
            )

        return jobs

    # -- detalhe -----------------------------------------------------

    def fetch_detail(self, job: RawJob) -> RawJob:
        """Preenche descrição e critérios. Request caro — só para vaga nova.

        Falha de detalhe não derruba a vaga: ela entra sem descrição e a
        IA simplesmente tem menos com o que trabalhar.

        O `_sleep()` vale aqui tanto quanto na paginação: sem ele o loop de
        detalhes dispara dezenas de requests seguidos e o LinkedIn devolve
        429 na 1ª ou 2ª vaga. Medido com 6 vagas: 6/6 descrições com pausa,
        bloqueio quase imediato sem.
        """
        _sleep()
        try:
            resp = self.session.get(DETAIL_URL.format(job_id=job.source_job_id), timeout=30)
            if resp.status_code == 429:
                raise SourceBlocked("LinkedIn 429 ao buscar detalhe")
            if resp.status_code != 200:
                log.warning("detalhe %s: HTTP %d", job.source_job_id, resp.status_code)
                return job
        except requests.RequestException as exc:
            log.warning("detalhe %s falhou: %s", job.source_job_id, exc)
            return job

        soup = BeautifulSoup(resp.text, "html.parser")

        markup = soup.select_one("div.show-more-less-html__markup")
        if markup:
            # Sanitiza ANTES de gravar: o front renderiza isso com
            # dangerouslySetInnerHTML e o conteúdo é de terceiros.
            job.description_html = sanitize_html(str(markup))
            job.description_text = markup.get_text("\n", strip=True)

        # O LinkedIn já entrega critérios estruturados — aproveitar antes da IA.
        # Atenção: as CHAVES seguem o Accept-Language ('Nível de experiência',
        # não 'Seniority level'). Não casar por chave literal em outro lugar —
        # isso vai cru no raw e quem normaliza é o enrich.
        criteria: dict[str, str] = {}
        for item in soup.select("li.description__job-criteria-item"):
            key_el = item.select_one("h3")
            val_el = item.select_one("span")
            if key_el and val_el:
                criteria[key_el.get_text(strip=True)] = val_el.get_text(strip=True)
        if criteria:
            job.raw["criteria"] = criteria

        # "Remote"/"Hybrid" às vezes vem colado no local do topo do detalhe.
        for flavor in soup.select("span.topcard__flavor--bullet"):
            text = flavor.get_text(strip=True).lower()
            if any(w in text for w in ("remote", "remoto", "hybrid", "híbrido")):
                job.work_model = flavor.get_text(strip=True)
                break

        return job


@register("linkedin")
def _factory() -> LinkedInConnector:
    return LinkedInConnector()


# -- CLI de verificação ----------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o conector LinkedIn isoladamente")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default=None)
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--detail", action="store_true", help="busca a descrição da 1ª vaga")
    parser.add_argument("--dry-run", action="store_true", help="só imprime, não grava")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    connector = LinkedInConnector()
    profile = SearchProfile(
        id=None,
        keywords=args.keywords,
        location=args.location,
        remote_only=args.remote_only,
    )

    jobs = connector.search(profile, limit=args.limit)
    print(f"\n{len(jobs)} vagas\n")
    for job in jobs:
        posted = job.posted_at.date().isoformat() if job.posted_at else "?"
        print(f"[{job.source_job_id}] {job.title}")
        print(f"    {job.company or '?'} — {job.location or '?'} — {posted}")
        print(f"    {job.url}")

    if args.detail and jobs:
        print("\n--- detalhe da 1ª vaga ---")
        detailed = connector.fetch_detail(jobs[0])
        print("critérios:", detailed.raw.get("criteria"))
        print("work_model:", detailed.work_model)
        text = detailed.description_text or ""
        print(f"descrição: {len(text)} chars")
        print(text[:400])

    if not args.dry_run:
        print("\n(--dry-run não passado, mas gravação só existe via run.py)")


if __name__ == "__main__":
    main()
