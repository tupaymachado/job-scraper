import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { getSupabase } from './supabase'
import type {
  JobStatusValue,
  JobWithMeta,
  ScrapeRun,
  SearchProfile,
  UserProfile,
} from './types'

export const PAGE_SIZE = 20

export interface FeedFilters {
  search: string
  source: string | null
  seniority: string | null
  workModel: string | null
  minScore: number
  status: JobStatusValue | 'all'
}

export const emptyFilters: FeedFilters = {
  search: '',
  source: null,
  seniority: null,
  workModel: null,
  minScore: 0,
  status: 'all',
}

/**
 * Feed paginado.
 *
 * job_matches e job_status são embeds por usuário — a RLS já limita ao
 * dono, então não precisamos filtrar por user_id na query.
 */
export function useJobsFeed(filters: FeedFilters) {
  return useInfiniteQuery({
    queryKey: ['jobs', filters],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      let query = getSupabase()
        .from('jobs')
        .select('*, job_enrichments(*), job_matches(*), job_status(*)')
        .order('first_seen_at', { ascending: false })
        .range(pageParam, pageParam + PAGE_SIZE - 1)

      if (filters.search) {
        // or() precisa dos valores sem vírgula, senão quebra o parser do PostgREST.
        const term = filters.search.replace(/[,()]/g, ' ').trim()
        query = query.or(`title.ilike.%${term}%,company.ilike.%${term}%`)
      }
      if (filters.source) query = query.eq('source', filters.source)
      if (filters.seniority) query = query.eq('job_enrichments.seniority', filters.seniority)
      if (filters.workModel) query = query.eq('job_enrichments.work_model', filters.workModel)

      const { data, error } = await query
      if (error) throw error

      let jobs = (data ?? []) as unknown as JobWithMeta[]

      // Score e status ficam em embeds — o PostgREST não filtra por eles
      // sem !inner, e !inner esconderia vagas ainda não pontuadas.
      if (filters.minScore > 0) {
        jobs = jobs.filter((j) => (j.job_matches?.[0]?.score ?? 0) >= filters.minScore)
      }
      if (filters.status !== 'all') {
        jobs = jobs.filter((j) => (j.job_status?.[0]?.status ?? 'new') === filters.status)
      }

      return { jobs, nextOffset: (data?.length ?? 0) === PAGE_SIZE ? pageParam + PAGE_SIZE : null }
    },
    getNextPageParam: (last) => last.nextOffset,
  })
}

export function useJob(jobId: string) {
  return useQuery({
    queryKey: ['job', jobId],
    queryFn: async () => {
      const { data, error } = await getSupabase()
        .from('jobs')
        .select('*, job_enrichments(*), job_matches(*), job_status(*)')
        .eq('id', jobId)
        .single()
      if (error) throw error
      return data as unknown as JobWithMeta
    },
  })
}

export function useSetJobStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      jobId,
      userId,
      status,
      notes,
    }: {
      jobId: string
      userId: string
      status: JobStatusValue
      notes?: string
    }) => {
      const { error } = await getSupabase()
        .from('job_status')
        .upsert(
          { job_id: jobId, user_id: userId, status, notes, updated_at: new Date().toISOString() },
          { onConflict: 'user_id,job_id' },
        )
      if (error) throw error
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['job', vars.jobId] })
    },
  })
}

export function useSearchProfiles() {
  return useQuery({
    queryKey: ['search_profiles'],
    queryFn: async () => {
      const { data, error } = await getSupabase()
        .from('search_profiles')
        .select('*')
        .order('created_at', { ascending: false })
      if (error) throw error
      return (data ?? []) as SearchProfile[]
    },
  })
}

export function useSaveSearchProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (profile: Partial<SearchProfile> & { user_id: string }) => {
      const { error } = await getSupabase().from('search_profiles').upsert(profile)
      if (error) throw error
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['search_profiles'] }),
  })
}

export function useDeleteSearchProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { error } = await getSupabase().from('search_profiles').delete().eq('id', id)
      if (error) throw error
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['search_profiles'] }),
  })
}

/**
 * "Buscar agora": insere na fila e o worker da VM faz poll a cada 60s.
 * A Vercel não alcança a VM, então a fila inverte o sentido da chamada.
 */
export function useRequestScrape() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ profileId, userId }: { profileId: string; userId: string }) => {
      const { error } = await getSupabase()
        .from('scrape_requests')
        .insert({ search_profile_id: profileId, user_id: userId })
      if (error) throw error
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scrape_requests'] }),
  })
}

export function useScrapeRequests() {
  return useQuery({
    queryKey: ['scrape_requests'],
    queryFn: async () => {
      const { data, error } = await getSupabase()
        .from('scrape_requests')
        .select('*')
        .order('requested_at', { ascending: false })
        .limit(5)
      if (error) throw error
      return data ?? []
    },
    // Enquanto houver pedido em voo, acompanha o worker de perto.
    refetchInterval: (q) => {
      const rows = (q.state.data ?? []) as { status: string }[]
      return rows.some((r) => r.status === 'pending' || r.status === 'running') ? 5_000 : false
    },
  })
}

export function useScrapeRuns() {
  return useQuery({
    queryKey: ['scrape_runs'],
    queryFn: async () => {
      const { data, error } = await getSupabase()
        .from('scrape_runs')
        .select('*')
        .order('started_at', { ascending: false })
        .limit(10)
      if (error) throw error
      return (data ?? []) as ScrapeRun[]
    },
  })
}

export function useUserProfile(userId: string | undefined) {
  return useQuery({
    queryKey: ['user_profile', userId],
    enabled: Boolean(userId),
    queryFn: async () => {
      const { data, error } = await getSupabase()
        .from('user_profiles')
        .select('*')
        .eq('user_id', userId!)
        .maybeSingle()
      if (error) throw error
      return data as UserProfile | null
    },
  })
}

export function useSaveUserProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (profile: { user_id: string; cv_text: string; preferences: string }) => {
      const { error } = await getSupabase()
        .from('user_profiles')
        .upsert({ ...profile, updated_at: new Date().toISOString() })
      if (error) throw error
    },
    onSuccess: (_d, vars) =>
      qc.invalidateQueries({ queryKey: ['user_profile', vars.user_id] }),
  })
}
