/** Espelha supabase/migrations/0001_init.sql. */

export type JobSource = 'linkedin' | 'google_jobs'

export type Seniority = 'estagio' | 'junior' | 'pleno' | 'senior' | 'staff' | 'lead'
export type WorkModel = 'remoto' | 'hibrido' | 'presencial'
export type ContractType = 'clt' | 'pj' | 'estagio' | 'freelance' | 'temporario'
export type JobStatusValue = 'new' | 'saved' | 'applied' | 'discarded'

export interface Job {
  id: string
  source: JobSource
  source_job_id: string
  url: string
  title: string
  company: string | null
  location: string | null
  work_model: string | null
  posted_at: string | null
  description_html: string | null
  description_text: string | null
  first_seen_at: string
}

export interface JobEnrichment {
  job_id: string
  seniority: Seniority | null
  stack: string[] | null
  work_model: WorkModel | null
  contract_type: ContractType | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  tags: string[] | null
  summary: string | null
  model: string | null
}

export interface JobMatch {
  job_id: string
  score: number
  reasoning: string | null
}

export interface JobStatus {
  job_id: string
  status: JobStatusValue
  notes: string | null
}

/** Vaga com os joins que o feed usa. O PostgREST devolve os embeds como array. */
export interface JobWithMeta extends Job {
  job_enrichments: JobEnrichment | JobEnrichment[] | null
  job_matches: JobMatch[] | null
  job_status: JobStatus[] | null
}

export interface SearchProfile {
  id: string
  user_id: string
  name: string
  keywords: string
  location: string | null
  remote_only: boolean
  sources: JobSource[]
  enabled: boolean
  created_at: string
}

export interface UserProfile {
  user_id: string
  cv_text: string | null
  preferences: string | null
  updated_at: string
}

export interface ScrapeRequest {
  id: string
  search_profile_id: string | null
  status: 'pending' | 'running' | 'done' | 'error'
  requested_at: string
  finished_at: string | null
  error: string | null
}

export interface ScrapeRun {
  id: string
  source: JobSource
  started_at: string
  finished_at: string | null
  status: 'ok' | 'blocked' | 'error' | null
  jobs_found: number
  jobs_new: number
  error: string | null
}

/** O PostgREST às vezes devolve um embed 1:1 como array de um item. */
export function one<T>(value: T | T[] | null | undefined): T | null {
  if (!value) return null
  return Array.isArray(value) ? (value[0] ?? null) : value
}
