"""Tipos compartilhados entre conectores, store e pipeline de IA."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class SearchProfile:
    """Uma busca salva do usuário. Espelha a tabela search_profiles."""

    id: str | None
    keywords: str
    location: str | None = None
    remote_only: bool = False
    sources: list[str] = field(default_factory=lambda: ["linkedin"])
    name: str = ""
    user_id: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SearchProfile:
        return cls(
            id=row["id"],
            keywords=row["keywords"],
            location=row.get("location"),
            remote_only=row.get("remote_only", False),
            sources=row.get("sources") or ["linkedin"],
            name=row.get("name", ""),
            user_id=row.get("user_id"),
        )


@dataclass
class RawJob:
    """Vaga como saiu da fonte, antes do enriquecimento por IA.

    `source` + `source_job_id` é a chave de dedup (unique no Postgres).
    `raw` guarda o que a fonte deu de estruturado, para reparsear
    depois sem precisar raspar de novo.
    """

    source: str
    source_job_id: str
    url: str
    title: str
    company: str | None = None
    location: str | None = None
    work_model: str | None = None
    posted_at: datetime | None = None
    description_html: str | None = None
    description_text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return row


class SourceBlocked(Exception):
    """A fonte bloqueou (429, captcha, challenge).

    Não é erro de código — é o caminho esperado para Google Jobs e para
    o LinkedIn quando se pagina demais. Vira scrape_runs.status='blocked'.
    """
