-- Ordenação do feed por score.
--
-- O score vive em job_matches (PK composta user_id+job_id), então o
-- PostgREST enxerga jobs→job_matches como to-many e não deixa ordenar o
-- nível de cima por coluna do embed. Um `!inner` resolveria a ordenação,
-- mas esconderia toda vaga ainda não pontuada — some do feed a vaga
-- recém-coletada até o timer de match rodar.
--
-- A view traz o score do usuário logado para o nível de cima como coluna
-- comum, que aí é ordenável e filtrável direto no banco. `security_invoker`
-- faz a RLS de jobs e job_matches valer para quem consulta, então a view
-- não abre nada que a tabela já não abrisse.
create or replace view jobs_feed
with (security_invoker = true) as
select
  j.*,
  (
    select m.score
    from job_matches m
    where m.job_id = j.id
      and m.user_id = auth.uid()
  ) as match_score
from jobs j;

-- Sem grant explícito a view nasce inacessível ao client.
grant select on jobs_feed to authenticated;

-- O feed ordena por score desc e desempata por first_seen_at + id. O
-- desempate não é capricho: uma coleta insere o lote inteiro na mesma
-- transação, então dezenas de linhas compartilham first_seen_at, e sem
-- ordem total a paginação por range repete/pula linha entre as páginas.
create index if not exists jobs_feed_tiebreak_idx
  on jobs (first_seen_at desc, id) where canonical_id is null;
