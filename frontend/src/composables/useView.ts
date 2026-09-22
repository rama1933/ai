import { computed, ref } from 'vue'

/**
 * Which screen the app is on, held in `location.hash`.
 *
 * ponytail: a hash switch, not routing -- no vue-router, no path params, no guards.
 * Introduce the router only when a screen needs a parameter in its url or a real
 * navigation guard; until then this is 15 lines and one browser primitive, and the
 * back button works for free.
 */
export const VIEWS = ['chat', 'admin/knowledge', 'admin/logs', 'admin/users'] as const
export type View = (typeof VIEWS)[number]

/** An unknown or absent hash is the chat: it is the screen everybody has. */
export function viewFromHash(hash: string): View {
  const path = hash.replace(/^#\/?/, '')
  return (VIEWS as readonly string[]).includes(path) ? (path as View) : 'chat'
}

// Module-level singleton, the shape useAuth and useSessions already use.
const view = ref<View>(viewFromHash(window.location.hash))

window.addEventListener('hashchange', () => {
  view.value = viewFromHash(window.location.hash)
})

export function useView() {
  /** `replace` for a redirect nobody asked for -- a push there would leave a history
   * entry the back button returns to, only to be bounced off it again. */
  function go(next: View, options: { replace?: boolean } = {}): void {
    view.value = next
    // Assigning the hash is what makes the back button work; the hashchange
    // listener above then writes the same value back into the ref.
    const hash = `#/${next}`
    if (options.replace) window.location.replace(hash)
    else window.location.hash = hash
  }

  const isAdminView = computed(() => view.value.startsWith('admin/'))

  return { view, isAdminView, go }
}
