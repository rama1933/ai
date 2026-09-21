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
  role: string
  message: string
  created_at: string
}

export interface UploadResponse {
  filename: string
  status: string
  kind: 'image' | 'document'
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
http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status: number | undefined = error.response?.status
    const url: string = error.config?.url ?? ''
    const isAuthCall = url.includes('/auth/')

    if (status === 401 && !isAuthCall) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(ROLE_KEY)
      localStorage.removeItem(USERNAME_KEY)
      window.location.reload()
      return new Promise(() => {}) // the page is being replaced; never settle
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
  return axios.isAxiosError(error) && error.response?.status === 404
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
}
