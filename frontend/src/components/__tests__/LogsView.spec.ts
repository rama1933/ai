import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import LogsView from '../admin/LogsView.vue'
import { api, type LogItem } from '../../services/api'

/** The dialogs are portalled out of the wrapper, so they are read off the document. */
function dialogButton(label: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === label)
}

function setDialogInput(id: string, value: string): void {
  const input = document.querySelector<HTMLInputElement>(`#${id}`)
  if (!input) throw new Error(`no #${id} in the dialog`)
  input.value = value
  input.dispatchEvent(new Event('input'))
}

const LOG: LogItem = {
  id: 3,
  username: 'admin',
  action: 'CHAT_TURN',
  target: 'session-1',
  detail: { tool_used: 'rag_search', duration_ms: 812 },
  created_at: '2026-09-22T10:00:00Z',
}

describe('LogsView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api.admin, 'listLogs').mockResolvedValue([LOG])
    vi.spyOn(api.admin, 'logActions').mockResolvedValue(['AUTH_LOGIN', 'CHAT_TURN'])
    vi.spyOn(api.admin, 'purgeLogs').mockResolvedValue({ deleted: 2 })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders a row per event with its detail as key/value, not raw JSON', async () => {
    const wrapper = mount(LogsView)
    await flushPromises()

    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('CHAT_TURN')
    expect(wrapper.text()).toContain('session-1')
    expect(wrapper.text()).toContain('tool_used')
    expect(wrapper.text()).toContain('rag_search')
  })

  it('offers the actions the log actually contains', async () => {
    const wrapper = mount(LogsView)
    await flushPromises()

    const options = wrapper.findAll('#log-action option').map((o) => o.text())

    expect(options).toEqual(['Semua aksi', 'AUTH_LOGIN', 'CHAT_TURN'])
  })

  it('refetches from the first page when a filter changes', async () => {
    const wrapper = mount(LogsView)
    await flushPromises()

    await wrapper.find('#log-action').setValue('AUTH_LOGIN')
    await flushPromises()

    expect(api.admin.listLogs).toHaveBeenLastCalledWith(
      expect.objectContaining({ action: 'AUTH_LOGIN', offset: 0, limit: 50 }),
    )
  })

  it('sends a date range as whole days, end date included', async () => {
    const wrapper = mount(LogsView)
    await flushPromises()

    await wrapper.find('#log-since').setValue('2026-09-01')
    await wrapper.find('#log-until').setValue('2026-09-22')
    await flushPromises()

    expect(api.admin.listLogs).toHaveBeenLastCalledWith(
      expect.objectContaining({ since: '2026-09-01T00:00:00', until: '2026-09-22T23:59:59' }),
    )
  })

  it('purges only once a date has been given', async () => {
    const wrapper = mount(LogsView, { attachTo: document.body })
    await flushPromises()

    const purgeButton = wrapper.findAll('button').find((b) => b.text().includes('Bersihkan log lama'))
    await purgeButton?.trigger('click')
    await flushPromises()

    // No bare "delete the log": the confirm is inert until a date is set.
    expect(dialogButton('Hapus')?.disabled).toBe(true)
    dialogButton('Hapus')?.click()
    await flushPromises()
    expect(api.admin.purgeLogs).not.toHaveBeenCalled()

    setDialogInput('purge-before', '2026-08-01')
    await flushPromises()
    dialogButton('Hapus')?.click()
    await flushPromises()

    expect(api.admin.purgeLogs).toHaveBeenCalledWith('2026-08-01T00:00:00')
    expect(wrapper.text()).toContain('2 baris log lama dihapus')
  })
})
