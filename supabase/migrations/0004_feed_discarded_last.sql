-- Descartadas no fim do feed.
--
-- Mesma ideia do match_score: o status vive num embed por usuário, então
-- para ordenar por ele ele precisa ser coluna do nível de cima. Vira
-- boolean e não texto porque a ordenação é binária — ativa antes de
-- descartada — e as demais distinções (new/saved/applied) não mexem na
-- ordem, só no filtro.
--
-- coalesce é obrigatório: vaga sem linha em job_status devolveria NULL, e
-- NULL não é "não descartada" para o ORDER BY.
--
-- `create or replace` só aceita colunas novas no fim da lista, que é o caso.
create or replace view jobs_feed
with (security_invoker = true) as
select
  j.*,
  (
    select m.score
    from job_matches m
    where m.job_id = j.id
      and m.user_id = auth.uid()
  ) as match_score,
  coalesce(
    (
      select s.status = 'discarded'
      from job_status s
      where s.job_id = j.id
        and s.user_id = auth.uid()
    ),
    false
  ) as is_discarded
from jobs j;
