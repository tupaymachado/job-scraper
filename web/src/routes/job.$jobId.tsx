import { Link, createFileRoute } from '@tanstack/react-router'
import { RequireAuth } from '../components/RequireAuth'
import { useAuth } from '../lib/auth'
import { useJob, useSetJobStatus } from '../lib/queries'
import { one } from '../lib/types'
import type { JobStatusValue } from '../lib/types'

export const Route = createFileRoute('/job/$jobId')({
  component: () => (
    <RequireAuth>
      <JobDetail />
    </RequireAuth>
  ),
})

const ACTIONS: { value: JobStatusValue; label: string; className: string }[] = [
  { value: 'saved', label: 'Salvar', className: 'bg-amber-500 hover:bg-amber-600' },
  { value: 'applied', label: 'Candidatei', className: 'bg-emerald-600 hover:bg-emerald-700' },
  { value: 'discarded', label: 'Descartar', className: 'bg-zinc-500 hover:bg-zinc-600' },
]

function formatSalary(min: number | null, max: number | null, currency: string | null) {
  if (!min && !max) return null
  const fmt = (v: number) =>
    new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: currency || 'BRL',
      maximumFractionDigits: 0,
    }).format(v)
  if (min && max) return `${fmt(min)} – ${fmt(max)}`
  return fmt((min ?? max)!)
}

function JobDetail() {
  const { jobId } = Route.useParams()
  const { user } = useAuth()
  const { data: job, isLoading, error } = useJob(jobId)
  const setStatus = useSetJobStatus()

  if (isLoading) return <p className="p-6 text-sm text-zinc-500">Carregando…</p>
  if (error || !job) {
    return (
      <div className="p-6">
        <p className="text-sm text-red-600">
          {error instanceof Error ? error.message : 'Vaga não encontrada'}
        </p>
        <Link to="/" className="mt-2 inline-block text-sm text-sky-600">
          ← Voltar
        </Link>
      </div>
    )
  }

  const enrichment = one(job.job_enrichments)
  const match = job.job_matches?.[0]
  const current = job.job_status?.[0]?.status ?? 'new'
  const salary = enrichment
    ? formatSalary(enrichment.salary_min, enrichment.salary_max, enrichment.salary_currency)
    : null

  return (
    <div className="mx-auto max-w-3xl p-4 md:p-6">
      <Link to="/" className="text-sm text-sky-600 dark:text-sky-400">
        ← Vagas
      </Link>

      <header className="mt-3">
        <h1 className="text-xl font-bold leading-tight md:text-2xl">{job.title}</h1>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">
          {job.company ?? 'Empresa não informada'}
          {job.location ? ` · ${job.location}` : ''}
        </p>
      </header>

      {match ? (
        <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold tabular-nums">{match.score}</span>
            <span className="text-sm text-zinc-500">de aderência ao seu perfil</span>
          </div>
          {match.reasoning ? (
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">{match.reasoning}</p>
          ) : null}
        </div>
      ) : null}

      {enrichment ? (
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          {[
            ['Senioridade', enrichment.seniority],
            ['Modelo', enrichment.work_model],
            ['Contrato', enrichment.contract_type],
            ['Salário', salary],
          ]
            .filter(([, v]) => v)
            .map(([label, value]) => (
              <div
                key={label as string}
                className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
              >
                <dt className="text-xs text-zinc-500">{label}</dt>
                <dd className="mt-0.5 font-medium capitalize">{value}</dd>
              </div>
            ))}
        </dl>
      ) : null}

      {enrichment?.stack?.length ? (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {enrichment.stack.map((tech) => (
            <span
              key={tech}
              className="rounded-md bg-sky-500/10 px-2 py-0.5 text-sm text-sky-700 dark:text-sky-300"
            >
              {tech}
            </span>
          ))}
        </div>
      ) : null}

      {/* Ações fixas no rodapé no mobile, inline no desktop */}
      <div className="fixed inset-x-0 bottom-16 z-30 flex gap-2 border-t border-zinc-200 bg-white p-3 md:static md:mt-6 md:border-0 md:bg-transparent md:p-0 dark:border-zinc-800 dark:bg-zinc-900 md:dark:bg-transparent">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 rounded-lg bg-sky-600 px-4 py-2.5 text-center font-medium text-white hover:bg-sky-700"
        >
          Candidatar-se
        </a>
        {ACTIONS.map((action) => (
          <button
            key={action.value}
            type="button"
            disabled={!user || setStatus.isPending}
            onClick={() =>
              setStatus.mutate({
                jobId: job.id,
                userId: user!.id,
                // Clicar de novo no status atual desfaz a marcação.
                status: current === action.value ? 'new' : action.value,
              })
            }
            className={`rounded-lg px-3 py-2.5 text-sm font-medium text-white disabled:opacity-50 ${
              current === action.value ? 'ring-2 ring-offset-1' : ''
            } ${action.className}`}
          >
            {action.label}
          </button>
        ))}
      </div>

      <section className="mt-6 mb-32 md:mb-6">
        <h2 className="mb-2 font-semibold">Descrição</h2>
        {job.description_html ? (
          // Conteúdo do LinkedIn: HTML simples de descrição, sem scripts.
          <div
            className="prose-sm max-w-none space-y-2 text-sm leading-relaxed text-zinc-700 [&_li]:ml-4 [&_li]:list-disc [&_strong]:font-semibold dark:text-zinc-300"
            dangerouslySetInnerHTML={{ __html: job.description_html }}
          />
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {job.description_text ?? 'Sem descrição coletada.'}
          </p>
        )}
      </section>
    </div>
  )
}
