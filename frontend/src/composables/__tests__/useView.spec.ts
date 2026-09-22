import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The view is seeded when the module loads, so every case here re-imports it with
 * the hash already set -- the same order a page load uses.
 */
async function freshView(hash: string) {
  window.location.hash = hash
  vi.resetModules()
  const { useView } = await import('../useView')
  return useView()
}

function fireHashChange(): void {
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

describe('useView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('seeds the view from the hash on load', async () => {
    const { view } = await freshView('#/admin/logs')

    expect(view.value).toBe('admin/logs')
  })

  it('falls back to chat for an unknown or absent hash', async () => {
    expect((await freshView('#/admin/nonsense')).view.value).toBe('chat')
    expect((await freshView('')).view.value).toBe('chat')
  })

  it('go writes the hash so the back button has an entry to return to', async () => {
    const { view, go } = await freshView('#/chat')

    go('admin/users')

    expect(view.value).toBe('admin/users')
    expect(window.location.hash).toBe('#/admin/users')
  })

  it('follows the hash when the browser moves it', async () => {
    const { view } = await freshView('#/chat')

    window.location.hash = '#/admin/knowledge'
    fireHashChange()

    expect(view.value).toBe('admin/knowledge')
  })

  it('reports whether the current view is an admin one', async () => {
    const { isAdminView, go } = await freshView('#/chat')
    expect(isAdminView.value).toBe(false)

    go('admin/logs')
    expect(isAdminView.value).toBe(true)
  })
})
