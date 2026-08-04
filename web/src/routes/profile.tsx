import { useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { RequireAuth } from '../components/RequireAuth'
import { signOut, useAuth } from '../lib/auth'
import { useSaveUserProfile, useUserProfile } from '../lib/queries'

export const Route = createFileRoute('/profile')({
  component: () => (
    <RequireAuth>
      <Profile />
    </RequireAuth>
  ),
})

function Profile() {
  const { user } = useAuth()
  const { data: profile, isLoading } = useUserProfile(user?.id)
  const save = useSaveUserProfile()

  const [cvText, setCvText] = useState('')
  const [preferences, setPreferences] = useState('')
  const [saved, setSaved] = useState(false)

  // Só popula quando os dados chegam — evita apagar o que o usuário digitou.
  useEffect(() => {
    if (profile) {
      setCvText(profile.cv_text ?? '')
      setPreferences(profile.preferences ?? '')
    }
  }, [profile])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!user) return
    await save.mutateAsync({ user_id: user.id, cv_text: cvText, preferences })
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
  }

  return (
    <div className="mx-auto max-w-3xl p-4 md:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold md:text-2xl">Perfil</h1>
          <p className="mt-1 text-sm text-zinc-500">{user?.email}</p>
        </div>
        <button
          type="button"
          onClick={() => signOut()}
          className="shrink-0 rounded-lg border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700"
        >
          Sair
        </button>
      </div>

      <p className="mt-4 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
        O texto abaixo é o que a IA usa para calcular o score de aderência de cada vaga. Quanto mais
        concreto (tecnologias, anos de experiência, tipo de vaga que você quer), melhor o score.
      </p>

      {isLoading ? (
        <p className="mt-4 text-sm text-zinc-500">Carregando…</p>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-4">
          <div>
            <label htmlFor="cv" className="mb-1.5 block text-sm font-medium">
              Currículo / resumo profissional
            </label>
            <textarea
              id="cv"
              value={cvText}
              onChange={(e) => setCvText(e.target.value)}
              rows={14}
              placeholder="Cole aqui seu CV ou um resumo: stack, anos de experiência, projetos relevantes…"
              className="w-full rounded-lg border border-zinc-300 bg-white p-3 text-sm leading-relaxed outline-none focus:border-sky-500 dark:border-zinc-700 dark:bg-zinc-900"
            />
          </div>

          <div>
            <label htmlFor="prefs" className="mb-1.5 block text-sm font-medium">
              Preferências
            </label>
            <textarea
              id="prefs"
              value={preferences}
              onChange={(e) => setPreferences(e.target.value)}
              rows={4}
              placeholder="Ex: só remoto, PJ, faixa a partir de R$ 12k, evitar consultoria…"
              className="w-full rounded-lg border border-zinc-300 bg-white p-3 text-sm leading-relaxed outline-none focus:border-sky-500 dark:border-zinc-700 dark:bg-zinc-900"
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded-lg bg-sky-600 px-4 py-2 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
            >
              {save.isPending ? 'Salvando…' : 'Salvar'}
            </button>
            {saved ? <span className="text-sm text-emerald-600">Salvo</span> : null}
          </div>

          <p className="text-xs text-zinc-500">
            Depois de editar o CV, rode{' '}
            <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
              python -m ai.match --user-id {user?.id ?? '<seu-id>'}
            </code>{' '}
            no worker para recalcular os scores.
          </p>
        </form>
      )}
    </div>
  )
}
