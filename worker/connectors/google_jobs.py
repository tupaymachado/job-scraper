"""Conector Google Jobs via Botasaurus — best-effort, ~10 vagas/dia.

Porte do padrão validado em
~/.hermes/skills/research/botasaurus-scraping/references/job-sites-pattern.md
(jul/2026). NÃO alterar a receita anti-bot sem re-testar: cada detalhe abaixo
foi pago com uma rodada bloqueada.

LIMITE ESTRUTURAL: o Google flagra o IP depois de UM acesso automatizado. A
segunda rodada toma reCAPTCHA. headless=False, Xvfb e Tor NÃO desfazem o flag.
Por isso: 1 rodada/dia, e bloqueio é resultado normal (status='blocked'), não
erro. O carro-chefe é o LinkedIn.

Receita, em ordem de importância:
  1. driver.google_get()  — referrer de busca do Google. Foi a diferença entre
     captcha imediato e 10 cards. NUNCA driver.get().
  2. delete_cookies_and_local_storage() + enable_human_mode() antes de navegar.
  3. NUNCA scroll_to_bottom() — os cards div.mqj2af somem (0 cards depois).
  4. tiny_profile=True exige profile="nome" junto, senão ValueError.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup

from connectors.base import register
from models import RawJob, SearchProfile, SourceBlocked

log = logging.getLogger(__name__)

CARD_SELECTOR = "div.mqj2af"

# Ruído de UI que aparece misturado no texto do card.
UI_NOISE = ("Share", "Copy link", "Link copied", "Facebook", "Gmail", "Reddit", "WhatsApp", "X ")

TIME_RE = re.compile(r"(ago|atrás|hour|day|week|month|ano|dia|semana|hora)", re.I)
REMOTE_RE = re.compile(r"(work from home|remoto|remote|home office)", re.I)
CONTRACT_RE = re.compile(r"(full.time|part.time|contract|integral|parcial|CLT|PJ|estágio)", re.I)
VIA_RE = re.compile(r"via\s+(.+?)$")


DEBUG_DIR = Path("/tmp/job-scraper-debug")

# Sinais de bloqueio real. Não usar só `"captcha" in html`: a palavra aparece
# em scripts de página legítima e dá falso positivo.
BLOCK_MARKERS = (
    "our systems have detected unusual traffic",
    "tráfego incomum",
    "id=\"recaptcha\"",
    "g-recaptcha",
    "/sorry/index",
)


def _is_blocked(driver, html: str) -> bool:
    if driver.is_bot_detected():
        return True
    if "/sorry/" in (driver.current_url or ""):
        return True
    lowered = html.lower()
    return any(marker in lowered for marker in BLOCK_MARKERS)


def _dump_debug(driver, html: str) -> str:
    """Salva HTML + screenshot para diagnóstico pós-bloqueio."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = DEBUG_DIR / f"gjobs-{stamp}.html"
    try:
        path.write_text(html, encoding="utf-8")
        driver.save_screenshot(str(DEBUG_DIR / f"gjobs-{stamp}.png"))
    except Exception as exc:  # noqa: BLE001 — diagnóstico não pode quebrar o run
        log.debug("dump falhou: %s", exc)
    return str(path)


def _parse_cards(html: str, limit: int) -> list[RawJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[RawJob] = []
    seen: set[str] = set()

    for card in soup.select(CARD_SELECTOR):
        parts = [p.strip() for p in card.get_text("|", strip=True).split("|") if p.strip()]
        clean = [p for p in parts if not any(noise in p for noise in UI_NOISE)]
        if len(clean) < 3:
            continue

        title, company = clean[0], clean[1]

        # O Google Jobs não expõe um ID estável — a chave de dedup é
        # título+empresa normalizados. Aceita colisão em vaga repostada.
        key = f"{title}|{company}".lower()
        if key in seen:
            continue
        seen.add(key)

        location_and_source = clean[2]
        via = VIA_RE.search(location_and_source)
        source_site = via.group(1).strip() if via else ""
        location = (
            location_and_source.replace(f"via {source_site}", "").replace("•", "").strip()
            if source_site
            else location_and_source
        )

        posted_label = work_model = contract = ""
        for meta in clean[3:]:
            if not posted_label and TIME_RE.search(meta):
                posted_label = meta
            elif not work_model and REMOTE_RE.search(meta):
                work_model = meta
            elif not contract and CONTRACT_RE.search(meta):
                contract = meta

        jobs.append(
            RawJob(
                source="google_jobs",
                source_job_id=key,
                url="",  # preenchido depois pelos links de candidatura, se vierem
                title=title,
                company=company,
                location=location[:120],
                work_model=work_model or None,
                raw={
                    "via": source_site,
                    "posted_label": posted_label,
                    "contract": contract,
                },
            )
        )

        if len(jobs) >= limit:
            break

    return jobs


def _extract_apply_links(html: str) -> list[dict[str, str]]:
    """Links reais de candidatura, que só existem depois de clicar num card.

    Todos carregam utm_campaign=google_jobs_apply. Não são por card — são
    todos da página de uma vez, então casamos por empresa no texto/href.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "google_jobs_apply" in href:
            links.append({"text": a.get_text(strip=True), "href": href})
    return links


class GoogleJobsConnector:
    name = "google_jobs"

    def search(self, profile: SearchProfile, limit: int = 10) -> list[RawJob]:
        # Import tardio: o Botasaurus sobe um Chromium, caro para pagar
        # em `import` quando só o LinkedIn vai rodar.
        from botasaurus.browser import browser

        query = f"{profile.keywords} vagas"
        if profile.location:
            query += f" {profile.location}"
        url = f"https://www.google.com/search?q={quote(query)}&ibp=htl;jobs&hl=pt-BR&gl=br"

        @browser(
            headless=True,
            output=None,
            block_images=True,
            close_on_crash=True,
            tiny_profile=True,
            profile="job-scraper-gjobs",  # obrigatório junto com tiny_profile
        )
        def _scrape(driver, _data):
            driver.delete_cookies_and_local_storage()
            driver.enable_human_mode()

            driver.google_get(url)  # referrer trick — NUNCA driver.get()
            driver.long_random_sleep()

            html = driver.page_html
            if _is_blocked(driver, html):
                # Guarda evidência: sem isso não dá para distinguir bloqueio
                # real de mudança de layout que zerou os cards.
                dump = _dump_debug(driver, html)
                return {"blocked": True, "dump": dump}

            jobs_html = html

            # Uma única chance por IP: colher lista E clicar por links de
            # candidatura no MESMO page load.
            apply_html = ""
            try:
                clicked = driver.run_js(
                    f"const c=document.querySelectorAll('{CARD_SELECTOR}');"
                    "if(c.length){c[0].click();return true}return false"
                )
                if clicked:
                    driver.short_random_sleep()
                    apply_html = driver.page_html
            except Exception as exc:  # noqa: BLE001 — clique é bônus, não requisito
                log.debug("clique no card falhou: %s", exc)

            return {"blocked": False, "jobs_html": jobs_html, "apply_html": apply_html}

        result = _scrape()
        if isinstance(result, list):  # botasaurus às vezes embrulha em lista
            result = result[0]

        if result.get("blocked"):
            raise SourceBlocked(
                f"Google Jobs: captcha/bot detection (esperado — IP flagrado). "
                f"Evidência: {result.get('dump')}"
            )

        jobs = _parse_cards(result["jobs_html"], limit)
        if not jobs:
            # Passou pela detecção de bloqueio mas não achou card nenhum:
            # cheira a mudança no seletor div.mqj2af, não a anti-bot.
            log.warning("nenhum card %s encontrado — seletor pode ter mudado", CARD_SELECTOR)

        # Casa link de candidatura com a vaga pelo nome da empresa.
        if result.get("apply_html"):
            links = _extract_apply_links(result["apply_html"])
            log.info("%d links de candidatura encontrados", len(links))
            for job in jobs:
                company_slug = (job.company or "").lower().replace(" ", "-")
                for link in links:
                    if company_slug and company_slug[:12] in link["href"].lower():
                        job.url = link["href"]
                        break

        # Sem URL a vaga é inútil — cai no link de busca do Google.
        for job in jobs:
            if not job.url:
                job.url = f"https://www.google.com/search?q={quote(job.title + ' ' + (job.company or ''))}&ibp=htl;jobs"

        return jobs


@register("google_jobs")
def _factory() -> GoogleJobsConnector:
    return GoogleJobsConnector()


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o conector Google Jobs isoladamente")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default=None)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    profile = SearchProfile(id=None, keywords=args.keywords, location=args.location)
    try:
        jobs = GoogleJobsConnector().search(profile, limit=args.limit)
    except SourceBlocked as exc:
        print(f"\nBLOQUEADO: {exc}")
        print("Resultado esperado se o IP já foi usado hoje. Não é bug.")
        return

    print(f"\n{len(jobs)} vagas\n")
    for job in jobs:
        print(f"{job.title} — {job.company}")
        print(f"    {job.location} | via {job.raw.get('via')} | {job.raw.get('posted_label')}")
        print(f"    {job.url[:110]}")


if __name__ == "__main__":
    main()
