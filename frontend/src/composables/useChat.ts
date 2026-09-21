import { ref } from 'vue'

import { api, describeError, type SourceRef } from '../services/api'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  toolUsed?: string | null
  sources?: SourceRef[]
}

const SESSION_KEY = 'agentic-rag-session'

function resolveSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY)
  if (!id) {
    id = `session-${crypto.randomUUID()}`
    localStorage.setItem(SESSION_KEY, id)
  }
  return id
}

export function useChat() {
  const sessionId = resolveSessionId()
  const messages = ref<ChatMessage[]>([])
  const input = ref('')
  const pendingImage = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function loadHistory(): Promise<void> {
    try {
      const history = await api.fetchHistory(sessionId)
      messages.value = history.map((item) => ({
        role: item.role === 'user' ? 'user' : 'assistant',
        content: item.message,
      }))
    } catch (err) {
      error.value = describeError(err)
    }
  }

  async function attach(file: File): Promise<void> {
    error.value = null
    isLoading.value = true
    try {
      const result = await api.uploadFile(file)
      if (result.kind === 'image') {
        pendingImage.value = result.filename
      } else {
        messages.value.push({
          role: 'assistant',
          content: `Dokumen **${result.filename}** sudah diproses dan masuk ke knowledge base.`,
        })
      }
    } catch (err) {
      error.value = describeError(err)
    } finally {
      isLoading.value = false
    }
  }

  async function send(): Promise<void> {
    const text = input.value.trim()
    if (!text || isLoading.value) return

    error.value = null
    messages.value.push({ role: 'user', content: text })
    input.value = ''
    isLoading.value = true

    try {
      const response = await api.sendMessage(sessionId, text, pendingImage.value ?? undefined)
      messages.value.push({
        role: 'assistant',
        content: response.answer,
        toolUsed: response.tool_used,
        sources: response.sources,
      })
      pendingImage.value = null
    } catch (err) {
      error.value = describeError(err)
    } finally {
      isLoading.value = false
    }
  }

  return { sessionId, messages, input, pendingImage, isLoading, error, send, attach, loadHistory }
}
