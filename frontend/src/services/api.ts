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

const TOKEN_KEY = 'agentic-rag-token'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 180_000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export const api = {
  tokenKey: TOKEN_KEY,

  async login(username: string, password: string): Promise<{ token: string; role: string }> {
    const { data } = await http.post('/auth/login', { username, password })
    return { token: data.access_token, role: data.role }
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
