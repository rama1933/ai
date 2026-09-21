import { ref, watchEffect } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'agentic-rag-theme'

function stored(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null // private mode / storage disabled — fall back to the OS setting
  }
}

function preferred(): Theme {
  const saved = stored()
  if (saved) return saved
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const theme = ref<Theme>(preferred())

/**
 * Keep the browser chrome in step with the in-app theme. A meta tag cannot read
 * a CSS variable, so resolve the token here rather than pasting its value into
 * index.html where it would silently drift from the palette.
 */
function syncThemeColor(): void {
  const meta = document.querySelector('meta[name="theme-color"]')
  if (!meta) return
  const token = theme.value === 'dark' ? '--c-bg' : '--c-primary'
  const channels = getComputedStyle(document.documentElement)
    .getPropertyValue(token)
    .trim()
    .split(/\s+/)
  if (channels.length !== 3) return // no stylesheet resolved (e.g. jsdom) — leave the default
  const hex = channels.map((c) => Number(c).toString(16).padStart(2, '0')).join('')
  meta.setAttribute('content', `#${hex}`)
}

// Single writer: the class on <html> and the stored value can never disagree.
watchEffect(() => {
  document.documentElement.classList.toggle('dark', theme.value === 'dark')
  try {
    localStorage.setItem(STORAGE_KEY, theme.value)
  } catch {
    // a failed write only costs the preference, never the current render
  }
  syncThemeColor()
})

export function useTheme() {
  return {
    theme,
    toggle: () => {
      theme.value = theme.value === 'dark' ? 'light' : 'dark'
    },
  }
}
