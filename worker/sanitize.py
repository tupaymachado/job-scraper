"""Sanitiza HTML de descrição vindo de fonte externa.

O front renderiza description_html com dangerouslySetInnerHTML. Como o
conteúdo vem de terceiros (qualquer um publica uma vaga), ele tem que
estar limpo ANTES de entrar no banco — sanitizar só na renderização
deixaria payload perigoso armazenado esperando o próximo consumidor.

Allowlist restrita: descrição de vaga é texto formatado, não precisa de
mais que isso.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Comment

ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "span", "div", "a",
}

# Só href em <a>. Nada de style (CSS injection) nem on* (handlers).
ALLOWED_ATTRS = {"a": {"href"}}

SAFE_SCHEMES = ("http://", "https://", "mailto:")


def sanitize_html(html: str | None) -> str | None:
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Remove nós perigosos inteiros, com conteúdo.
    for tag in soup.find_all(["script", "style", "iframe", "object", "embed", "form", "input"]):
        tag.decompose()

    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            # unwrap preserva o texto e joga fora só a tag.
            tag.unwrap()
            continue

        allowed = ALLOWED_ATTRS.get(tag.name, set())
        for attr in list(tag.attrs):
            if attr not in allowed:
                del tag[attr]

        # javascript:/data: em href continuariam executando.
        href = tag.get("href")
        if href and not href.lower().startswith(SAFE_SCHEMES):
            del tag["href"]

    return str(soup)
