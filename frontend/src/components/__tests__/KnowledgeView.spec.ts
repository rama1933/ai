import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KnowledgeView from '../admin/KnowledgeView.vue'
import { api, type KnowledgeItem } from '../../services/api'

const ROW: KnowledgeItem = {
  filename: 'abc123-sp2-policy.pdf',
  display_name: 'sp2-policy.pdf',
  chunks: 4,
  chars: 3200,
  owner: 'admin',
  created_at: '2026-09-22T10:00:00Z',
}

function mountView() {
  return mount(KnowledgeView, { attachTo: document.body })
}

/** reka-ui portals the dialog out of the wrapper, so it is found in the document. */
function dialogButton(label: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === label)
}

describe('KnowledgeView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api.admin, 'listDocuments').mockResolvedValue([ROW])
    vi.spyOn(api.admin, 'listChunks').mockResolvedValue([
      { chunk_index: 0, chars: 800, content: 'kebijakan cuti tahunan' },
    ])
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders a row per document the API returns', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('sp2-policy.pdf')
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).not.toContain('Belum ada dokumen')
  })

  it('shows the empty state when there is nothing ingested', async () => {
    vi.spyOn(api.admin, 'listDocuments').mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Belum ada dokumen')
  })

  it('expands a row into its chunks', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button[aria-expanded]').trigger('click')
    await flushPromises()

    expect(api.admin.listChunks).toHaveBeenCalledWith(ROW.filename)
    expect(wrapper.text()).toContain('Chunk 0')
    expect(wrapper.text()).toContain('kebijakan cuti tahunan')
  })

  it('deletes only after the confirmation dialog is accepted', async () => {
    const deleteSpy = vi.spyOn(api.admin, 'deleteDocument').mockResolvedValue(undefined)
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button[aria-label="Hapus sp2-policy.pdf"]').trigger('click')
    await flushPromises()

    expect(dialogButton('Hapus dokumen')).toBeTruthy()
    expect(deleteSpy).not.toHaveBeenCalled()

    dialogButton('Hapus dokumen')?.click()
    await flushPromises()

    expect(deleteSpy).toHaveBeenCalledWith(ROW.filename)
    expect(api.admin.listDocuments).toHaveBeenCalledTimes(2) // the table refreshes
  })

  it('cancelling the dialog deletes nothing', async () => {
    const deleteSpy = vi.spyOn(api.admin, 'deleteDocument').mockResolvedValue(undefined)
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button[aria-label="Hapus sp2-policy.pdf"]').trigger('click')
    await flushPromises()
    dialogButton('Batal')?.click()
    await flushPromises()

    expect(deleteSpy).not.toHaveBeenCalled()
  })

  it('surfaces a failed delete instead of silently refreshing', async () => {
    vi.spyOn(api.admin, 'deleteDocument').mockRejectedValue(new Error('boom'))
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button[aria-label="Hapus sp2-policy.pdf"]').trigger('click')
    await flushPromises()
    dialogButton('Hapus dokumen')?.click()
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('boom')
  })
})
