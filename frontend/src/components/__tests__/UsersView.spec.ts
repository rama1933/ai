import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import UsersView from '../admin/UsersView.vue'
import { useAuth } from '../../composables/useAuth'
import { api, type AdminUserItem } from '../../services/api'

const ME: AdminUserItem = {
  id: 1,
  username: 'admin',
  role: 'ADMIN',
  is_active: true,
  created_at: '2026-09-01T10:00:00Z',
  sessions: 3,
  documents: 2,
}

const OTHER: AdminUserItem = {
  id: 2,
  username: 'budi',
  role: 'USER',
  is_active: true,
  created_at: '2026-09-02T10:00:00Z',
  sessions: 0,
  documents: 0,
}

function rowFor(wrapper: ReturnType<typeof mount>, username: string) {
  return wrapper.findAll('tbody tr').find((tr) => tr.text().includes(username))
}

describe('UsersView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuth().username.value = 'admin'
    vi.spyOn(api.admin, 'listUsers').mockResolvedValue([ME, OTHER])
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders a row per account', async () => {
    const wrapper = mount(UsersView)
    await flushPromises()

    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('budi')
    expect(rowFor(wrapper, 'budi')?.text()).toContain('USER')
  })

  it('disables the destructive controls on the signed-in admin own row', async () => {
    const wrapper = mount(UsersView)
    await flushPromises()

    const mine = rowFor(wrapper, 'admin')
    const theirs = rowFor(wrapper, 'budi')

    expect(mine?.find('select[disabled]').exists()).toBe(true)
    expect(mine?.find('button[disabled]').exists()).toBe(true)
    expect(mine?.find('button[title]').attributes('title')).toContain('sendiri')
    // The same controls stay live on somebody else's row.
    expect(theirs?.find('select[disabled]').exists()).toBe(false)
    expect(theirs?.find('button[disabled]').exists()).toBe(false)
  })

  it('creating a user calls the API and shows the new row', async () => {
    const created = { ...OTHER, id: 9, username: 'sari' }
    const createSpy = vi.spyOn(api.admin, 'createUser').mockResolvedValue(created)
    const wrapper = mount(UsersView)
    await flushPromises()

    await wrapper.find('#new-username').setValue('sari')
    await wrapper.find('#new-password').setValue('supersecret1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createSpy).toHaveBeenCalledWith({ username: 'sari', password: 'supersecret1', role: 'USER' })
    expect(wrapper.text()).toContain('sari')
    expect(wrapper.text()).toContain('ditambahkan')
  })

  it('surfaces a duplicate username as something readable', async () => {
    vi.spyOn(api.admin, 'createUser').mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: 'username already exists' } },
    })
    const wrapper = mount(UsersView)
    await flushPromises()

    await wrapper.find('#new-username').setValue('budi')
    await wrapper.find('#new-password').setValue('supersecret1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('username already exists')
  })

  it('explains a rejected role change instead of silently snapping back', async () => {
    // The reload that restores the select clears the banner on entry, so the message
    // has to be re-set after it -- otherwise the change just undoes itself.
    vi.spyOn(api.admin, 'updateUser').mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { detail: 'the last active admin cannot be demoted' } },
    })
    const wrapper = mount(UsersView)
    await flushPromises()

    await rowFor(wrapper, 'budi')?.find('select').setValue('ADMIN')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('last active admin')
    expect(rowFor(wrapper, 'budi')?.find('select').element.value).toBe('USER')
  })

  it('toggles activation through the API', async () => {
    const updateSpy = vi
      .spyOn(api.admin, 'updateUser')
      .mockResolvedValue({ ...OTHER, is_active: false })
    const wrapper = mount(UsersView)
    await flushPromises()

    const toggle = rowFor(wrapper, 'budi')?.findAll('button')[0]
    await toggle?.trigger('click')
    await flushPromises()

    expect(updateSpy).toHaveBeenCalledWith(OTHER.id, { is_active: false })
    expect(rowFor(wrapper, 'budi')?.text()).toContain('Nonaktif')
  })

  it('deletes through the confirmation dialog', async () => {
    const deleteSpy = vi.spyOn(api.admin, 'deleteUser').mockResolvedValue(undefined)
    const wrapper = mount(UsersView, { attachTo: document.body })
    await flushPromises()

    await rowFor(wrapper, 'budi')?.find('button[aria-label="Hapus budi"]').trigger('click')
    await flushPromises()

    const confirm = [...document.querySelectorAll('button')].find(
      (b) => b.textContent?.trim() === 'Hapus pengguna',
    )
    confirm?.click()
    await flushPromises()

    expect(deleteSpy).toHaveBeenCalledWith(OTHER.id)
    expect(rowFor(wrapper, 'budi')).toBeUndefined()
    expect(wrapper.text()).toContain('budi dihapus')
  })
})
