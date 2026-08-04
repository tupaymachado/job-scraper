"""Extrai campos estruturados da descrição da vaga.

Modelo barato (gemini-3.5-flash por padrão) — roda em toda vaga nova.
Grava o `model` usado para dar pra reprocessar quando trocar de modelo.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from ai.client import chat_json
from config import ENRICH_MODEL
from store import Store

log = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 6000

SENIORITY = ("estagio", "junior", "pleno", "senior", "staff", "lead")
WORK_MODELS = ("remoto", "hibrido", "presencial")
CONTRACTS = ("clt", "pj", "estagio", "freelance", "temporario")

SYSTEM = """Você extrai dados estruturados de vagas de emprego brasileiras.
Responda APENAS com um objeto JSON, sem texto ao redor e sem blocos de código.

Campos:
  seniority      string|null  um de: estagio, junior, pleno, senior, staff, lead
  stack          string[]     tecnologias citadas, minúsculas (ex: ["react","typescript"])
  work_model     string|null  um de: remoto, hibrido, presencial
  contract_type  string|null  um de: clt, pj, estagio, freelance, temporario
  salary_min     number|null  em unidades da moeda, mensal
  salary_max     number|null
  salary_currency string|null ISO (BRL, USD)
  tags           string[]     3-6 tags curtas do domínio (ex: ["fintech","startup"])
  summary        string       UMA frase em português resumindo a vaga

Regras:
- Não invente. Campo ausente na descrição = null (ou [] para listas).
- Salário só se explícito. "a combinar" = null.
- Senioridade pelo texto; se só o título disser, use o título."""


def _prompt(job: dict[str, Any]) -> str:
    description = (job.get("description_text") or "")[:MAX_DESCRIPTION_CHARS]
    criteria = (job.get("raw") or {}).get("criteria") or {}
    criteria_text = "\n".join(f"{k}: {v}" for k, v in criteria.items())

    return f"""Título: {job.get('title')}
Empresa: {job.get('company') or '?'}
Local: {job.get('location') or '?'}
{f'Critérios da fonte:{chr(10)}{criteria_text}' if criteria_text else ''}

Descrição:
{description}"""


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Normaliza e descarta o que o modelo inventou fora do enum."""

    def enum(value: Any, allowed: tuple[str, ...]) -> str | None:
        if not isinstance(value, str):
            return None
        v = value.strip().lower()
        return v if v in allowed else None

    def str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [s.strip().lower() for s in value if isinstance(s, str) and s.strip()][:12]

    def number(value: Any) -> float | None:
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return None

    summary = data.get("summary")
    currency = data.get("salary_currency")

    return {
        "seniority": enum(data.get("seniority"), SENIORITY),
        "stack": str_list(data.get("stack")),
        "work_model": enum(data.get("work_model"), WORK_MODELS),
        "contract_type": enum(data.get("contract_type"), CONTRACTS),
        "salary_min": number(data.get("salary_min")),
        "salary_max": number(data.get("salary_max")),
        "salary_currency": currency.strip().upper()[:3] if isinstance(currency, str) else None,
        "tags": str_list(data.get("tags")),
        "summary": summary.strip()[:500] if isinstance(summary, str) else None,
    }


def enrich_job(store: Store, job: dict[str, Any], model: str) -> bool:
    data = chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(job)}],
        model=model,
        max_tokens=800,
    )
    if data is None:
        log.warning("vaga %s: modelo não devolveu JSON válido", job["id"])
        return False

    store.save_enrichment(job["id"], _clean(data), model)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Enriquece vagas com IA")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--model", default=ENRICH_MODEL)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    store = Store()
    jobs = store.jobs_needing_enrichment(limit=args.limit)
    if not jobs:
        log.info("nenhuma vaga pendente de enriquecimento")
        return 0

    log.info("enriquecendo %d vagas com %s", len(jobs), args.model)
    ok = 0
    for job in jobs:
        # Uma vaga que o modelo não parseou não pode derrubar o lote.
        try:
            if enrich_job(store, job, args.model):
                ok += 1
                log.info("  ✓ %s", (job.get("title") or "")[:70])
        except Exception:  # noqa: BLE001
            log.exception("  ✗ %s", job["id"])

    log.info("%d/%d enriquecidas", ok, len(jobs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
