import { useState } from 'react'
import { useAuth, signInWithEmail } from '../lib/auth'
import { isSupabaseConfigured } from '../lib/supabase'

/** Login por magic link. Envolve toda tela que precisa de sessão. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  if (!isSupabaseConfigured) {
    return (
      <div className="mx-auto max-w-md p-6">
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-800 dark:bg-amber-950/40">
          <p className="font-semibold text-amber-900 dark:text-amber-200">Supabase não configurado</p>
          <p className="mt-1 text-amber-800 dark:text-amber-300">
            Copie <code>web/.env.example</code> para <code>web/.env.local</code> e preencha
            <code> VITE_SUPABASE_URL</code> e <code>VITE_SUPABASE_ANON_KEY</code>.
          </p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-sm text-zinc-500">
        Carregando…
      </div>
    )
  }

  if (user) return <>{children}</>

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSending(true)
    try {
      await signInWithEmail(email)
      setSent(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao enviar o link')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold tracking-tight">Vagas</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Entre com seu e-mail para receber um link de acesso.
        </p>

        {sent ? (
          <div className="mt-6 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
            Link enviado para <strong>{email}</strong>. Confira sua caixa de entrada.
          </div>
        ) : (
          <form onSubmit={submit} className="mt-6 space-y-3">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="voce@exemplo.com"
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2.5 text-base outline-none focus:border-sky-500 dark:border-zinc-700 dark:bg-zinc-900"
            />
            <button
              type="submit"
              disabled={sending}
              className="w-full rounded-lg bg-sky-600 px-4 py-2.5 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
            >
              {sending ? 'Enviando…' : 'Enviar link'}
            </button>
            {error ? <p className="text-sm text-red-600">{error}</p> : null}
          </form>
        )}
      </div>
    </div>
  )
}
