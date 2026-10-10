"""Conectores Selecty — portais de vagas de consultorias de RH (Harmona, InCompany).

A Selecty é a plataforma de R&S de várias consultorias; cada uma tem um
portal em <consultoria>.selecty.com.br. Interessam aqui duas que anunciam
vagas administrativas/financeiras na região de Pelotas:

  harmona.selecty.com.br    incompany.selecty.com.br

## BLOQUEIO (out/2026) — TODO

Os dois portais respondem **403 Forbidden do nginx para IP de datacenter**,
desta VM (Oracle Cloud): curl, requests e Chromium via Botasaurus — com
google_get, human mode e cookies limpos — tomam o mesmo 403 de 500 bytes,
sem challenge JS. É bloqueio por IP/ASN, e browser nenhum resolve isso.

O conector existe e roda 1x/dia (timer job-scraper-browser) para:
  1. registrar `blocked` em scrape_runs — resultado NORMAL, não erro;
  2. começar a colher sozinho se o bloqueio cair um dia.

Destravar de verdade exigiria sair por um IP residencial (proxy residencial
ou o worker rodando numa máquina em casa). Decisão do dono do projeto
(out/2026): NÃO usar proxy residencial por ora.

## Formato (NÃO validado nestes dois portais)

O parser foi escrito a partir de snapshots do Wayback Machine de OUTRO
portal Selecty (admvital.selecty.com.br, mai/2024), porque harmona e
incompany nunca responderam 200 daqui. O tema da plataforma é o mesmo
para todas as consultorias, mas pode ter mudado desde 2024:

  lista   GET /
          -> <li><div class="box"><a href=".../vaga/<id>/<slug>">
                <span>Vaga para <strong>Título</strong> em Cidade - UF - Brasil</span>
                <small title="21/05/2024 15:10:05">há 2 dias</small>
  detalhe GET /vaga/<id>/<slug>
          -> div.vaga com <h2>Título em Cidade</h2>, <p> de descrição e
             "Sobre a empresa"; sem JSON-LD

Se o portal abrir e o parser não achar nada, o HTML vai para
/tmp/job-scraper-debug/ e o log avisa — sinal para revisar os seletores.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from connectors.base import register
from location import matches_keywords, parse_location, same_place
from models import RawJob, SearchProfile, SourceBlocked
from sanitize import html_to_text, sanitize_html

log = logging.getLogger(__name__)

PORTALS = {
    "harmona": "https://harmona.selecty.com.br",
    "incompany": "https://incompany.selecty.com.br",
}

# Detalhes por rodada. Cada um é uma navegação no browser; os portais de
# consultoria têm dezenas de vagas, não milhares.
MAX_DETAILS = 25

JOB_PATH_RE = re.compile(r"/vaga/(\d+)(?:/|$)")

DEBUG_DIR = Path("/tmp/job-scraper-debug")

BLOCK_MARKERS = ("403 forbidden", "access denied", "acesso negado")


def _is_blocked(title: str, html: str) -> bool:
    if "403" in (title or ""):
        return True
    head = html[:2000].lower()
    return any(marker in head for marker in BLOCK_MARKERS)


def _dump_debug(name: str, html: str) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.html"
    try:
        path.write_text(html, encoding="utf-8")
    except OSError as exc:
        log.debug("dump falhou: %s", exc)
    return str(path)


def _parse_posted(small) -> datetime | None:
    """<small title="21/05/2024 15:10:05">há 2 dias</small>."""
    if small is None or not small.get("title"):
        return None
    try:
        return datetime.strptime(small["title"].strip(), "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None


def _split_city(location: str | None) -> tuple[str | None, str | None]:
    """'Pelotas - RS - Brasil' -> ('Pelotas', 'RS') (UF crua; same_place aceita)."""
    if not location:
        return None, None
    parts = [p.strip() for p in location.split(" - ") if p.strip()]
    if not parts:
        return None, None
    return parts[0], (parts[1] if len(parts) > 1 else None)


def parse_list(html: str, source: str, base_url: str) -> list[RawJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[RawJob] = []
    seen: set[str] = set()

    for link in soup.select('a[href*="/vaga/"]'):
        href = link["href"].split("?", 1)[0]
        match = JOB_PATH_RE.search(href)
        title_el = link.select_one("strong")
        if not match or not title_el:
            continue

        job_id = match.group(1)
        if job_id in seen:
            continue
        seen.add(job_id)

        title = " ".join(title_el.get_text(strip=True).split())
        span = link.select_one("span")
        text = " ".join(span.get_text(" ", strip=True).split()) if span else ""
        # "Vaga para <título> em <local>": o local é o que vem depois do último " em ".
        location = text.rsplit(" em ", 1)[1].strip() if " em " in text else None

        jobs.append(
            RawJob(
                source=source,
                source_job_id=job_id,
                url=href if href.startswith("http") else f"{base_url}{href}",
                title=title,
                # O portal é da consultoria; o contratante, quando aparece,
                # está no "Sobre a empresa" do detalhe.
                company=None,
                location=location,
                posted_at=_parse_posted(link.select_one("small")),
                raw={"list_text": text},
            )
        )

    return jobs


def parse_detail(html: str, job: RawJob) -> None:
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one("div.vaga")
    if box is None:
        return

    # Fora da descrição: código da vaga, botão de candidatura e compartilhamento.
    for junk in box.select("small, div.vaga-compartilhar, a[href*='inscribe=']"):
        junk.decompose()

    job.description_html = sanitize_html(str(box))
    job.description_text = html_to_text(str(box))


class SelectyConnector:
    def __init__(self, name: str, base_url: str) -> None:
        self.name = name
        self.base_url = base_url

    def search(self, profile: SearchProfile, limit: int = 50) -> list[RawJob]:
        # Import tardio: o Botasaurus sobe um Chromium, caro para pagar em
        # `import` quando só as fontes HTTP vão rodar.
        from botasaurus.browser import browser

        from config import chrome_path

        name, base_url = self.name, self.base_url
        city, state = parse_location(profile.location)

        def wanted(job: RawJob) -> bool:
            if not matches_keywords(profile.keywords, f"{job.title} {job.raw.get('list_text', '')}"):
                return False
            if city and not profile.remote_only:
                job_city, job_uf = _split_city(job.location)
                return same_place(job_city, job_uf, city, state)
            return True

        @browser(
            headless=True,
            output=None,
            block_images=True,
            close_on_crash=True,
            reuse_driver=False,
            chrome_executable_path=chrome_path(),
        )
        def _scrape(driver, _data) -> dict[str, Any]:
            # Devolve só HTML (string): o retorno do @browser pode ser
            # serializado, e RawJob/datetime não sobrevivem a isso.
            driver.delete_cookies_and_local_storage()
            driver.enable_human_mode()
            driver.google_get(f"{base_url}/")
            driver.short_random_sleep()

            html = driver.page_html
            if _is_blocked(driver.title, html):
                return {"blocked": True}

            # Detalhe no MESMO browser: abrir um Chromium por vaga não compensa.
            targets = [j.url for j in parse_list(html, name, base_url) if wanted(j)][:MAX_DETAILS]
            details: dict[str, str] = {}
            for url in targets:
                driver.get(url)
                driver.short_random_sleep()
                details[url] = driver.page_html

            return {"blocked": False, "list_html": html, "details": details}

        result = _scrape()
        if isinstance(result, list):  # botasaurus às vezes embrulha em lista
            result = result[0]

        if result.get("blocked"):
            raise SourceBlocked(
                f"{name}.selecty.com.br: 403 para IP de datacenter (esperado — "
                "ver TODO em connectors/selecty.py)"
            )

        listed = parse_list(result["list_html"], name, base_url)
        if not listed:
            dump = _dump_debug(name, result["list_html"])
            log.warning("%s: portal abriu mas nenhuma vaga parseada — seletores? %s", name, dump)

        jobs = [j for j in listed if wanted(j)][:limit]
        details = result.get("details") or {}
        for job in jobs:
            if job.url in details:
                parse_detail(details[job.url], job)
        return jobs


@register("harmona")
def _harmona() -> SelectyConnector:
    return SelectyConnector("harmona", PORTALS["harmona"])


@register("incompany")
def _incompany() -> SelectyConnector:
    return SelectyConnector("incompany", PORTALS["incompany"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa um portal Selecty isoladamente")
    parser.add_argument("portal", choices=sorted(PORTALS))
    parser.add_argument("--keywords", default="")
    parser.add_argument("--location", default=None, help='ex: "Pelotas, RS"')
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--html", help="parseia um HTML salvo (lista) em vez de abrir o browser — teste offline"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.html:
        jobs = parse_list(Path(args.html).read_text(errors="replace"), args.portal, PORTALS[args.portal])
    else:
        profile = SearchProfile(id=None, keywords=args.keywords, location=args.location)
        try:
            jobs = SelectyConnector(args.portal, PORTALS[args.portal]).search(profile, limit=args.limit)
        except SourceBlocked as exc:
            print(f"\nBLOQUEADO: {exc}")
            return

    print(f"\n{len(jobs)} vagas\n")
    for job in jobs:
        posted = job.posted_at.date().isoformat() if job.posted_at else "?"
        print(f"[{job.source_job_id}] {job.title[:70]}")
        print(f"    {job.location or '?'} — {posted} — desc: {len(job.description_text or '')} chars")


if __name__ == "__main__":
    main()
