import axios from 'axios'

export interface SourceRef {
  filename: string
  score: number | null
}

export interface ChatResponse {
  answer: string
  tool_used: string | null
  sources: SourceRef[]
}

export interface HistoryItem {
  id: number
  role: string
  message: string
  attachments: AttachmentRef[]
  created_at: string
}

export interface AttachmentRef {
  stored_name: string
  display_name: string
  kind: 'image' | 'document'
  mime: string
  size: number
  /** Client-only: a local object URL for the optimistic bubble, before the
   * server row exists to serve the real thumbnail. */
  previewUrl?: string | null
}

export interface SessionSummary {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

/** Mirrors the backend's stream_agent events plus the transport-only error type. */
export type StreamEvent =
  | { type: 'tool'; name: string }
  | { type: 'sources'; sources: SourceRef[] }
  | { type: 'delta'; text: string }
  | { type: 'done'; answer: string; tool_used: string | null; sources: SourceRef[] }
  | { type: 'error'; detail: string }

export interface StreamChatBody {
  session_id: string
  message: string
  attachments?: string[]
  truncate_after_id?: number
}

export interface UploadResponse {
  filename: string
  status: string
  kind: 'image' | 'document'
  stored_name: string
  display_name: string
  mime: string
  size: number
}

export const TOKEN_KEY = 'agentic-rag-token'
export const ROLE_KEY = 'agentic-rag-role'
export const USERNAME_KEY = 'agentic-rag-username'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 180_000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/**
 * A 401 anywhere except the login/register calls means the stored JWT is gone
 * or expired. Without this the UI keeps rendering the chat and every send
 * fails with a raw axios message, leaving the person stuck on a dead screen.
 */
export function handleUnauthorized(): Promise<never> {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ROLE_KEY)
  localStorage.removeItem(USERNAME_KEY)
  window.location.reload()
  return new Promise(() => {}) // the page is being replaced; never settle
}

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status: number | undefined = error.response?.status
    const url: string = error.config?.url ?? ''
    const isAuthCall = url.includes('/auth/')

    if (status === 401 && !isAuthCall) {
      return handleUnauthorized()
    }
    return Promise.reject(error)
  },
)

/**
 * True when a request failed because the resource is absent. `GET /chat/history`
 * answers 404 for a session that does not exist, deliberately and
 * indistinguishably from one owned by somebody else, so callers that treat
 * "absent" as "empty" need this rather than a raw status read.
 */
export function isNotFound(error: unknown): boolean {
  if (axios.isAxiosError(error)) return error.response?.status === 404
  // streamMessage bypasses axios; it attaches the status to what it throws.
  return (error as { status?: number } | null)?.status === 404
}

/** Turn a thrown value into something worth showing a person. */
export function describeError(error: unknown): string {
  if (!axios.isAxiosError(error)) {
    return error instanceof Error ? error.message : String(error)
  }

  if (!error.response) {
    return 'Tidak dapat menghubungi server. Pastikan backend berjalan di port 8000.'
  }

  const { status, data } = error.response
  const detail =
    data && typeof data === 'object' && 'detail' in data ? String((data as { detail: unknown }).detail) : ''

  switch (status) {
    case 401:
      return 'Username atau password salah.'
    case 400:
      return detail || 'Permintaan ditolak.'
    case 422:
      return detail || 'Berkas tidak dapat diproses.'
    case 503:
      return detail || 'Model lokal sedang tidak tersedia. Coba lagi sebentar lagi.'
    default:
      return detail || `Terjadi kesalahan pada server (${status}).`
  }
}

function parseSseFrame(frame: string): StreamEvent | null {
  const line = frame.split('\n').find((l) => l.startsWith('data: '))
  if (!line) return null
  try {
    return JSON.parse(line.slice('data: '.length)) as StreamEvent
  } catch {
    return null // a malformed frame is dropped, not fatal
  }
}

export const api = {
  async login(username: string, password: string): Promise<{ token: string; role: string }> {
    const { data } = await http.post('/auth/login', { username, password })
    return { token: data.access_token, role: data.role }
  },

  async fetchMe(): Promise<{ username: string; role: string; created_at: string }> {
    const { data } = await http.get('/auth/me')
    return data
  },

  async register(username: string, password: string): Promise<void> {
    await http.post('/auth/register', { username, password })
  },

  async sendMessage(sessionId: string, message: string, imagePath?: string): Promise<ChatResponse> {
    const { data } = await http.post('/chat', {
      session_id: sessionId,
      message,
      image_path: imagePath ?? null,
    })
    return data
  },

  async uploadFile(file: File): Promise<UploadResponse> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await http.post('/upload', form)
    return data
  },

  async fetchHistory(sessionId: string): Promise<HistoryItem[]> {
    const { data } = await http.get('/chat/history', { params: { session_id: sessionId } })
    return data
  },

  async listSessions(): Promise<SessionSummary[]> {
    const { data } = await http.get('/sessions')
    return data
  },

  async createSession(): Promise<SessionSummary> {
    const { data } = await http.post('/sessions')
    return data
  },

  async renameSession(sessionId: string, title: string): Promise<SessionSummary> {
    const { data } = await http.patch(`/sessions/${sessionId}`, { title })
    return data
  },

  async deleteSession(sessionId: string): Promise<void> {
    await http.delete(`/sessions/${sessionId}`)
  },

  async fetchAttachmentBlob(storedName: string): Promise<Blob> {
    // <img src> cannot carry the bearer token, so attachments are fetched like
    // streamMessage is: with fetch and the header, bypassing axios.
    const token = localStorage.getItem(TOKEN_KEY)
    const base = http.defaults.baseURL ?? ''
    const response = await fetch(`${base}/attachments/${encodeURIComponent(storedName)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (response.status === 401) {
      await handleUnauthorized()
      return new Blob()
    }
    if (!response.ok) throw new Error(`attachment failed (${response.status})`)
    return response.blob()
  },

  /**
   * POST /chat/stream as an async generator of parsed events.
   *
   * Axios cannot expose a streaming body in the browser and EventSource cannot
   * send a POST or an Authorization header, so this is the one place that
   * bypasses the axios instance. It must therefore reproduce what the
   * interceptors do: attach the bearer token and clear storage on 401.
   */
  async *streamMessage(body: StreamChatBody, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    const token = localStorage.getItem(TOKEN_KEY)
    const base = http.defaults.baseURL ?? ''
    const response = await fetch(`${base}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      signal,
    })

    if (response.status === 401) {
      await handleUnauthorized()
      return
    }
    if (!response.ok || !response.body) {
      let detail = ''
      try {
        const data = await response.json()
        if (data && typeof data === 'object' && 'detail' in data) detail = String(data.detail)
      } catch {
        // non-JSON error body
      }
      throw Object.assign(new Error(detail || `stream failed (${response.status})`), { status: response.status })
    }

    // SSE frames end with \n\n but a chunk boundary can land mid-frame, so the
    // reader keeps a carry buffer and only parses complete frames.
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let carry = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      carry += decoder.decode(value, { stream: true })
      let boundary = carry.indexOf('\n\n')
      while (boundary !== -1) {
        const event = parseSseFrame(carry.slice(0, boundary))
        carry = carry.slice(boundary + 2)
        if (event) yield event
        boundary = carry.indexOf('\n\n')
      }
    }
  },
}
