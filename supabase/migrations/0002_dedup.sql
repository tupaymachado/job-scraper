-- Dedup entre fontes.
--
-- Com LinkedIn + Gupy + Careerjet a mesma vaga aparece várias vezes (a
-- Careerjet reagrega os outros dois). Agrupamos por título+empresa
-- normalizados: uma linha vira a canônica e as demais apontam para ela.
--
-- Por que não uma VIEW agregando na leitura: o feed é paginado por range
-- do PostgREST, e agrupar na leitura quebraria a paginação. Marcar a
-- duplicata na ingestão mantém "uma linha = uma vaga" no feed.

alter table jobs add column if not exists dedup_key text;

-- NULL = esta linha é a canônica. Preenchido = duplicata, aponta para a canônica.
alter table jobs add column if not exists canonical_id uuid references jobs(id) on delete set null;

-- Denormalizado na canônica: todas as fontes onde a vaga apareceu, e os
-- links alternativos. Evita um embed auto-referencial no PostgREST só
-- para montar os badges do card.
alter table jobs add column if not exists sources text[] not null default '{}';
alter table jobs add column if not exists alt_urls jsonb not null default '[]';

-- Backfill: toda linha existente é canônica de si mesma. Sem isso o filtro
-- por fonte do feed (contains em `sources`) não acharia nada antigo.
update jobs set sources = array[source] where sources = '{}';

create index if not exists jobs_dedup_key_idx on jobs (dedup_key);
-- O filtro por fonte do feed usa `sources @> '{x}'`; GIN é o índice desse operador.
create index if not exists jobs_sources_idx on jobs using gin (sources);
create index if not exists jobs_canonical_idx on jobs (canonical_id);

-- O feed só lê canônicas: este índice é o que ele usa de fato.
create index if not exists jobs_feed_idx
  on jobs (first_seen_at desc) where canonical_id is null;
