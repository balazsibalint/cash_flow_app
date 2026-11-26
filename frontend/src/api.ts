import type { Invoice, Report, UploadResult } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // nem JSON a válasz
  }
  if (res.status === 413) return 'A fájl túl nagy.'
  return `A szerver hibát adott (HTTP ${res.status}).`
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError(0, 'A szerver nem érhető el.')
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const api = {
  report: () => request<Report>('/api/report'),
  invoices: () => request<Invoice[]>('/api/invoices'),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return request<UploadResult>('/api/invoices', { method: 'POST', body: form })
  },
  deleteInvoice: (id: number) => request<void>(`/api/invoices/${id}`, { method: 'DELETE' }),
  deleteAll: () => request<void>('/api/invoices', { method: 'DELETE' }),
  pdfUrl: (id: number) => `/api/invoices/${id}/pdf`,
}
