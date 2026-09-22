import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AdminLayout from '../admin/AdminLayout.vue'
import { useAuth } from '../../composables/useAuth'
import { useSessions } from '../../composables/useSessions'
import { useView } from '../../composables/useView'
import { api, type AdminStats } from '../../services/api'

const STATS: AdminStats = {
  users: 4,
  active_users: 3,
  documents: 9,
  chunks: 617,
  sessions: 14,
  messages: 47,
  storage_bytes: 4_790_269,
}

function mountLayout() {
  return mount(AdminLayout, { slots: { default: '<p>isi</p>' } })
}

describe('AdminLayout', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    useAuth().username.value = 'admin'
    useAuth().role.value = 'ADMIN'
    useView().view.value = 'admin/knowledge'
    const sessions = useSessions()
    sessions.sessions.value = []
    sessions.error.value = null
    sessions.isLoading.value = false
  })

  it('summarises the system in the header', async () => {
    vi.spyOn(api.admin, 'stats').mockResolvedValue(STATS)

    const wrapper = mountLayout()
    await flushPromises()

    expect(wrapper.text()).toContain('4 pengguna (3 aktif)')
    expect(wrapper.text()).toContain('9 dokumen')
    expect(wrapper.text()).toContain('4.6 MB')
    expect(wrapper.text()).not.toContain('Ringkasan tidak tersedia')
  })

  it('says the summary is unavailable rather than quietly showing a username', async () => {
    vi.spyOn(api.admin, 'stats').mockRejectedValue(new Error('boom'))

    const wrapper = mountLayout()
    await flushPromises()

    expect(wrapper.text()).toContain('Ringkasan tidak tersedia')
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('isi'), 'the screen below still renders'
  })
})
