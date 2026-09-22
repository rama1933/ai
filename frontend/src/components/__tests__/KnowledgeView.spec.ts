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

    // By its label, not by `button[aria-expanded]`: the source toggles carry that
    // attribute too, and they come first in the DOM.
    const rowToggle = wrapper.findAll('button').find((b) => b.text().includes(ROW.display_name))
    await rowToggle?.trigger('click')
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

  it('ingests pasted text through the text panel', async () => {
    const spy = vi.spyOn(api, 'ingestText').mockResolvedValue({ filename: 'x-sp2.txt', chunks: 1 })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('#knowledge-text-body').exists()).toBe(false)
    await wrapper.find('button[aria-controls="knowledge-text-panel"]').trigger('click')

    await wrapper.find('#knowledge-text-title').setValue('Kebijakan cuti')
    await wrapper.find('#knowledge-text-body').setValue('  cuti tahunan 12 hari  ')
    await wrapper.find('#knowledge-text-panel').trigger('submit')
    await flushPromises()

    expect(spy).toHaveBeenCalledWith({ content: 'cuti tahunan 12 hari', title: 'Kebijakan cuti' })
    expect(wrapper.find('#knowledge-text-panel').exists()).toBe(false) // panel closes on success
    expect(api.admin.listDocuments).toHaveBeenCalledTimes(2) // the table refreshes
  })

  it('sends a URL to the backend rather than fetching it here', async () => {
    const spy = vi.spyOn(api, 'ingestUrl').mockResolvedValue({ filename: 'x-kebijakan.txt', chunks: 2 })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button[aria-controls="knowledge-url-panel"]').trigger('click')
    await wrapper.find('#knowledge-url').setValue(' https://contoh.id/kebijakan ')
    await wrapper.find('#knowledge-url-panel').trigger('submit')
    await flushPromises()

    expect(spy).toHaveBeenCalledWith({ url: 'https://contoh.id/kebijakan', title: undefined })
    expect(wrapper.find('#knowledge-url-panel').exists()).toBe(false)
  })

  it('keeps the draft when the server refuses it', async () => {
    vi.spyOn(api, 'ingestUrl').mockRejectedValue(new Error('file:// is not a readable page'))
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button[aria-controls="knowledge-url-panel"]').trigger('click')
    await wrapper.find('#knowledge-url').setValue('https://contoh.id/x')
    await wrapper.find('#knowledge-url-panel').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('not a readable page')
    expect(wrapper.find('#knowledge-url-panel').exists()).toBe(true)
    expect((wrapper.find('#knowledge-url').element as HTMLInputElement).value).toBe('https://contoh.id/x')
  })

  it('refuses to submit an empty draft', async () => {
    const spy = vi.spyOn(api, 'ingestText').mockResolvedValue({ filename: 'x.txt', chunks: 1 })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button[aria-controls="knowledge-text-panel"]').trigger('click')
    await wrapper.find('#knowledge-text-body').setValue('   ')
    await wrapper.find('#knowledge-text-panel').trigger('submit')
    await flushPromises()

    expect(spy).not.toHaveBeenCalled()
  })
})
