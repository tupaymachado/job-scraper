import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { RequireAuth } from '../components/RequireAuth'
import { useAuth } from '../lib/auth'
import {
  useDeleteSearchProfile,
  useRequestScrape,
  useSaveSearchProfile,
  useScrapeRequests,
  useScrapeRuns,
  useSearchProfiles,
} from '../lib/queries'
import type { JobSource, SearchProfile } from '../lib/types'

export const Route = createFileRoute('/searches')({
  component: () => (
    <RequireAuth>
      <Searches />
    </RequireAuth>
  ),
})

const ALL_SOURCES: { value: JobSource; label: string; hint: string }[] = [
  { value: 'linkedin', label: 'LinkedIn', hint: '~50 vagas por rodada, descrição completa' },
  { value: 'gupy', label: 'Gupy', hint: 'ATS dominante no Brasil, ~500 vagas por termo' },
  { value: 'careerjet', label: 'Careerjet', hint: 'Agregadora, com salário. Exige API key grátis' },
  { value: 'google_jobs', label: 'Google Jobs', hint: '~10 vagas/dia, quase sempre bloqueado' },
]

const emptyForm = {
  name: '',
  keywords: '',
  location: 'Brazil',
  remote_only: false,
  sources: ['linkedin', 'gupy'] as JobSource[],
}

function Searches() {
  const { user } = useAuth()
  const { data: profiles, isLoading } = useSearchProfiles()
  const { data: requests } = useScrapeRequests()
  const { data: runs } = useScrapeRuns()
  const save = useSaveSearchProfile()
  const remove = useDeleteSearchProfile()
  const requestScrape = useRequestScrape()

  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState<string | null>(null)

  const inFlight = requests?.some(
    (r: { status: string }) => r.status === 'pending' || r.status === 'running',
  )

  function startEdit(profile: SearchProfile) {
    setEditingId(profile.id)
    setForm({
      name: profile.name,
      keywords: profile.keywords,
      location: profile.location ?? '',
      remote_only: profile.remote_only,
      sources: profile.sources,
    })
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!user) return
    await save.mutateAsync({
      ...(editingId ? { id: editingId } : {}),
      user_id: user.id,
      name: form.name || form.keywords,
      keywords: form.keywords,
      location: form.location || null,
      remote_only: form.remote_only,
      sources: form.sources,
      enabled: true,
    })
    setForm(emptyForm)
    setEditingId(null)
  }

  function toggleSource(source: JobSource) {
    setForm((f) => ({
      ...f,
      sources: f.sources.includes(source)
        ? f.sources.filter((s) => s !== source)
        : [...f.sources, source],
    }))
  }

  return (
    <div className="mx-auto max-w-3xl p-4 md:p-6">
      <h1 className="text-xl font-bold md:text-2xl">Buscas</h1>
      <p className="mt-1 text-sm text-zinc-500">
        O worker roda automaticamente. "Buscar agora" entra numa fila que ele consome em até 1
        minuto.
      </p>

      <form
        onSubmit={submit}
        className="mt-5 space-y-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
      >
        <h2 className="font-semibold">{editingId ? 'Editar busca' : 'Nova busca'}</h2>

        <input
          required
          value={form.keywords}
          onChange={(e) => setForm({ ...form, keywords: e.target.value })}
          placeholder="Palavras-chave (ex: desenvolvedor react)"
          className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-base outline-none focus:border-sky-500 dark:border-zinc-700 dark:bg-zinc-800"
        />
        <div className="flex gap-2">
          <input
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            placeholder="Local (ex: Brazil)"
            className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-base outline-none focus:border-sky-500 dark:border-zinc-700 dark:bg-zinc-800"
          />
          <label className="flex shrink-0 items-center gap-2 rounded-lg border border-zinc-300 px-3 text-sm dark:border-zinc-700">
            <input
              type="checkbox"
              checked={form.remote_only}
              onChange={(e) => setForm({ ...form, remote_only: e.target.checked })}
              className="accent-sky-500"
            />
            Só remoto
          </label>
        </div>

        <div className="space-y-1.5">
          {ALL_SOURCES.map((s) => (
            <label key={s.value} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.sources.includes(s.value)}
                onChange={() => toggleSource(s.value)}
                className="mt-1 accent-sky-500"
              />
              <span>
                {s.label}
                <span className="block text-xs text-zinc-500">{s.hint}</span>
              </span>
            </label>
          ))}
        </div>

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={save.isPending || form.sources.length === 0}
            className="rounded-lg bg-sky-600 px-4 py-2 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {editingId ? 'Salvar' : 'Criar busca'}
          </button>
          {editingId ? (
            <button
              type="button"
              onClick={() => {
                setEditingId(null)
                setForm(emptyForm)
              }}
              className="rounded-lg border border-zinc-300 px-4 py-2 text-sm dark:border-zinc-700"
            >
              Cancelar
            </button>
          ) : null}
        </div>
      </form>

      <div className="mt-6 space-y-3">
        {isLoading ? <p className="text-sm text-zinc-500">Carregando…</p> : null}

        {profiles?.map((profile) => (
          <div
            key={profile.id}
            className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate font-medium">{profile.name}</h3>
                <p className="mt-0.5 truncate text-sm text-zinc-500">
                  {profile.keywords}
                  {profile.location ? ` · ${profile.location}` : ''}
                  {profile.remote_only ? ' · só remoto' : ''}
                </p>
                <p className="mt-1 text-xs text-zinc-500">{profile.sources.join(', ')}</p>
              </div>
              <button
                type="button"
                onClick={() => remove.mutate(profile.id)}
                className="shrink-0 text-sm text-red-600 hover:underline"
              >
                Excluir
              </button>
            </div>

            <div className="mt-3 flex gap-2">
              <button
                type="button"
                disabled={!user || inFlight || requestScrape.isPending}
                onClick={() => requestScrape.mutate({ profileId: profile.id, userId: user!.id })}
                className="rounded-lg bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
              >
                {inFlight ? 'Coletando…' : 'Buscar agora'}
              </button>
              <button
                type="button"
                onClick={() => startEdit(profile)}
                className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700"
              >
                Editar
              </button>
            </div>
          </div>
        ))}
      </div>

      {runs?.length ? (
        <section className="mt-8">
          <h2 className="mb-2 font-semibold">Últimas coletas</h2>
          <div className="space-y-1.5 text-sm">
            {runs.map((run) => (
              <div
                key={run.id}
                className="flex items-center justify-between gap-3 rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-800"
              >
                <span className="truncate">
                  {run.source} ·{' '}
                  {new Date(run.started_at).toLocaleString('pt-BR', {
                    day: '2-digit',
                    month: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${
                    run.status === 'ok'
                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                      : run.status === 'blocked'
                        ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300'
                        : 'bg-red-500/15 text-red-700 dark:text-red-300'
                  }`}
                  title={run.error ?? undefined}
                >
                  {run.status === 'ok'
                    ? `+${run.jobs_new} de ${run.jobs_found}`
                    : run.status === 'blocked'
                      ? 'bloqueado'
                      : 'erro'}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-zinc-500">
            "Bloqueado" no Google Jobs é esperado — ele flagra o IP após um acesso automatizado.
          </p>
        </section>
      ) : null}
    </div>
  )
}
