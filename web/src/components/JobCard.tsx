import { Link } from '@tanstack/react-router'
import { one } from '../lib/types'
import type { JobWithMeta } from '../lib/types'

const SOURCE_LABEL: Record<string, string> = {
  linkedin: 'LinkedIn',
  google_jobs: 'Google Jobs',
}

function scoreColor(score: number) {
  if (score >= 86) return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
  if (score >= 61) return 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
  if (score >= 31) return 'bg-amber-500/15 text-amber-700 dark:text-amber-300'
  return 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400'
}

function relativeDate(iso: string | null) {
  if (!iso) return null
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return 'hoje'
  if (days === 1) return 'ontem'
  if (days < 30) return `${days}d`
  return `${Math.floor(days / 30)}m`
}

export function JobCard({ job, active }: { job: JobWithMeta; active?: boolean }) {
  const enrichment = one(job.job_enrichments)
  const match = job.job_matches?.[0]
  const status = job.job_status?.[0]?.status ?? 'new'
  const posted = relativeDate(job.posted_at ?? job.first_seen_at)

  return (
    <Link
      to="/job/$jobId"
      params={{ jobId: job.id }}
      className={`block rounded-xl border p-4 transition-colors ${
        active
          ? 'border-sky-500 bg-sky-50 dark:bg-sky-950/30'
          : 'border-zinc-200 bg-white hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700'
      } ${status === 'discarded' ? 'opacity-50' : ''}`}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 flex-1 font-semibold leading-snug text-zinc-900 dark:text-zinc-100">
          {job.title}
        </h3>
        {match ? (
          <span
            className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums ${scoreColor(match.score)}`}
            title={match.reasoning ?? undefined}
          >
            {match.score}
          </span>
        ) : null}
      </div>

      <p className="mt-1 truncate text-sm text-zinc-600 dark:text-zinc-400">
        {job.company ?? 'Empresa não informada'}
        {job.location ? ` · ${job.location}` : ''}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
          {SOURCE_LABEL[job.source] ?? job.source}
        </span>
        {posted ? (
          <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
            {posted}
          </span>
        ) : null}
        {enrichment?.seniority ? (
          <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-violet-700 dark:text-violet-300">
            {enrichment.seniority}
          </span>
        ) : null}
        {enrichment?.work_model ? (
          <span className="rounded bg-teal-500/10 px-1.5 py-0.5 text-teal-700 dark:text-teal-300">
            {enrichment.work_model}
          </span>
        ) : null}
        {status === 'saved' ? (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700 dark:text-amber-300">
            salva
          </span>
        ) : null}
        {status === 'applied' ? (
          <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-700 dark:text-emerald-300">
            candidatei
          </span>
        ) : null}
      </div>

      {enrichment?.stack?.length ? (
        <p className="mt-2 truncate text-xs text-zinc-500 dark:text-zinc-500">
          {enrichment.stack.slice(0, 6).join(' · ')}
        </p>
      ) : null}
    </Link>
  )
}
