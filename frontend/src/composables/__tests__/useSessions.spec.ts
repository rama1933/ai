import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../../services/api'
import { useSessions } from '../useSessions'

describe('useSessions', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    // Module-level singleton: put it back to a bootstrapped state between tests.
    const sessions = useSessions()
    sessions.sessions.value = []
    sessions.activeId.value = null
    sessions.error.value = null
  })

  it('create prepends the new conversation and activates it', async () => {
    const { sessions, activeId, create } = useSessions()
    sessions.value = [{ id: 'session-old', title: 'lama', created_at: '', updated_at: '' }]
    vi.spyOn(api, 'createSession').mockResolvedValue({
      id: 'session-new',
      title: null,
      created_at: '',
      updated_at: '',
    })

    const created = await create()

    expect(created.id).toBe('session-new')
    expect(sessions.value.map((s) => s.id)).toEqual(['session-new', 'session-old'])
    expect(activeId.value).toBe('session-new')
  })

  it('rename updates the row in place', async () => {
    const { sessions, rename } = useSessions()
    sessions.value = [{ id: 'session-1', title: 'awal', created_at: '', updated_at: '' }]
    vi.spyOn(api, 'renameSession').mockResolvedValue({
      id: 'session-1',
      title: 'Retensi dokumen',
      created_at: '',
      updated_at: '2026-09-22T10:00:00Z',
    })

    await rename('session-1', 'Retensi dokumen')

    expect(sessions.value).toHaveLength(1)
    expect(sessions.value[0].title).toBe('Retensi dokumen')
  })

  it('remove drops the row and, when it was active, activates the next one', async () => {
    const { sessions, activeId, remove } = useSessions()
    sessions.value = [
      { id: 'session-a', title: 'A', created_at: '', updated_at: '' },
      { id: 'session-b', title: 'B', created_at: '', updated_at: '' },
    ]
    activeId.value = 'session-b'
    vi.spyOn(api, 'deleteSession').mockResolvedValue(undefined)

    await remove('session-b')

    expect(sessions.value.map((s) => s.id)).toEqual(['session-a'])
    expect(activeId.value).toBe('session-a')

    await remove('session-a')
    expect(activeId.value).toBeNull()
  })

  it('a stored legacy id survives an empty server list', async () => {
    // Users of the pre-sidebar build carry a bare session id in localStorage;
    // POST /chat adopts it server-side, so it must not be discarded here.
    const { activeId, refresh } = useSessions()
    activeId.value = 'session-legacy'
    vi.spyOn(api, 'listSessions').mockResolvedValue([])

    await refresh()

    expect(activeId.value).toBe('session-legacy')
  })

  it('refresh selects the newest row when the active id is unknown', async () => {
    const { activeId, refresh, sessions } = useSessions()
    activeId.value = 'session-gone'
    vi.spyOn(api, 'listSessions').mockResolvedValue([
      { id: 'session-newest', title: 'terbaru', created_at: '', updated_at: '2026-09-22T10:00:00Z' },
      { id: 'session-older', title: 'lama', created_at: '', updated_at: '2026-09-21T10:00:00Z' },
    ])

    await refresh()

    expect(activeId.value).toBe('session-newest')
    expect(sessions.value).toHaveLength(2)
  })
})
