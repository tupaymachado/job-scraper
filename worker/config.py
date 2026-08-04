"""Configuração do worker. Segredos vêm de worker/.env (chmod 600, fora do git)."""

from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"


def _load_env() -> None:
    """Carrega .env sem depender de python-dotenv (não está no venv)."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY", "")
OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")

# Modelo barato para extrair campos estruturados de muitas vagas.
ENRICH_MODEL = os.environ.get("ENRICH_MODEL", "gemini-3.5-flash")
# Modelo forte, só nas vagas que passam o prefiltro.
MATCH_MODEL = os.environ.get("MATCH_MODEL", "claude-sonnet-5")


def require_supabase() -> tuple[str, str]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise SystemExit(
            "Faltam SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.\n"
            f"Crie {ENV_PATH} a partir de .env.example (chmod 600)."
        )
    return SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY


def require_opencode() -> str:
    if not OPENCODE_API_KEY:
        raise SystemExit(
            "Falta OPENCODE_API_KEY.\n"
            "Pegue em https://opencode.ai/auth e coloque em worker/.env."
        )
    return OPENCODE_API_KEY
