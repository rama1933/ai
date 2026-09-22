import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuth } from '../../composables/useAuth'
import { useSessions } from '../../composables/useSessions'
import { useView } from '../../composables/useView'
import SessionSidebarBody from '../SessionSidebarBody.vue'

/**
 * The sidebar's admin menu. Both it and useView are module-level singletons, so
 * each case puts them back to a known state first.
 */
function mountBody() {
  return mount(SessionSidebarBody)
}

function adminMenu(wrapper: ReturnType<typeof mountBody>) {
  return wrapper.find('nav[aria-label="Menu admin"]')
}

describe('SessionSidebarBody admin menu', () => {
  beforeEach(() => {
    localStorage.clear()
    const { role, username, token } = useAuth()
    role.value = null
    username.value = null
    token.value = null
    const sessions = useSessions()
    sessions.sessions.value = []
    sessions.error.value = null
    sessions.isLoading.value = false
    useView().view.value = 'chat'
  })

  it('shows the three console links to an admin', () => {
    useAuth().role.value = 'ADMIN'

    const menu = adminMenu(mountBody())

    expect(menu.exists()).toBe(true)
    expect(menu.text()).toContain('Admin')
    expect(menu.text()).toContain('Data Training')
    expect(menu.text()).toContain('Log Aktivitas')
    expect(menu.text()).toContain('Pengguna')
  })

  it('shows nothing of the sort to a user', () => {
    useAuth().role.value = 'USER'

    const wrapper = mountBody()

    expect(adminMenu(wrapper).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Data Training')
  })

  it('opening Data Training sets the view and tells the shell to close', async () => {
    useAuth().role.value = 'ADMIN'
    const { view } = useView()
    const wrapper = mountBody()

    const item = wrapper.findAll('nav[aria-label="Menu admin"] button')[0]
    await item.trigger('click')

    expect(view.value).toBe('admin/knowledge')
    expect(window.location.hash).toBe('#/admin/knowledge')
    expect(wrapper.emitted('openView')?.[0]).toEqual(['admin/knowledge'])
  })

  it('marks the item for the current view as current, and only that one', async () => {
    useAuth().role.value = 'ADMIN'
    const { view } = useView()
    view.value = 'admin/logs'
    const wrapper = mountBody()

    const current = wrapper.findAll('nav[aria-label="Menu admin"] button[aria-current="page"]')

    expect(current).toHaveLength(1)
    expect(current[0].text()).toContain('Log Aktivitas')
  })
})
