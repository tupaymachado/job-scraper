"""Chave de dedup entre fontes.

A mesma vaga aparece no LinkedIn, na Gupy e de novo na Careerjet (que
reagrega as duas). Sem URL comum — a Careerjet devolve link de tracker
opaco — a única âncora confiável é título + empresa normalizados.

Calibragem: normalizar de menos deixa duplicata passar; normalizar de
mais funde vagas diferentes ("Dev Java Pleno" com "Dev Java Sênior"),
o que é bem pior. Na dúvida, deixamos passar a duplicata: senioridade,
stack e números ficam preservados na chave.
"""

from __future__ import annotations

import re
import unicodedata

# Ruído de formatação que varia entre fontes para a mesma vaga.
NOISE_PATTERNS = [
    r"\(remoto?\)", r"\(remote\)", r"\(h[ií]brido\)", r"\(presencial\)",
    r"\bvaga afirmativa\b", r"\bexclusiva? para\b.*$",
    r"\bpcd\b", r"\bpessoa com defici[êe]ncia\b",
    r"\bv\d+\b", r"\bref#?\s*\d+\b",
    # "- Remote, Latin America" / "| Home office SP": traço seguido de
    # modalidade engole o resto, que é sempre localidade/modalidade.
    r"[-–|·]\s*(remoto?|remote|home\s*office|h[ií]brido|presencial)\b.*$",
]

# Marcadores de linguagem inclusiva: só formatação, não mudam a vaga.
INCLUSIVE_PATTERNS = [
    (r"\bpessoa\s+desenvolvedora\b", "desenvolvedor"),
    (r"\bpessoa\s+engenheira\b", "engenheiro"),
    (r"\bpessoa\s+analista\b", "analista"),
    (r"\(a\)", ""),
    (r"\(o\)", ""),
    (r"\(as?\)", ""),
    (r"\bdesenvolvedora\b", "desenvolvedor"),
    (r"\bengenheira\b", "engenheiro"),
]

# Sufixos societários: "Locks" e "Locks Ltda" são a mesma empresa.
# Aplicado DEPOIS de _normalize, então "S.A." já chegou aqui como "s a".
COMPANY_SUFFIXES = (
    r"\b(ltda|s\s*a|me|epp|eireli|inc|llc|corp|group|grupo|brasil|brazil)\b"
)


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _normalize(text: str) -> str:
    text = _strip_accents(text.lower())
    for pattern, replacement in INCLUSIVE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text)
    # Pontuação vira espaço; preserva alfanumérico (senioridade, "c#", "node2").
    text = re.sub(r"[^a-z0-9#+]+", " ", text)
    return " ".join(text.split())


def normalize_company(company: str | None) -> str:
    if not company:
        return ""
    normalized = _normalize(company)
    normalized = re.sub(COMPANY_SUFFIXES, " ", normalized)
    return " ".join(normalized.split())


def make_dedup_key(title: str, company: str | None) -> str:
    """Chave estável para a mesma vaga vista em fontes diferentes.

    Sem empresa a chave fica só com o título — mais frouxo, mas é o que
    dá para fazer; a Careerjet às vezes omite a empresa.
    """
    normalized_title = _normalize(title)
    normalized_company = normalize_company(company)
    return f"{normalized_title}|{normalized_company}" if normalized_company else normalized_title
