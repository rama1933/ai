import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import LoginForm from '../LoginForm.vue'
import { SESSION_ENDED_KEY } from '../../services/api'

describe('LoginForm', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  it('explains a forced sign-out rather than leaving it looking like a bad password', async () => {
    // What handleUnauthorized leaves behind when the server rejects a stored token --
    // the shape an admin deactivating an account takes.
    sessionStorage.setItem(SESSION_ENDED_KEY, '1')

    const wrapper = mount(LoginForm)
    await flushPromises()

    expect(wrapper.find('[role="status"]').text()).toContain('Sesi Anda berakhir')
    // Read once, then dropped: it describes the session that just ended, not this one.
    expect(sessionStorage.getItem(SESSION_ENDED_KEY)).toBeNull()
  })

  it('says nothing when the page was simply opened', async () => {
    const wrapper = mount(LoginForm)
    await flushPromises()

    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})
