import { ref } from 'vue'

import { api, describeError, isNotFound, type SourceRef } from '../services/api'
import { useSessions } from './useSessions'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  toolUsed?: string | null
  sources?: SourceRef[]
}

export function useChat() {
  // One active conversation across the app; the sidebar owns switching.
  const { activeId } = useSessions()
  const messages = ref<ChatMessage[]>([])
  const input = ref('')
  const pendingImage = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  /** The id the next message goes to, minting one when nothing is active yet. */
  function resolveSessionId(): string {
    if (activeId.value) return activeId.value
    // A brand-new account has no server-side session to select. Mint as the
    // pre-sidebar build did; POST /chat adopts the id through get_or_create_session.
    const minted = `session-${crypto.randomUUID()}`
    activeId.value = minted
    return minted
  }

  async function loadHistory(): Promise<void> {
    if (!activeId.value) return
    try {
      const history = await api.fetchHistory(activeId.value)
      messages.value = history.map((item) => ({
        role: item.role === 'user' ? 'user' : 'assistant',
        content: item.message,
      }))
    } catch (err) {
      // A session id is generated client-side, so a brand-new conversation has no
      // row until the first POST /chat. GET /chat/history answers 404 for that --
      // deliberately, and the same 404 an unowned session gets -- which means
      // "empty", not "broken". Anything else is a real error worth a banner.
      if (isNotFound(err)) return
      error.value = describeError(err)
    }
  }

  /** Sidebar navigation: clear this conversation's state, load the target's. */
  async function switchTo(): Promise<void> {
    messages.value = []
    input.value = ''
    pendingImage.value = null
    error.value = null
    await loadHistory()
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

  /** One attempt. Returns the failure, or null when the reply landed. */
  async function deliver(sessionId: string, text: string): Promise<unknown> {
    try {
      const response = await api.sendMessage(sessionId, text, pendingImage.value ?? undefined)
      messages.value.push({
        role: 'assistant',
        content: response.answer,
        toolUsed: response.tool_used,
        sources: response.sources,
      })
      pendingImage.value = null
      return null
    } catch (err) {
      return err
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
      let failure = await deliver(resolveSessionId(), text)
      if (failure && isNotFound(failure)) {
        // The stored id is unknown or belongs to another account -- stale
        // localStorage after a logout on a shared browser. A fresh conversation
        // fixes it; retrying is cheaper than a dead-end "unknown session".
        activeId.value = null
        failure = await deliver(resolveSessionId(), text)
      }
      if (failure) error.value = describeError(failure)
    } finally {
      isLoading.value = false
    }
  }

  return { sessionId: activeId, messages, input, pendingImage, isLoading, error, send, attach, loadHistory, switchTo }
}
