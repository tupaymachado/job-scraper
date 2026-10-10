"""Conector Gupy via API pública do portal — HTTP puro, sem browser.

A Gupy é o ATS dominante no Brasil; milhares de empresas publicam por ela.
O portal de vagas expõe uma API JSON sem autenticação:

  GET https://portal.gupy.io/api/job-search/jobs
      ?jobName=<termo>&limit=<n>&offset=<n>&workplaceType=remote|hybrid|onsite

HISTÓRICO (out/2026): o endpoint antigo employability-portal.gupy.io/api/v1/jobs
morreu com 404 global de nginx (confirmado por scrapers de terceiros em
set/2026). O portal foi reescrito e hoje chama a API na própria origem,
descoberto via devtools em portal.gupy.io/job-search. Formato da resposta:
{data: [...jobs], pagination: {...}}. Campos do job: id, name, jobUrl,
careerPageName, careerPageUrl, city, state, workplaceType, type,
description (HTML), publishedDate, applicationDeadline, badges,
disabilities. Detalhe: alguns jobs trazem careerPageName como slogan de
marketing e city/state vazios — o _company() já trata.

Validado out/2026 desta VM: HTTP 200 direto via requests, sem cookie nem
token; detalhe da vaga continua em <careerPageUrl>/job/<id>.

LOCALIZAÇÃO: `jobName` sozinho ignora o local — "administrativo" devolve
~3000 vagas do Brasil inteiro e as de Pelotas nunca chegam nas primeiras
páginas. O parâmetro `city=<nome>` filtra no servidor (medido out/2026:
6 vagas "administrativo" em Pelotas); `state` só aceita o nome por extenso
("Rio Grande do Sul", não "RS"). Para perfil com cidade, fazemos duas
buscas — a da cidade e a das remotas, que valem de qualquer lugar — e
pós-filtramos tudo por city/state, porque o filtro do servidor não é
documentado e pode mudar sem aviso.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import time
from datetime import datetime
from typing import Any, Callable

import requests

from connectors.base import register
from location import parse_location, same_place
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import sanitize_html

log = logging.getLogger(__name__)

API_URL = "https://portal.gupy.io/api/job-search/jobs"

PAGE_SIZE = 50
MAX_PAGES = 10

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Vocabulário da Gupy -> nosso vocabulário.
WORKPLACE_MAP = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial"}


def _in_location(item: dict[str, Any], city: str, state: str | None) -> bool:
    return same_place(item.get("city"), item.get("state"), city, state)


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
        city, state = parse_location(profile.location)

        if profile.remote_only or not city:
            # Sem cidade (ou só remoto) o local não restringe: busca única.
            extra = {"workplaceType": "remote"} if profile.remote_only else {}
            return self._collect(profile.keywords, extra, limit, keep=None)

        # Com cidade: primeiro as vagas dela, depois as remotas preenchem o
        # que sobrar do limite. Remota vale de qualquer lugar, então entra.
        def keep(item: dict[str, Any]) -> bool:
            return item.get("workplaceType") == "remote" or _in_location(item, city, state)

        local_params = {"city": city}
        if state:
            local_params["state"] = state
        jobs = self._collect(profile.keywords, local_params, limit, keep=keep)
        log.info("Gupy: %d vagas em %s", len(jobs), city)

        if len(jobs) < limit:
            seen = {j.source_job_id for j in jobs}
            remote = self._collect(
                profile.keywords, {"workplaceType": "remote"}, limit - len(jobs),
                keep=keep, seen=seen, has_results=bool(jobs),
            )
            log.info("Gupy: + %d remotas", len(remote))
            jobs.extend(remote)

        return jobs[:limit]

    def _collect(
        self,
        keywords: str,
        extra_params: dict[str, Any],
        limit: int,
        keep: Callable[[dict[str, Any]], bool] | None,
        seen: set[str] | None = None,
        has_results: bool = False,
    ) -> list[RawJob]:
        """Pagina uma busca. `keep` é o pós-filtro aplicado item a item.

        `has_results` diz se uma busca anterior do mesmo perfil já colheu
        algo: aí um erro aqui não é bloqueio, só fim antecipado.
        """
        jobs: list[RawJob] = []
        seen = set(seen or ())

        for page in range(MAX_PAGES):
            if len(jobs) >= limit:
                break

            params: dict[str, Any] = {
                "jobName": keywords,
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
                **extra_params,
            }

            resp = self.session.get(API_URL, params=params, timeout=30)
            collected = bool(jobs) or has_results

            if resp.status_code == 429:
                log.warning("Gupy 429 na página %d (%d colhidas)", page, len(jobs))
                if not collected:
                    raise SourceBlocked("Gupy respondeu 429 já na primeira página")
                break
            if resp.status_code != 200:
                log.warning("Gupy HTTP %d na página %d", resp.status_code, page)
                if not collected:
                    raise SourceBlocked(f"Gupy respondeu HTTP {resp.status_code}")
                break

            items = (resp.json() or {}).get("data") or []
            if not items:
                break

            for item in items:
                if keep is not None and not keep(item):
                    continue
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
    parser.add_argument("--location", default=None, help='ex: "Pelotas, RS"')
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    profile = SearchProfile(
        id=None, keywords=args.keywords, location=args.location, remote_only=args.remote_only
    )
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
