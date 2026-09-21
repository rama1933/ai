import { ref } from 'vue'

import {
  api,
  describeError,
  isNotFound,
  type SourceRef,
  type StreamEvent,
} from '../services/api'
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
  const isLoading = ref(false) // request in flight, no token received yet
  const isStreaming = ref(false) // tokens are arriving; stop is available
  const error = ref<string | null>(null)
  let controller: AbortController | null = null

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

  function applyEvent(event: StreamEvent, assistant: ChatMessage): void {
    if (event.type === 'delta') {
      assistant.content += event.text
    } else if (event.type === 'tool') {
      assistant.toolUsed = event.name
    } else if (event.type === 'sources') {
      assistant.sources = event.sources
    } else if (event.type === 'done') {
      // The full answer is authoritative: it is stripped and carries any text
      // the backend's JSON-leak guard held back.
      assistant.content = event.answer
      assistant.toolUsed = event.tool_used
      assistant.sources = event.sources
    }
  }

  /** One stream attempt. Returns the failure, or null when it finished cleanly. */
  async function consume(sessionId: string, text: string, assistant: ChatMessage): Promise<unknown> {
    try {
      for await (const event of api.streamMessage(
        { session_id: sessionId, message: text, attachments: pendingImage.value ? [pendingImage.value] : [] },
        controller!.signal,
      )) {
        // First byte arrived: swap the typing dots for the growing answer.
        isLoading.value = false
        isStreaming.value = true
        if (event.type === 'error') return new Error(event.detail)
        applyEvent(event, assistant)
      }
      // The attachment travelled with this message (a stopped stream keeps it
      // server-side too), so the composer no longer holds it.
      pendingImage.value = null
      return null
    } catch (err) {
      if ((err as Error | null)?.name === 'AbortError') return null // stop() is deliberate
      return err
    }
  }

  async function send(): Promise<void> {
    const text = input.value.trim()
    if (!text || isLoading.value || isStreaming.value) return

    error.value = null
    messages.value.push({ role: 'user', content: text })
    messages.value.push({ role: 'assistant', content: '' })
    // Index the reactive array rather than keeping the raw object pushed into
    // it: mutations on the raw object bypass the proxy and never re-render.
    const assistant = messages.value[messages.value.length - 1]
    input.value = ''
    isLoading.value = true
    controller = new AbortController()

    try {
      let failure = await consume(resolveSessionId(), text, assistant)
      if (failure && isNotFound(failure)) {
        // The stored id is unknown or belongs to another account -- stale
        // localStorage after a logout on a shared browser. A fresh conversation
        // fixes it; retrying is cheaper than a dead-end "unknown session".
        activeId.value = null
        failure = await consume(resolveSessionId(), text, assistant)
      }
      if (failure) {
        error.value = describeError(failure)
        // An empty failed bubble is noise; the banner tells the story.
        if (!assistant.content) messages.value.pop()
      }
    } finally {
      isLoading.value = false
      isStreaming.value = false
      controller = null
    }
  }

  /** Abort the stream. The server persists the truncated answer in its finally. */
  function stop(): void {
    controller?.abort()
  }

  return {
    sessionId: activeId,
    messages,
    input,
    pendingImage,
    isLoading,
    isStreaming,
    error,
    send,
    stop,
    attach,
    loadHistory,
    switchTo,
  }
}
