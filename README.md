# Job Scraper

Webapp mobile-first que coleta vagas do LinkedIn, Gupy, Careerjet e Google Jobs, enriquece com IA
(campos estruturados + score de aderência ao seu perfil) e mostra tudo num feed.

```
VM Oracle (worker Python)                    Vercel (TanStack Start)
┌────────────────────────────┐               ┌──────────────────────┐
│ systemd timers             │               │ rotas + server fns   │
│  ├ linkedin.py  (HTTP)     │               │ @supabase/ssr (anon) │
│  ├ gupy.py      (HTTP)     │               └──────────┬───────────┘
│  ├ careerjet.py (HTTP)     │                          │
│  ├ google_jobs.py (Bota)   │                          │
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

## As fontes não são equivalentes

Medido nesta VM em ago/2026, para o termo "desenvolvedor":

| Fonte | Método | Volume | Observação |
|---|---|---|---|
| **LinkedIn** | API `jobs-guest`, HTTP puro | ~50/rodada, 6/6h | Descrição completa; URL direta |
| **Gupy** | API JSON pública, sem auth | **554** por termo, 100/página | Melhor estruturada: modalidade, skills, URL direta |
| **Careerjet** | API v4, Basic auth | 1917 hits, 99/página | Agregadora, ~39% com salário. **Exige API key grátis** |
| **Google Jobs** | Botasaurus | ~10/dia, quase sempre bloqueado | Best-effort |

**Google Jobs não é uma fonte, é um agregador** — a "lista completa" dele é a
união de LinkedIn, Indeed, Catho, Gupy e afins. Brigar com o Google por essa
união custa dinheiro e fragilidade; ir direto nas fontes é grátis e robusto. Ele
segue no projeto como best-effort: o Google flagra o IP depois de **um** acesso
automatizado, e `headless=False`, Xvfb e Tor não desfazem isso. `status='blocked'`
é resultado **normal**, não erro.

A correção de raiz para o Google seria proxy residencial (o Botasaurus já aceita
`@browser(proxy=...)`, é um parâmetro). SerpAPI não compensa: US$ 25/mês por 1.000
buscas e o Google removeu `salaries` e `apply_options` do endpoint — receberíamos
menos dado do que o nosso próprio scraper.

### Careerjet exige chave (e por que não usamos a API legada)

A API legada responde 200 só para `Referer` de domínios legados e 401 para os
demais ("only accessible for authenticated legacy users"). Fazê-la funcionar
exigiria forjar o Referer de um terceiro allowlistado — contornar controle de
acesso se passando por outro, além de revogável a qualquer momento. Usamos a v4
com chave própria: registro grátis em https://www.careerjet.com/partners/api/,
valor em `CAREERJET_AFFID`. Sem a chave, o conector se desabilita sozinho.

## Dedup entre fontes

A mesma vaga aparece em várias fontes (a Careerjet reagrega as outras), e o
LinkedIn ainda republica a mesma vaga por cidade com id diferente. A primeira
vista de uma `dedup_key` (título+empresa normalizados, `worker/dedup.py`) vira a
**canônica**; as demais recebem `canonical_id`, somem do feed e somam sua
fonte/link na canônica — que exibe uma badge por fonte e os links alternativos.

A ordem de coleta (`SOURCE_ORDER` em `run.py`) é a ordem de preferência: LinkedIn
e Gupy primeiro porque têm URL direta, Careerjet por último porque o link dela é
um redirect de tracking opaco que não deve virar o link principal.

A normalização é deliberadamente conservadora: senioridade e stack ficam na chave,
então "Dev Java Pleno" nunca funde com "Dev Java Sênior". Deixar passar uma
duplicata (vaga aparece duas vezes) é melhor que fundir vagas distintas (vaga
some).

## Setup

### 1. Supabase

Aplique as migrations do [supabase/migrations/](supabase/migrations/) **em ordem** no
SQL Editor do dashboard: `0001_init.sql` (tabelas, índices, RLS) e depois
`0002_dedup.sql` (colunas de dedup).

### 2. Worker (na VM)

```bash
cd worker
cp .env.example .env && chmod 600 .env   # SUPABASE_*, OPENCODE_API_KEY, CAREERJET_AFFID

# Conectores rodam isolados, sem tocar no Supabase — dá para conferir a
# coleta antes de configurar qualquer credencial:
~/botasaurus-env/bin/python -m connectors.linkedin \
    --keywords "desenvolvedor react" --location Brazil --limit 10 --detail --dry-run
~/botasaurus-env/bin/python -m connectors.gupy --keywords "desenvolvedor react" --limit 10
~/botasaurus-env/bin/python -m connectors.careerjet --keywords "desenvolvedor react"
```

Timers:

```bash
loginctl enable-linger ubuntu                    # sobrevive a logout
mkdir -p ~/.config/systemd/user
cp worker/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now job-scraper-collect.timer \
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
python run.py --source all --once          # LinkedIn + Gupy + Careerjet, na ordem do dedup
python run.py --source gupy --once         # uma fonte só
python run.py --source google_jobs --once  # best-effort, fora do 'all' de propósito
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

**`--source all` não inclui o Google Jobs.** Ele tem timer próprio, 1x/dia. Rodá-lo
junto da coleta de 6/6h só queimaria o IP e encheria `scrape_runs` de `blocked`.

**Detalhe só do que é novo.** O request de descrição do LinkedIn é o mais caro do
orçamento de rate limit, então `run.py` consulta os IDs já conhecidos antes.

**PostgREST direto, sem SDK.** O worker fala com o Supabase via `requests` em
[worker/store.py](worker/store.py). O `~/botasaurus-env` é compartilhado com outras
ferramentas e o supabase-py arrastaria httpx/pydantic/gotrue para dentro dele.

**Bun local, Node no deploy.** O runtime Bun da Vercel está em beta e ainda não
cobre TanStack Start. Quando cobrir, é uma linha (`"bunVersion": "1.x"`) no
`vercel.json`.
