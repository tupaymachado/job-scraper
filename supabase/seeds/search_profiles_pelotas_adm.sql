-- Perfis de busca: vagas administrativas/financeiras/contábeis em Pelotas-RS.
--
-- Não é migration: são dados de UM usuário. O user id NÃO vai no arquivo
-- (o repo é público) — troque <MATCH_USER_ID> pelo valor de MATCH_USER_ID do
-- worker/.env antes de rodar no SQL Editor. Idempotente: pula perfis que o
-- usuário já tem com o mesmo nome.
--
-- Fontes: gupy, linkedin, careerjet, amplagestao. Programathor fica de fora (só TI).
-- remote_only = false: o conector da Gupy traz as de Pelotas + as remotas.

insert into search_profiles (user_id, name, keywords, location, remote_only, sources, enabled)
select '<MATCH_USER_ID>'::uuid, v.name, v.keywords, 'Pelotas, RS', false,
       '{gupy,linkedin,amplagestao,careerjet}'::text[], true
from (values
  ('Administrativo Pelotas', 'administrativo'),
  ('Financeiro Pelotas',     'financeiro'),
  ('Contábil Pelotas',       'contabil')
) as v(name, keywords)
where not exists (
  select 1 from search_profiles s
  where s.user_id = '<MATCH_USER_ID>'::uuid and s.name = v.name
);

-- Perfis criados antes do conector da Ampla Gestão: acrescenta a fonte.
update search_profiles
set sources = array_append(sources, 'amplagestao')
where user_id = '<MATCH_USER_ID>'::uuid
  and name in ('Administrativo Pelotas', 'Financeiro Pelotas', 'Contábil Pelotas')
  and not ('amplagestao' = any(sources));
