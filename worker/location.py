"""Localização dos perfis de busca, compartilhada entre os conectores.

O perfil guarda texto livre ("Pelotas, RS", "Brazil"). Fontes que não
filtram por local no servidor (ou filtram mal) usam isto para pós-filtrar.
"""

from __future__ import annotations

import re
import unicodedata

UF_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia",
    "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}

# Local que é o país inteiro não restringe nada (perfis antigos usam "Brazil").
COUNTRY_NAMES = {"brazil", "brasil", "br"}


def fold(text: str | None) -> str:
    """Minúsculas e sem acento, para comparar 'São Paulo' com 'Sao Paulo'."""
    normalized = unicodedata.normalize("NFKD", (text or "").strip().lower())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def parse_location(location: str | None) -> tuple[str | None, str | None]:
    """'Pelotas, RS' -> ('Pelotas', 'Rio Grande do Sul'). País inteiro -> (None, None).

    Aceita 'Cidade, UF', 'Cidade - UF', 'Cidade/UF' e só 'Cidade'.
    """
    if not location or fold(location) in COUNTRY_NAMES:
        return None, None

    parts = [p.strip() for p in re.split(r"[,/]|\s-\s", location) if p.strip()]
    parts = [p for p in parts if fold(p) not in COUNTRY_NAMES]
    if not parts:
        return None, None

    city = parts[0]
    state = None
    if len(parts) > 1:
        state = UF_NAMES.get(parts[1].upper(), parts[1])
    return city, state


def same_place(city: str | None, state: str | None, want_city: str, want_state: str | None) -> bool:
    """A vaga (city, state) está no local pedido? Estado ausente na vaga não reprova.

    `state` da vaga pode vir como UF ("RS") ou por extenso ("Rio Grande do Sul").
    """
    if fold(city) != fold(want_city):
        return False
    if want_state is None or not state:
        return True
    state_name = UF_NAMES.get(state.strip().upper(), state)
    return fold(state_name) == fold(want_state)
