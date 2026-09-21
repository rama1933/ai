import { describe, expect, it, vi } from 'vitest'

import { api } from '../../services/api'
import { useAuth } from '../useAuth'

// useAuth holds its state in module-level refs, so these tests drive that state
// through the refs it returns. Clearing localStorage between cases would not reset
// them, and the second test would then inherit the first test's token.
describe('useAuth.fetchMe', () => {
  it('populates username and role from the server, not from localStorage', async () => {
    const auth = useAuth()
    auth.token.value = 'a-token'
    auth.role.value = 'ADMIN' // deliberately wrong, to prove the server wins
    vi.spyOn(api, 'fetchMe').mockResolvedValue({
      username: 'siti',
      role: 'USER',
      created_at: '2026-09-21T00:00:00',
    })

    await auth.fetchMe()

    expect(auth.username.value).toBe('siti')
    expect(auth.role.value).toBe('USER')
  })

  it('clears the session when the stored token is rejected', async () => {
    const auth = useAuth()
    auth.token.value = 'stale-token'
    vi.spyOn(api, 'fetchMe').mockRejectedValue(new Error('401'))

    await auth.fetchMe()

    expect(auth.isAuthenticated.value).toBe(false)
  })
})
