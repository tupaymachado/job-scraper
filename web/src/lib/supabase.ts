import { createBrowserClient } from '@supabase/ssr'
import type { SupabaseClient } from '@supabase/supabase-js'

/**
 * Client do Supabase para o browser.
 *
 * Usa só a anon key — toda a proteção vem da RLS definida na migration.
 * A service_role key NUNCA entra aqui: ela vive só no worker, na VM.
 */

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

let client: SupabaseClient | null = null

export function getSupabase(): SupabaseClient {
  if (!url || !anonKey) {
    throw new Error(
      'Faltam VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY. ' +
        'Copie web/.env.example para web/.env.local e preencha.',
    )
  }
  // Singleton: cada createBrowserClient abre o seu próprio canal de auth.
  client ??= createBrowserClient(url, anonKey)
  return client
}

export const isSupabaseConfigured = Boolean(url && anonKey)
