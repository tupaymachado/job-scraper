"""Acesso ao Supabase via PostgREST.

Usa `requests` direto em vez do SDK supabase-py de propósito: o venv
~/botasaurus-env é compartilhado com outras ferramentas e o SDK arrastaria
httpx/pydantic/gotrue para dentro dele. A superfície que usamos é pequena.

A service_role key passa por cima da RLS — este módulo só roda na VM.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from config import require_supabase
from dedup import make_dedup_key
from models import RawJob, SearchProfile

log = logging.getLogger(__name__)

JOB_COLUMNS = (
    "source,source_job_id,url,title,company,location,"
    "work_model,posted_at,description_html,description_text,raw"
)


class Store:
    def __init__(self) -> None:
        url, key = require_supabase()
        self.base = f"{url.rstrip('/')}/rest/v1"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.session.request(method, f"{self.base}/{path}", timeout=30, **kwargs)
        if not resp.ok:
            raise RuntimeError(f"Supabase {method} {path} -> {resp.status_code}: {resp.text[:300]}")
        if resp.status_code == 204 or not resp.text:
            return None
        return resp.json()

    # -- leitura -----------------------------------------------------

    def enabled_search_profiles(self) -> list[SearchProfile]:
        rows = self._request("GET", "search_profiles", params={"enabled": "eq.true", "select": "*"})
        return [SearchProfile.from_row(r) for r in rows or []]

    def get_search_profile(self, profile_id: str) -> SearchProfile | None:
        rows = self._request(
            "GET", "search_profiles", params={"id": f"eq.{profile_id}", "select": "*"}
        )
        return SearchProfile.from_row(rows[0]) if rows else None

    def existing_source_ids(self, source: str, source_job_ids: list[str]) -> set[str]:
        """Quais desses IDs já estão no banco.

        É o que evita gastar um request de detalhe por vaga já conhecida —
        o detalhe é o request mais caro do orçamento de rate limit.
        """
        if not source_job_ids:
            return set()

        found: set[str] = set()
        # PostgREST monta a query na URL; lotes evitam estourar o tamanho.
        for i in range(0, len(source_job_ids), 100):
            chunk = source_job_ids[i : i + 100]
            in_list = ",".join(f'"{sid}"' for sid in chunk)
            rows = self._request(
                "GET",
                "jobs",
                params={
                    "source": f"eq.{source}",
                    "source_job_id": f"in.({in_list})",
                    "select": "source_job_id",
                },
            )
            found.update(r["source_job_id"] for r in rows or [])
        return found

    # -- escrita -----------------------------------------------------

    def upsert_jobs(self, jobs: list[RawJob]) -> int:
        """Insere ignorando duplicatas e liga as duplicatas. Retorna as novas.

        Dedup em duas camadas:
          1. (source, source_job_id) unique — a mesma vaga, relida da mesma
             fonte, não vira linha nova.
          2. dedup_key (título+empresa normalizados) — a mesma vaga vista em
             fontes diferentes, ou republicada pela mesma fonte com outro id.
             A primeira vista vira canônica; as demais recebem canonical_id,
             somem do feed e somam sua fonte/link na canônica.

        A camada 2 vale também DENTRO da mesma fonte: o LinkedIn republica a
        mesma vaga por cidade com source_job_id diferente (visto de verdade —
        "React Engineer - Remote, Latin America" da Bluelight aparecendo em
        Porto Alegre e Salvador). A unique da camada 1 não pega esse caso.

        Inserimos em duas fases porque uma duplicata pode ter sua canônica no
        MESMO lote: só depois do primeiro insert é que o id dela existe para
        ser referenciado.
        """
        if not jobs:
            return 0

        for job in jobs:
            job.dedup_key = make_dedup_key(job.title, job.company)

        canonicals = self._canonical_by_dedup_key([j.dedup_key for j in jobs if j.dedup_key])

        first_wave: list[dict[str, Any]] = []
        second_wave: list[dict[str, Any]] = []
        claimed: set[str] = set()

        for job in jobs:
            row = job.to_row()
            key = job.dedup_key or ""

            if key in canonicals:
                row["canonical_id"] = canonicals[key]["id"]
                first_wave.append(row)
            elif key in claimed:
                # A canônica está neste mesmo lote e ainda não tem id.
                second_wave.append(row)
            else:
                claimed.add(key)
                row["sources"] = [job.source]
                first_wave.append(row)

        inserted = self._insert_rows(first_wave)

        if second_wave:
            # Agora as canônicas do lote existem: resolve e insere o resto.
            resolved = self._canonical_by_dedup_key([r["dedup_key"] for r in second_wave])
            for row in second_wave:
                canonical = resolved.get(row["dedup_key"] or "")
                if canonical:
                    row["canonical_id"] = canonical["id"]
                else:
                    row["sources"] = [row["source"]]
            inserted += self._insert_rows(second_wave)

        return len(inserted)

    def _insert_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        inserted = (
            self._request(
                "POST",
                "jobs",
                params={
                    "on_conflict": "source,source_job_id",
                    "select": "id,canonical_id,source,url",
                },
                headers={
                    # ignore-duplicates: uma vaga já vista não é sobrescrita.
                    "Prefer": "resolution=ignore-duplicates,return=representation",
                },
                json=rows,
            )
            or []
        )
        self._attach_to_canonicals(inserted)
        return inserted

    def _canonical_by_dedup_key(self, dedup_keys: list[str]) -> dict[str, dict[str, Any]]:
        """Canônicas já existentes para essas chaves (canonical_id is null)."""
        found: dict[str, dict[str, Any]] = {}
        unique_keys = list({k for k in dedup_keys if k})

        for i in range(0, len(unique_keys), 50):
            chunk = unique_keys[i : i + 50]
            in_list = ",".join('"' + k.replace('"', '""') + '"' for k in chunk)
            rows = self._request(
                "GET",
                "jobs",
                params={
                    "dedup_key": f"in.({in_list})",
                    "canonical_id": "is.null",
                    "select": "id,dedup_key,source",
                },
            )
            for row in rows or []:
                # Primeira vista vence: não sobrescreve uma canônica já achada.
                found.setdefault(row["dedup_key"], row)
        return found

    def _attach_to_canonicals(self, inserted: list[dict[str, Any]]) -> None:
        """Soma fonte e link das duplicatas recém-criadas na canônica.

        Denormalizar aqui evita um embed auto-referencial no PostgREST só
        para o card mostrar os badges de fonte.
        """
        by_canonical: dict[str, list[dict[str, Any]]] = {}
        for row in inserted:
            if row.get("canonical_id"):
                by_canonical.setdefault(row["canonical_id"], []).append(row)

        for canonical_id, duplicates in by_canonical.items():
            current = self._request(
                "GET", "jobs", params={"id": f"eq.{canonical_id}", "select": "sources,alt_urls"}
            )
            if not current:
                continue

            sources = list(current[0].get("sources") or [])
            alt_urls = list(current[0].get("alt_urls") or [])
            known = {entry.get("url") for entry in alt_urls}

            for duplicate in duplicates:
                if duplicate["source"] not in sources:
                    sources.append(duplicate["source"])
                if duplicate.get("url") and duplicate["url"] not in known:
                    alt_urls.append({"source": duplicate["source"], "url": duplicate["url"]})
                    known.add(duplicate["url"])

            self._request(
                "PATCH",
                "jobs",
                params={"id": f"eq.{canonical_id}"},
                json={"sources": sources, "alt_urls": alt_urls},
            )

    # -- scrape_runs -------------------------------------------------

    def start_run(self, source: str, search_profile_id: str | None) -> str:
        rows = self._request(
            "POST",
            "scrape_runs",
            headers={"Prefer": "return=representation"},
            json={"source": source, "search_profile_id": search_profile_id},
        )
        return rows[0]["id"]

    def finish_run(
        self,
        run_id: str,
        status: str,
        jobs_found: int = 0,
        jobs_new: int = 0,
        error: str | None = None,
    ) -> None:
        self._request(
            "PATCH",
            "scrape_runs",
            params={"id": f"eq.{run_id}"},
            json={
                "status": status,
                "jobs_found": jobs_found,
                "jobs_new": jobs_new,
                "error": error,
                "finished_at": "now()",
            },
        )

    # -- fila de scrape sob demanda ----------------------------------

    def claim_scrape_request(self) -> dict[str, Any] | None:
        """Pega o pedido pendente mais antigo e marca como running.

        O PATCH filtra por status='pending' de novo, então dois workers
        concorrentes não pegam o mesmo pedido.
        """
        pending = self._request(
            "GET",
            "scrape_requests",
            params={
                "status": "eq.pending",
                "select": "*",
                "order": "requested_at.asc",
                "limit": "1",
            },
        )
        if not pending:
            return None

        claimed = self._request(
            "PATCH",
            "scrape_requests",
            params={"id": f"eq.{pending[0]['id']}", "status": "eq.pending"},
            headers={"Prefer": "return=representation"},
            json={"status": "running"},
        )
        return claimed[0] if claimed else None

    def finish_scrape_request(self, request_id: str, status: str, error: str | None = None) -> None:
        self._request(
            "PATCH",
            "scrape_requests",
            params={"id": f"eq.{request_id}"},
            json={"status": status, "error": error, "finished_at": "now()"},
        )

    # -- IA ----------------------------------------------------------

    def jobs_needing_enrichment(self, limit: int = 20) -> list[dict[str, Any]]:
        """Vagas com descrição mas ainda sem linha em job_enrichments."""
        return (
            self._request(
                "GET",
                "jobs",
                params={
                    "select": "id,title,company,location,description_text,raw,job_enrichments(job_id)",
                    "description_text": "not.is.null",
                    "canonical_id": "is.null",
                    "job_enrichments": "is.null",
                    "order": "first_seen_at.desc",
                    "limit": str(limit),
                },
            )
            or []
        )

    def save_enrichment(self, job_id: str, data: dict[str, Any], model: str) -> None:
        payload = {k: v for k, v in data.items() if v is not None}
        payload.update({"job_id": job_id, "model": model})
        self._request(
            "POST",
            "job_enrichments",
            params={"on_conflict": "job_id"},
            headers={"Prefer": "resolution=merge-duplicates"},
            json=payload,
        )

    def user_profile(self, user_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET", "user_profiles", params={"user_id": f"eq.{user_id}", "select": "*"}
        )
        return rows[0] if rows else None

    def jobs_needing_match(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Vagas já enriquecidas que esse usuário ainda não tem score."""
        scored = self._request(
            "GET", "job_matches", params={"user_id": f"eq.{user_id}", "select": "job_id"}
        )
        scored_ids = {r["job_id"] for r in scored or []}

        rows = (
            self._request(
                "GET",
                "jobs",
                params={
                    "select": "id,title,company,location,description_text,job_enrichments!inner(*)",
                    "order": "first_seen_at.desc",
                    "limit": str(limit + len(scored_ids)),
                },
            )
            or []
        )
        return [r for r in rows if r["id"] not in scored_ids][:limit]

    def save_match(self, user_id: str, job_id: str, score: int, reasoning: str, model: str) -> None:
        self._request(
            "POST",
            "job_matches",
            params={"on_conflict": "user_id,job_id"},
            headers={"Prefer": "resolution=merge-duplicates"},
            json={
                "user_id": user_id,
                "job_id": job_id,
                "score": score,
                "reasoning": reasoning,
                "model": model,
            },
        )
