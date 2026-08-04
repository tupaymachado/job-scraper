"""Orquestrador do worker.

    python run.py --source linkedin --once      # roda os perfis habilitados
    python run.py --queue                       # drena scrape_requests
    python run.py --source google_jobs --once   # best-effort, pode vir 'blocked'

Bloqueio (429/captcha) é resultado esperado, não falha: vira
scrape_runs.status='blocked' e o processo sai com 0.
"""

from __future__ import annotations

import argparse
import logging
import sys

# Registra os conectores no REGISTRY (import por efeito colateral).
import connectors.google_jobs  # noqa: F401
import connectors.linkedin  # noqa: F401
from connectors.base import REGISTRY, get_connector
from models import SearchProfile, SourceBlocked
from store import Store

log = logging.getLogger("worker")

DETAIL_SOURCES = {"linkedin"}  # fontes cujo conector tem fetch_detail()


def scrape(store: Store, source: str, profile: SearchProfile, limit: int = 50) -> tuple[int, int]:
    """Roda um conector para um perfil e grava. Retorna (encontradas, novas)."""
    run_id = store.start_run(source, profile.id)
    connector = get_connector(source)

    try:
        jobs = connector.search(profile, limit=limit)
    except SourceBlocked as exc:
        log.warning("[%s] bloqueado: %s", source, exc)
        store.finish_run(run_id, "blocked", error=str(exc))
        return 0, 0
    except Exception as exc:  # noqa: BLE001 — um conector quebrado não derruba os outros
        log.exception("[%s] erro", source)
        store.finish_run(run_id, "error", error=repr(exc))
        return 0, 0

    log.info("[%s] %d vagas encontradas", source, len(jobs))

    # Só busca detalhe do que é novo — é o request mais caro do orçamento.
    if source in DETAIL_SOURCES and hasattr(connector, "fetch_detail"):
        known = store.existing_source_ids(source, [j.source_job_id for j in jobs])
        new_jobs = [j for j in jobs if j.source_job_id not in known]
        log.info("[%s] %d novas, buscando detalhe", source, len(new_jobs))

        for job in new_jobs:
            try:
                connector.fetch_detail(job)
            except SourceBlocked as exc:
                # Rate limit no meio dos detalhes: grava o que já tem e para.
                log.warning("[%s] bloqueado no detalhe: %s", source, exc)
                break

    try:
        inserted = store.upsert_jobs(jobs)
    except Exception as exc:  # noqa: BLE001
        log.exception("[%s] falha ao gravar", source)
        store.finish_run(run_id, "error", jobs_found=len(jobs), error=repr(exc))
        return len(jobs), 0

    log.info("[%s] %d novas gravadas", source, inserted)
    store.finish_run(run_id, "ok", jobs_found=len(jobs), jobs_new=inserted)
    return len(jobs), inserted


def run_source(store: Store, source: str, limit: int) -> None:
    profiles = store.enabled_search_profiles()
    targets = [p for p in profiles if source in p.sources]

    if not targets:
        log.info("nenhum perfil de busca habilitado usa a fonte %r", source)
        return

    total_found = total_new = 0
    for profile in targets:
        log.info("perfil %r (%s)", profile.name or profile.keywords, source)
        found, new = scrape(store, source, profile, limit=limit)
        total_found += found
        total_new += new

    log.info("total: %d encontradas, %d novas", total_found, total_new)


def drain_queue(store: Store, limit: int) -> None:
    """Consome scrape_requests — é assim que o botão 'Buscar agora' chega aqui."""
    while (request := store.claim_scrape_request()) is not None:
        log.info("pedido %s", request["id"])
        try:
            profile = store.get_search_profile(request["search_profile_id"])
            if profile is None:
                store.finish_scrape_request(request["id"], "error", "perfil de busca não encontrado")
                continue

            for source in profile.sources:
                if source in REGISTRY:
                    scrape(store, source, profile, limit=limit)
                else:
                    log.warning("fonte desconhecida no perfil: %r", source)

            store.finish_scrape_request(request["id"], "done")
        except Exception as exc:  # noqa: BLE001 — um pedido ruim não pode travar a fila
            log.exception("pedido %s falhou", request["id"])
            store.finish_scrape_request(request["id"], "error", repr(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker de scraping de vagas")
    parser.add_argument("--source", choices=sorted(REGISTRY), help="fonte a rodar")
    parser.add_argument("--queue", action="store_true", help="drena scrape_requests e sai")
    parser.add_argument("--once", action="store_true", help="uma passada e sai")
    parser.add_argument("--limit", type=int, default=50, help="máximo de vagas por perfil")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.source and not args.queue:
        parser.error("informe --source SOURCE ou --queue")

    store = Store()

    if args.queue:
        drain_queue(store, args.limit)
    else:
        run_source(store, args.source, args.limit)

    return 0


if __name__ == "__main__":
    sys.exit(main())
