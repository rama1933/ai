import { ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'

import { api, describeError, type SessionSummary } from '../services/api'

// Module-level singleton, the same shape useAuth uses: every component calling
// useSessions() shares one list and one active conversation.
const sessions = ref<SessionSummary[]>([])
const activeId = useLocalStorage<string | null>('agentic-rag-session', null)
const isLoading = ref(false)
const error = ref<string | null>(null)

export function useSessions() {
  /**
   * Pull the caller's conversations and reconcile the active id.
   *
   * Migration for users of the pre-sidebar build, and it must be silent: their
   * localStorage key holds a bare session id from before POST /sessions existed.
   * When the server list is empty but a stored id is present, keep using it --
   * POST /chat adopts it through get_or_create_session, so the returning user
   * lands back in their last conversation. No prompt, no lost conversation.
   */
  async function refresh(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      sessions.value = await api.listSessions()
      if (sessions.value.length === 0) return
      if (!activeId.value || !sessions.value.some((s) => s.id === activeId.value)) {
        activeId.value = sessions.value[0].id
      }
    } catch (err) {
      error.value = describeError(err)
    } finally {
      isLoading.value = false
    }
  }

  /** Create an empty conversation server-side and make it active. */
  async function create(): Promise<SessionSummary> {
    const created = await api.createSession()
    sessions.value.unshift(created)
    activeId.value = created.id
    return created
  }

  async function rename(id: string, title: string): Promise<void> {
    const updated = await api.renameSession(id, title)
    const index = sessions.value.findIndex((s) => s.id === id)
    if (index !== -1) sessions.value[index] = updated
  }

  /** Delete a conversation; when it was active, activate the next one. */
  async function remove(id: string): Promise<void> {
    await api.deleteSession(id)
    const index = sessions.value.findIndex((s) => s.id === id)
    if (index === -1) return
    sessions.value.splice(index, 1)
    if (activeId.value === id) activeId.value = sessions.value[0]?.id ?? null
  }

  function select(id: string): void {
    activeId.value = id
  }

  /** Drop the active pointer. Used on logout: conversations belong to the account. */
  function forget(): void {
    activeId.value = null
  }

  return { sessions, activeId, isLoading, error, refresh, create, rename, remove, select, forget }
}
