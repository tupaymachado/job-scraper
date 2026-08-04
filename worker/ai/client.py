"""Cliente do openCode Zen (API compatível com OpenAI).

Base: https://opencode.ai/zen/v1 — Bearer OPENCODE_API_KEY.
Só `requests`, sem SDK: usamos um endpoint só.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from config import OPENCODE_BASE_URL, require_opencode

log = logging.getLogger(__name__)

# Modelos costumam devolver JSON dentro de ```json ... ```
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class OpenCodeError(RuntimeError):
    pass


def chat(
    messages: list[dict[str, str]],
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 2000,
    retries: int = 3,
) -> str:
    key = require_opencode()
    url = f"{OPENCODE_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            if resp.status_code == 429:
                wait = 2**attempt * 5
                log.warning("openCode 429, aguardando %ds", wait)
                time.sleep(wait)
                continue
            if not resp.ok:
                raise OpenCodeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, OpenCodeError) as exc:
            last_error = exc
            log.warning("tentativa %d/%d falhou: %s", attempt + 1, retries, exc)
            time.sleep(2**attempt)

    raise OpenCodeError(f"falhou após {retries} tentativas: {last_error}")


def chat_json(messages: list[dict[str, str]], model: str, **kwargs: Any) -> dict[str, Any] | None:
    """Como `chat`, mas devolve dict. None se o modelo não produzir JSON válido.

    Devolver None em vez de levantar é proposital: uma vaga que o modelo
    não conseguiu parsear não pode derrubar o lote inteiro.
    """
    content = chat(messages, model, **kwargs).strip()

    fence = FENCE_RE.search(content)
    if fence:
        content = fence.group(1).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Última tentativa: primeiro objeto {...} no texto.
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
        log.warning("resposta não é JSON válido: %s", content[:200])
        return None
