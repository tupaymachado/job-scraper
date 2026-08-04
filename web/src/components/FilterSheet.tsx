import { emptyFilters } from '../lib/queries'
import type { FeedFilters } from '../lib/queries'

const SENIORITIES = ['estagio', 'junior', 'pleno', 'senior', 'staff', 'lead']
const WORK_MODELS = ['remoto', 'hibrido', 'presencial']
const SOURCES = [
  { value: 'linkedin', label: 'LinkedIn' },
  { value: 'gupy', label: 'Gupy' },
  { value: 'careerjet', label: 'Careerjet' },
  { value: 'google_jobs', label: 'Google Jobs' },
]
const STATUSES = [
  { value: 'all', label: 'Todas' },
  { value: 'new', label: 'Novas' },
  { value: 'saved', label: 'Salvas' },
  { value: 'applied', label: 'Candidatei' },
  { value: 'discarded', label: 'Descartadas' },
]

interface Props {
  filters: FeedFilters
  onChange: (f: FeedFilters) => void
  /** No mobile vira bottom sheet; no desktop, uma coluna fixa. */
  onClose?: () => void
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-sm capitalize transition-colors ${
        active
          ? 'border-sky-500 bg-sky-500 text-white'
          : 'border-zinc-300 text-zinc-700 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-300'
      }`}
    >
      {label}
    </button>
  )
}

export function FilterPanel({ filters, onChange, onClose }: Props) {
  const set = <K extends keyof FeedFilters>(key: K, value: FeedFilters[K]) =>
    onChange({ ...filters, [key]: value })

  const toggle = (key: 'source' | 'seniority' | 'workModel', value: string) =>
    set(key, filters[key] === value ? null : value)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-zinc-900 dark:text-zinc-100">Filtros</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onChange(emptyFilters)}
            className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"
          >
            Limpar
          </button>
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              className="text-sm font-medium text-sky-600 dark:text-sky-400"
            >
              Aplicar
            </button>
          ) : null}
        </div>
      </div>

      <section>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Status</h3>
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <Chip
              key={s.value}
              label={s.label}
              active={filters.status === s.value}
              onClick={() => set('status', s.value as FeedFilters['status'])}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Fonte</h3>
        <div className="flex flex-wrap gap-2">
          {SOURCES.map((s) => (
            <Chip
              key={s.value}
              label={s.label}
              active={filters.source === s.value}
              onClick={() => toggle('source', s.value)}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
          Senioridade
        </h3>
        <div className="flex flex-wrap gap-2">
          {SENIORITIES.map((s) => (
            <Chip
              key={s}
              label={s}
              active={filters.seniority === s}
              onClick={() => toggle('seniority', s)}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Modelo</h3>
        <div className="flex flex-wrap gap-2">
          {WORK_MODELS.map((m) => (
            <Chip
              key={m}
              label={m}
              active={filters.workModel === m}
              onClick={() => toggle('workModel', m)}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
          Score mínimo: {filters.minScore}
        </h3>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={filters.minScore}
          onChange={(e) => set('minScore', Number(e.target.value))}
          className="w-full accent-sky-500"
        />
      </section>
    </div>
  )
}

export function FilterSheet({ filters, onChange, onClose }: Props & { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        role="presentation"
      />
      <div className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-2xl bg-white p-5 pb-8 dark:bg-zinc-900">
        <FilterPanel filters={filters} onChange={onChange} onClose={onClose} />
      </div>
    </div>
  )
}
