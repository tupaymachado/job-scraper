import { useMemo, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { FilterPanel, FilterSheet } from '../components/FilterSheet'
import { JobCard } from '../components/JobCard'
import { RequireAuth } from '../components/RequireAuth'
import { emptyFilters, useJobsFeed } from '../lib/queries'
import type { FeedFilters } from '../lib/queries'

export const Route = createFileRoute('/')({
  component: () => (
    <RequireAuth>
      <Feed />
    </RequireAuth>
  ),
})

function activeFilterCount(f: FeedFilters) {
  return (
    (f.source ? 1 : 0) +
    (f.seniority ? 1 : 0) +
    (f.workModel ? 1 : 0) +
    (f.minScore > 0 ? 1 : 0) +
    (f.status !== 'all' ? 1 : 0)
  )
}

function Feed() {
  const [filters, setFilters] = useState<FeedFilters>(emptyFilters)
  const [sheetOpen, setSheetOpen] = useState(false)

  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useJobsFeed(filters)

  const jobs = useMemo(() => data?.pages.flatMap((p) => p.jobs) ?? [], [data])
  const badge = activeFilterCount(filters)

  return (
    <div className="mx-auto max-w-6xl md:flex md:gap-6 md:p-6">
      {/* Filtros como coluna fixa só no desktop */}
      <aside className="hidden w-64 shrink-0 md:block">
        <div className="sticky top-6 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <FilterPanel filters={filters} onChange={setFilters} />
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 border-b border-zinc-200 bg-zinc-50/95 p-4 backdrop-blur md:static md:border-0 md:bg-transparent md:p-0 md:pb-4 dark:border-zinc-800 dark:bg-zinc-950/95">
          <div className="flex items-center gap-2">
            <input
              type="search"
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
              placeholder="Buscar título ou empresa…"
              className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-base outline-none focus:border-sky-500 dark:border-zinc-700 dark:bg-zinc-900"
            />
            <button
              type="button"
              onClick={() => setSheetOpen(true)}
              className="relative shrink-0 rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium md:hidden dark:border-zinc-700"
            >
              Filtros
              {badge > 0 ? (
                <span className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-sky-500 text-xs font-semibold text-white">
                  {badge}
                </span>
              ) : null}
            </button>
          </div>
        </header>

        <div className="space-y-3 p-4 md:p-0">
          {isLoading ? <p className="text-sm text-zinc-500">Carregando vagas…</p> : null}

          {error ? (
            <div className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
              {error instanceof Error ? error.message : 'Erro ao carregar vagas'}
            </div>
          ) : null}

          {!isLoading && !error && jobs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-300 p-8 text-center dark:border-zinc-700">
              <p className="font-medium">Nenhuma vaga por aqui</p>
              <p className="mt-1 text-sm text-zinc-500">
                {badge > 0
                  ? 'Tente afrouxar os filtros.'
                  : 'Crie um perfil de busca em Buscas e rode a coleta.'}
              </p>
            </div>
          ) : null}

          {jobs.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}

          {hasNextPage ? (
            <button
              type="button"
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="w-full rounded-lg border border-zinc-300 py-2.5 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              {isFetchingNextPage ? 'Carregando…' : 'Carregar mais'}
            </button>
          ) : null}
        </div>
      </div>

      {sheetOpen ? (
        <FilterSheet filters={filters} onChange={setFilters} onClose={() => setSheetOpen(false)} />
      ) : null}
    </div>
  )
}
