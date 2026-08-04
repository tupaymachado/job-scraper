-- Job Scraper — schema inicial
-- Aplicar pelo SQL Editor do dashboard do Supabase.

-- ---------------------------------------------------------------
-- Vagas: fonte canônica. Sem user_id — a vaga é global e os
-- usuários compartilham o mesmo pool (dedup entre usuários).
-- ---------------------------------------------------------------
create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  source text not null,                 -- 'linkedin' | 'google_jobs'
  source_job_id text not null,
  url text not null,
  title text not null,
  company text,
  location text,
  work_model text,                      -- bruto da fonte; a IA normaliza depois
  posted_at timestamptz,
  description_html text,
  description_text text,
  raw jsonb,                            -- payload original, p/ reparse sem re-scrape
  first_seen_at timestamptz not null default now(),
  unique (source, source_job_id)
);
create index if not exists jobs_first_seen_idx on jobs (first_seen_at desc);
create index if not exists jobs_company_idx on jobs (company);

-- ---------------------------------------------------------------
-- Saída da IA. Tabela separada de jobs para dar pra reprocessar
-- o enriquecimento sem tocar no que veio do scrape.
-- ---------------------------------------------------------------
create table if not exists job_enrichments (
  job_id uuid primary key references jobs on delete cascade,
  seniority text,                       -- junior|pleno|senior|staff|lead|estagio
  stack text[],
  work_model text,                      -- remoto|hibrido|presencial
  contract_type text,                   -- clt|pj|estagio|freelance
  salary_min numeric,
  salary_max numeric,
  salary_currency text,
  tags text[],
  summary text,
  model text,
  enriched_at timestamptz not null default now()
);

create table if not exists user_profiles (
  user_id uuid primary key references auth.users on delete cascade,
  cv_text text,
  preferences text,
  updated_at timestamptz not null default now()
);

create table if not exists search_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  name text not null,
  keywords text not null,
  location text,
  remote_only boolean not null default false,
  sources text[] not null default '{linkedin}',
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists search_profiles_user_idx on search_profiles (user_id);

create table if not exists job_matches (
  user_id uuid not null references auth.users on delete cascade,
  job_id uuid not null references jobs on delete cascade,
  score int not null check (score between 0 and 100),
  reasoning text,
  model text,
  scored_at timestamptz not null default now(),
  primary key (user_id, job_id)
);
create index if not exists job_matches_score_idx on job_matches (user_id, score desc);

create table if not exists job_status (
  user_id uuid not null references auth.users on delete cascade,
  job_id uuid not null references jobs on delete cascade,
  status text not null default 'new' check (status in ('new','saved','applied','discarded')),
  notes text,
  updated_at timestamptz not null default now(),
  primary key (user_id, job_id)
);

-- ---------------------------------------------------------------
-- Fila de scrape sob demanda. A Vercel não alcança a VM, então o
-- app insere aqui e o worker faz poll — inverte o sentido da chamada.
-- ---------------------------------------------------------------
create table if not exists scrape_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users on delete cascade,
  search_profile_id uuid references search_profiles on delete cascade,
  status text not null default 'pending' check (status in ('pending','running','done','error')),
  requested_at timestamptz not null default now(),
  finished_at timestamptz,
  error text
);
create index if not exists scrape_requests_pending_idx on scrape_requests (status, requested_at);

-- status='blocked' é captcha/rate-limit: resultado esperado, não falha.
create table if not exists scrape_runs (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  search_profile_id uuid references search_profiles on delete set null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text check (status in ('ok','blocked','error')),
  jobs_found int not null default 0,
  jobs_new int not null default 0,
  error text
);
create index if not exists scrape_runs_started_idx on scrape_runs (started_at desc);

-- ---------------------------------------------------------------
-- RLS. O worker usa a service_role key e passa por cima de tudo isso.
-- ---------------------------------------------------------------
alter table jobs             enable row level security;
alter table job_enrichments  enable row level security;
alter table user_profiles    enable row level security;
alter table search_profiles  enable row level security;
alter table job_matches      enable row level security;
alter table job_status       enable row level security;
alter table scrape_requests  enable row level security;
alter table scrape_runs      enable row level security;

-- Dados globais: qualquer usuário logado lê, ninguém escreve pelo client.
create policy jobs_read on jobs
  for select to authenticated using (true);
create policy job_enrichments_read on job_enrichments
  for select to authenticated using (true);
create policy scrape_runs_read on scrape_runs
  for select to authenticated using (true);

-- Dados por usuário: dono faz tudo.
create policy user_profiles_own on user_profiles
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy search_profiles_own on search_profiles
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy job_matches_own on job_matches
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy job_status_own on job_status
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy scrape_requests_own on scrape_requests
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
