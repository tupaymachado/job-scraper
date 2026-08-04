# Job Scraper

Webapp mobile-first que coleta vagas do LinkedIn e do Google Jobs, enriquece com IA
(campos estruturados + score de aderência ao seu perfil) e mostra tudo num feed.

```
VM Oracle (worker Python)                    Vercel (TanStack Start)
┌────────────────────────────┐               ┌──────────────────────┐
│ systemd timers             │               │ rotas + server fns   │
│  ├ linkedin.py  (HTTP)     │               │ @supabase/ssr (anon) │
│  ├ google_jobs.py (Bota)   │               └──────────┬───────────┘
│  ├ ai/enrich.py (Zen)      │                          │ RLS
│  └ ai/match.py  (Zen)      │                          │
└──────────┬─────────────────┘                          │
           │ service_role                               │
           └──────────────► Supabase (Postgres + Auth) ◄┘
                                   ▲
              worker faz poll em scrape_requests a cada 60s
              (a Vercel não alcança a VM — a fila inverte o fluxo)
```

| Diretório | O quê |
|---|---|
| [web/](web/) | TanStack Start + Tailwind + TanStack Query → Vercel |
| [worker/](worker/) | Python, roda em `~/botasaurus-env` na VM |
| [supabase/](supabase/) | Migrations SQL |

## As duas fontes não são equivalentes

**LinkedIn** é o carro-chefe: a API `jobs-guest` responde a `requests` comum, sem
browser e sem anti-bot. ~50 vagas por rodada, a cada 6h, com descrição completa.

**Google Jobs** é best-effort: o Google flagra o IP depois de **um** acesso
automatizado, e `headless=False`, Xvfb e Tor não desfazem isso. Roda 1x/dia e
`status='blocked'` é resultado **normal**, não erro. Se virar regra, o gancho de
escalada é trocar por SerpAPI atrás da mesma interface de conector.

## Setup

### 1. Supabase

Aplique [supabase/migrations/0001_init.sql](supabase/migrations/0001_init.sql) no
SQL Editor do dashboard. Ele cria as tabelas, os índices e as políticas de RLS.

### 2. Worker (na VM)

```bash
cd worker
cp .env.example .env && chmod 600 .env   # preencha SUPABASE_* e OPENCODE_API_KEY
~/botasaurus-env/bin/python -m connectors.linkedin \
    --keywords "desenvolvedor react" --location Brazil --limit 10 --detail --dry-run
```

Esse `--dry-run` não toca no Supabase — serve para confirmar que a coleta funciona
antes de configurar qualquer credencial.

Timers:

```bash
loginctl enable-linger ubuntu                    # sobrevive a logout
mkdir -p ~/.config/systemd/user
cp worker/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now job-scraper-linkedin.timer \
    job-scraper-google.timer job-scraper-queue.timer job-scraper-enrich.timer
systemctl --user list-timers
```

### 3. Web

```bash
cd web
cp .env.example .env.local   # VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
bun install
bun run dev
```

Deploy: push para o Git e importar na Vercel. Ela detecta TanStack Start e o
`bun.lock` sozinha. Configure só `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY`.

> **A `SERVICE_ROLE_KEY` e a `OPENCODE_API_KEY` não vão para a Vercel.** Elas
> vivem só em `worker/.env`, na VM. O front usa apenas a anon key, sob RLS.

## Comandos do worker

```bash
python run.py --source linkedin --once     # coleta LinkedIn
python run.py --source google_jobs --once  # coleta Google Jobs (best-effort)
python run.py --queue                      # drena os pedidos do botão "Buscar agora"
python -m ai.enrich --limit 20             # extrai campos estruturados
python -m ai.match --user-id <uuid>        # calcula score de aderência
```

Todos com `~/botasaurus-env/bin/python`, a partir de `worker/`.

## Notas de implementação

**Sanitização.** O front renderiza `description_html` com `dangerouslySetInnerHTML`.
O HTML vem de terceiros, então [worker/sanitize.py](worker/sanitize.py) limpa na
**escrita** — o que está no banco já é seguro por construção, em vez de depender
de cada consumidor lembrar de sanitizar.

**Custo da IA.** [ai/match.py](worker/ai/match.py) roda um prefiltro de overlap de
stack antes de chamar o modelo. Sem ele, pagaríamos reasoning caro para descobrir
que uma vaga de COBOL não combina com um perfil de front-end.

**Detalhe só do que é novo.** O request de descrição do LinkedIn é o mais caro do
orçamento de rate limit, então `run.py` consulta os IDs já conhecidos antes.

**PostgREST direto, sem SDK.** O worker fala com o Supabase via `requests` em
[worker/store.py](worker/store.py). O `~/botasaurus-env` é compartilhado com outras
ferramentas e o supabase-py arrastaria httpx/pydantic/gotrue para dentro dele.

**Bun local, Node no deploy.** O runtime Bun da Vercel está em beta e ainda não
cobre TanStack Start. Quando cobrir, é uma linha (`"bunVersion": "1.x"`) no
`vercel.json`.
