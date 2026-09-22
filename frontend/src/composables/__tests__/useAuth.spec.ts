import { AxiosError, type AxiosResponse } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, SESSION_ENDED_KEY } from '../../services/api'
import { useAuth } from '../useAuth'

// vite.config.ts sets no restoreMocks, so without this the spied api methods
// stay mocked for every case added below them.
afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
})

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
    // A real AxiosError carrying a 401: the case the axios interceptor defers here.
    const rejected = new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 401,
    } as AxiosResponse)
    vi.spyOn(api, 'fetchMe').mockRejectedValue(rejected)

    await auth.fetchMe()

    expect(auth.isAuthenticated.value).toBe(false)
  })

  it('leaves a note when the rejection is what ended the session', async () => {
    // The cold-start shape of a deactivated account: opening the app the next day
    // produces this one 401 and nothing else, so the login form has to be told here
    // or the person types the right password and is told it is wrong.
    const auth = useAuth()
    auth.token.value = 'stale-token'
    const rejected = new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 401,
    } as AxiosResponse)
    vi.spyOn(api, 'fetchMe').mockRejectedValue(rejected)

    await auth.fetchMe()

    expect(sessionStorage.getItem(SESSION_ENDED_KEY)).toBe('1')
  })

  it('keeps the session when the call fails for a reason other than a rejection', async () => {
    const auth = useAuth()
    auth.token.value = 'good-token'
    // What axios throws when the connection drops: an AxiosError with no response.
    // The token is still valid, so signing the person out here would be wrong.
    vi.spyOn(api, 'fetchMe').mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))

    await auth.fetchMe()

    expect(auth.isAuthenticated.value).toBe(true)
  })
})

describe('useAuth.login', () => {
  it('sets username from the credentials, so it is populated without a reload', async () => {
    const auth = useAuth()
    vi.spyOn(api, 'login').mockResolvedValue({ token: 'fresh-token', role: 'USER' })

    await auth.login('budi', 'pw')

    expect(auth.username.value).toBe('budi')
  })
})
