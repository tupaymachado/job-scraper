# Setup — do zero até coletando sozinho

Ordem importa. O ponto que costuma pegar: **o worker não coleta nada até existir
um perfil de busca**, e perfil de busca pertence a um usuário — então o app web e
o login vêm **antes** da primeira coleta.

Todos os comandos do worker rodam a partir de `worker/`, com
`~/botasaurus-env/bin/python`.

---

## 1. Contas e chaves

- [ ] **Supabase** — criar projeto em https://supabase.com/dashboard
      Anotar de *Project Settings → API*: `Project URL`, `anon key`, `service_role key`
- [ ] **openCode Zen** — pegar a API key em https://opencode.ai/auth
      (o `auth.json` da VM só tem `minimax`; a chave do Zen não está aqui)
- [ ] **Careerjet** *(opcional)* — API v4 em https://www.careerjet.com/partners/api/
      Sem ela o conector se desabilita sozinho; LinkedIn e Gupy seguem funcionando
- [ ] **GitHub** — criar repo vazio e apontar o remote:
      ```bash
      cd ~/projects/job-scraper
      git remote add origin git@github.com:<voce>/job-scraper.git
      git push -u origin main
      ```
- [ ] **Vercel** — conta ligada ao GitHub (o import vem no passo 7)

## 2. Banco

- [ ] No *SQL Editor* do Supabase, rodar **em ordem**:
  - [ ] `supabase/migrations/0001_init.sql` — tabelas, índices, RLS
  - [ ] `supabase/migrations/0002_dedup.sql` — colunas de dedup
- [ ] Conferir em *Table Editor* que apareceram 8 tabelas (`jobs`, `job_enrichments`,
      `job_matches`, `job_status`, `user_profiles`, `search_profiles`,
      `scrape_requests`, `scrape_runs`)
- [ ] Em *Authentication → Providers*, confirmar que **Email** está habilitado
      (o login é magic link)

## 3. Worker: credenciais e teste a seco

- [ ] ```bash
      cd ~/projects/job-scraper/worker
      cp .env.example .env && chmod 600 .env
      ```
- [ ] Preencher `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENCODE_API_KEY`
      (e `CAREERJET_AFFID` se tiver)
- [ ] Testar os conectores **sem tocar no banco** — se isto funciona, a coleta funciona:
      ```bash
      ~/botasaurus-env/bin/python -m connectors.linkedin \
          --keywords "desenvolvedor react" --location Brazil --limit 10 --detail --dry-run
      ~/botasaurus-env/bin/python -m connectors.gupy --keywords "desenvolvedor react" --limit 10
      ~/botasaurus-env/bin/python -m connectors.careerjet --keywords "desenvolvedor react"
      ```
      **Esperado:** LinkedIn e Gupy listam vagas com título/empresa/local.
      Careerjet sem chave imprime "CAREERJET_AFFID não configurada" — isso é ok.

## 4. Web local e primeiro login

- [ ] ```bash
      cd ~/projects/job-scraper/web
      cp .env.example .env.local
      ```
      Preencher `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` (a **anon**, não a service_role)
- [ ] `bun install && bun run dev`
- [ ] Abrir http://localhost:3000, entrar com seu e-mail, clicar no magic link
- [ ] Em **Perfil**, colar seu CV e as preferências → *Salvar*
      (é o que a IA usa para calcular o score; sem isso o match não roda)
- [ ] **Anotar o seu user id** — aparece no rodapé da página Perfil, no comando sugerido
- [ ] Em **Buscas**, criar um perfil de busca (ex: `desenvolvedor react`, `Brazil`,
      fontes LinkedIn + Gupy) → *Criar busca*

## 5. Primeira coleta de verdade

- [ ] ```bash
      cd ~/projects/job-scraper/worker
      ~/botasaurus-env/bin/python run.py --source all --once
      ```
      **Esperado:** log com `X vagas encontradas` e `Y novas gravadas` por fonte
- [ ] Rodar **de novo** o mesmo comando
      **Esperado:** `jobs_new` cai para perto de 0 — é o dedup funcionando
- [ ] Recarregar o feed em http://localhost:3000 — as vagas devem estar lá

> Se aparecer `nenhum perfil de busca habilitado usa a fonte 'x'`, você pulou o
> passo 4: o worker lê `search_profiles` e não tem o que coletar.

## 6. IA

- [ ] ```bash
      ~/botasaurus-env/bin/python -m ai.enrich --limit 10
      ```
      **Esperado:** uma linha `✓` por vaga. Conferir em `job_enrichments` que
      `stack` e `seniority` vieram preenchidos
- [ ] ```bash
      ~/botasaurus-env/bin/python -m ai.match --user-id <seu-user-id>
      ```
      **Esperado:** linhas com score de 0 a 100. No feed, as vagas passam a
      mostrar o badge de score
- [ ] Se der erro de chave, revisar `OPENCODE_API_KEY` no `.env`

## 7. Automatizar (systemd)

`loginctl enable-linger ubuntu` **já está ativo** nesta VM — pode pular.

- [ ] ```bash
      mkdir -p ~/.config/systemd/user
      cp ~/projects/job-scraper/worker/systemd/* ~/.config/systemd/user/
      systemctl --user daemon-reload
      systemctl --user enable --now \
          job-scraper-collect.timer \
          job-scraper-queue.timer \
          job-scraper-enrich.timer \
          job-scraper-google.timer
      ```
- [ ] `systemctl --user list-timers` — os 4 devem aparecer com próximo disparo
- [ ] Testar um serviço na mão e ver o log:
      ```bash
      systemctl --user start job-scraper-collect.service
      journalctl --user -u job-scraper-collect -n 50 --no-pager
      ```

| Timer | Frequência | O quê |
|---|---|---|
| `collect` | 6/6h | LinkedIn + Gupy + Careerjet |
| `queue` | 60s | atende o botão "Buscar agora" do app |
| `enrich` | 2/2h | extrai campos estruturados com IA |
| `google` | 1x/dia | Google Jobs, best-effort |

> `job-scraper-google` vindo `blocked` é o **comportamento esperado**, não falha.
> O `ai.match` não tem timer: ele depende do seu user id, então roda na mão
> (ou você adiciona um timer com o id fixo depois).

## 8. Deploy na Vercel

- [ ] Antes de tudo, garantir que o build passa local: `cd web && bun run build`
- [ ] Importar o repo na Vercel (*Add New → Project*), **Root Directory = `web`**
- [ ] Em *Settings → Environment Variables*, adicionar **só** estas duas:
      - `VITE_SUPABASE_URL`
      - `VITE_SUPABASE_ANON_KEY`
- [ ] Deploy e abrir a URL
- [ ] No Supabase, em *Authentication → URL Configuration*, adicionar a URL da
      Vercel em **Site URL** e em **Redirect URLs** — sem isso o magic link volta
      para `localhost` e o login em produção não fecha
- [ ] Testar o login na URL de produção
- [ ] Testar o botão **"Buscar agora"** em Buscas → o worker da VM deve consumir
      o pedido em até 60s e o status virar `done`

> ⚠️ **Nunca** colocar `SUPABASE_SERVICE_ROLE_KEY` ou `OPENCODE_API_KEY` na Vercel.
> Elas vivem só em `worker/.env`, na VM. O front usa apenas a anon key, sob RLS.

---

## Checagem final

- [ ] Feed mostra vagas com badge de fonte e score
- [ ] Filtros (fonte, senioridade, modelo, score) funcionam
- [ ] Salvar / Candidatei / Descartar persistem ao recarregar
- [ ] `systemctl --user list-timers` mostra os 4 timers ativos
- [ ] `select status, count(*) from scrape_runs group by status;` — a maioria `ok`,
      `blocked` só em `google_jobs`

## Quando algo falhar

| Sintoma | Onde olhar |
|---|---|
| Feed vazio | Existe perfil de busca? `select * from search_profiles;` |
| "Supabase não configurado" | `web/.env.local` faltando ou sem reiniciar o `bun run dev` |
| Coleta não roda sozinha | `journalctl --user -u job-scraper-collect -n 50` |
| Sem score nas vagas | `user_profiles.cv_text` preenchido? Rodou `ai.match`? |
| Google sempre `blocked` | Esperado. Ver a seção do README sobre proxy residencial |
| "Buscar agora" não sai de `pending` | O timer `job-scraper-queue` está ativo? |
