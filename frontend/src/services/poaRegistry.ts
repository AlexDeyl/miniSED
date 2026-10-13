import { api } from './api'

// Реестр доверенностей и МЧД (раздел юристов).
export type RegistryKind = 'poa' | 'mchd'
export type Validity = 'active' | 'expiring' | 'expired' | 'revoked' | 'no_term'

export interface RegistryEntry {
  id: number
  request: number | null
  request_number: string
  request_status: string
  request_status_display: string
  kind: RegistryKind
  kind_display: string
  organization: number
  organization_name: string
  number: string
  reg_number: string
  issue_date: string | null
  code: string
  representative: string
  powers: string
  valid_until: string | null
  cert_valid_until: string | null
  revoked_at: string | null
  comment: string
  validity: Validity
  validity_display: string
  created_at: string
  updated_at: string
}

export type RegistryEntryInput = Partial<Pick<RegistryEntry,
  'kind' | 'organization' | 'number' | 'reg_number' | 'issue_date' | 'code' |
  'representative' | 'powers' | 'valid_until' | 'cert_valid_until' | 'revoked_at' | 'comment'
>> & { assign_number?: boolean }

export interface RegistryMeta {
  organizations: { id: number; short_name: string }[]
  kinds: { code: RegistryKind; name: string }[]
  validity: { code: Validity; name: string }[]
  warn_days: number
  today: string
  can_edit: boolean
  can_history: boolean
}

export interface RegistryChange {
  id: number
  field: string
  field_display: string
  old_value: string
  new_value: string
  changed_by_b24_id: number | null
  changed_by_name: string
  changed_at: string
}

export interface Numbering {
  organization: number
  organization_name: string
  mask: string
  year: number
  last_seq: number
  next_number: string
}

export interface RegistryQuery {
  kind?: RegistryKind | ''
  organization?: number | ''
  validity?: Validity | ''
  q?: string
}

const BASE = '/reg/poa-registry'

function qs(f: RegistryQuery): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(f)) if (v !== '' && v !== undefined && v !== null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const poaRegistry = {
  list: (f: RegistryQuery) => api.get<RegistryEntry[]>(`${BASE}/${qs(f)}`),
  meta: () => api.get<RegistryMeta>(`${BASE}/meta/`),
  create: (data: RegistryEntryInput) => api.post<RegistryEntry>(`${BASE}/`, data),
  update: (id: number, data: RegistryEntryInput) => api.patch<RegistryEntry>(`${BASE}/${id}/`, data),
  remove: (id: number) => api.delete<void>(`${BASE}/${id}/`),
  history: (id: number) => api.get<RegistryChange[]>(`${BASE}/${id}/history/`),
  numbering: () => api.get<Numbering[]>(`${BASE}/numbering/`),
  setNumbering: (organization: number, data: { mask?: string; last_seq?: number }) =>
    api.patch<Numbering[]>(`${BASE}/numbering/`, { organization, ...data }),
  export: (f: RegistryQuery) =>
    api.download(`/api${BASE}/export/${qs(f)}`, `Реестр_доверенностей.xlsx`),
}
