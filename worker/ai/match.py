"""Score de aderência entre vaga e perfil do usuário.

Duas etapas de propósito:
  1. Prefiltro barato (overlap de stack/keywords) — descarta o obviamente
     irrelevante sem gastar token.
  2. Modelo forte (claude-sonnet-5) só no que passou.

Sem o prefiltro, pagaríamos reasoning caro em vaga de Java para um perfil
de front-end.
"""

from __future__ import annotations

import argparse
import logging
import re
from typing import Any

from ai.client import chat_json
from config import MATCH_MODEL
from store import Store

log = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 4000
PREFILTER_MIN_OVERLAP = 1

SYSTEM = """Você avalia o quanto uma vaga combina com o perfil de um candidato.
Responda APENAS com JSON, sem texto ao redor e sem blocos de código:

{"score": <0-100>, "reasoning": "<2 frases em português>"}

Escala:
  0-30   incompatível (stack errada, senioridade muito distante)
  31-60  parcial (algum overlap, lacunas relevantes)
  61-85  bom encaixe (stack principal bate, senioridade compatível)
  86-100 encaixe forte (bate stack, senioridade, modelo de trabalho e domínio)

Seja criterioso: reserve 86+ para quem o candidato tem chance real. Cite no
reasoning o fator que mais pesou, positivo ou negativo."""

WORD_RE = re.compile(r"[a-záàâãéêíóôõúç0-9+#.]{2,}", re.I)

# Palavras genéricas demais para contarem como sinal de match.
STOPWORDS = {
    "de", "da", "do", "com", "para", "em", "e", "o", "a", "os", "as", "um", "uma",
    "experiencia", "experiência", "conhecimento", "vaga", "empresa", "trabalho",
    "desenvolvedor", "developer", "analista", "engenheiro", "engineer", "pessoa",
}


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in WORD_RE.findall(text or "")} - STOPWORDS


def passes_prefilter(job: dict[str, Any], profile_tokens: set[str]) -> bool:
    """Overlap mínimo entre a stack/título da vaga e o perfil do candidato."""
    enrichment = job.get("job_enrichments") or {}
    if isinstance(enrichment, list):
        enrichment = enrichment[0] if enrichment else {}

    job_tokens = _tokens(job.get("title", ""))
    job_tokens |= {s.lower() for s in (enrichment.get("stack") or [])}
    job_tokens |= {s.lower() for s in (enrichment.get("tags") or [])}

    return len(job_tokens & profile_tokens) >= PREFILTER_MIN_OVERLAP


def _prompt(job: dict[str, Any], cv_text: str, preferences: str | None) -> str:
    enrichment = job.get("job_enrichments") or {}
    if isinstance(enrichment, list):
        enrichment = enrichment[0] if enrichment else {}

    return f"""## Candidato

CV:
{cv_text[:MAX_DESCRIPTION_CHARS]}

Preferências: {preferences or 'não informadas'}

## Vaga

Título: {job.get('title')}
Empresa: {job.get('company') or '?'}
Local: {job.get('location') or '?'}
Senioridade: {enrichment.get('seniority') or '?'}
Stack: {', '.join(enrichment.get('stack') or []) or '?'}
Modelo: {enrichment.get('work_model') or '?'}
Contrato: {enrichment.get('contract_type') or '?'}

Descrição:
{(job.get('description_text') or '')[:MAX_DESCRIPTION_CHARS]}"""


def score_job(
    store: Store, user_id: str, job: dict[str, Any], cv_text: str, preferences: str | None, model: str
) -> int | None:
    data = chat_json(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _prompt(job, cv_text, preferences)},
        ],
        model=model,
        # Aqui o raciocínio fica ligado: pontuar CV contra vaga é julgamento,
        # não extração. Mas então o orçamento tem que caber raciocínio +
        # resposta — com 400 o modelo pensava até o limite e devolvia vazio.
        max_tokens=2000,
    )
    if data is None:
        return None

    raw_score = data.get("score")
    if not isinstance(raw_score, (int, float)):
        log.warning("vaga %s: score ausente ou inválido", job["id"])
        return None

    score = max(0, min(100, int(raw_score)))
    reasoning = str(data.get("reasoning") or "")[:1000]
    store.save_match(user_id, job["id"], score, reasoning, model)
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description="Calcula score de aderência das vagas")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--model", default=MATCH_MODEL)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    store = Store()
    profile = store.user_profile(args.user_id)
    if not profile or not profile.get("cv_text"):
        log.error("usuário %s não tem cv_text — preencha em /profile antes", args.user_id)
        return 1

    cv_text = profile["cv_text"]
    preferences = profile.get("preferences")
    profile_tokens = _tokens(cv_text) | _tokens(preferences or "")

    jobs = store.jobs_needing_match(args.user_id, limit=args.limit)
    if not jobs:
        log.info("nenhuma vaga pendente de score")
        return 0

    scored = skipped = 0
    for job in jobs:
        if not passes_prefilter(job, profile_tokens):
            # Sem overlap nenhum: score 0 direto, sem gastar token.
            store.save_match(args.user_id, job["id"], 0, "Sem overlap com o perfil (prefiltro).", "prefilter")
            skipped += 1
            continue

        try:
            score = score_job(store, args.user_id, job, cv_text, preferences, args.model)
            if score is not None:
                scored += 1
                log.info("  %3d  %s", score, (job.get("title") or "")[:65])
        except Exception:  # noqa: BLE001
            log.exception("  ✗ %s", job["id"])

    log.info("%d avaliadas pelo modelo, %d cortadas no prefiltro", scored, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
