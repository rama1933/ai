<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useAuth } from '../../composables/useAuth'
import { useView, type View } from '../../composables/useView'
import { api, describeError, type AdminStats } from '../../services/api'
import AppIcon from '../AppIcon.vue'
import SessionSidebar from '../SessionSidebar.vue'
import ThemeToggle from '../ThemeToggle.vue'

/**
 * The console shell: the same conversation rail ChatBox has, plus a header and the
 * three tabs. The active view arrives through the slot, so this component owns no
 * screen's behaviour.
 *
 * Reached only by an ADMIN; App.vue sends everyone else back to the chat, and the
 * API's 403 is the real boundary.
 */
const { view, go } = useView()
const { username, logout } = useAuth()

const TABS: { view: View; label: string; icon: 'database' | 'history' | 'user' }[] = [
  { view: 'admin/knowledge', label: 'Data Training', icon: 'database' },
  { view: 'admin/logs', label: 'Log Aktivitas', icon: 'history' },
  { view: 'admin/users', label: 'Pengguna', icon: 'user' },
]

const stats = ref<AdminStats | null>(null)
const statsError = ref<string | null>(null)
const drawerOpen = ref(false)

onMounted(async () => {
  try {
    stats.value = await api.admin.stats()
  } catch (err) {
    // The header is decoration; a failed summary must not blank the screen. It does
    // have to say so, though -- silently falling back to the username reads as
    // "nothing to report" rather than "this did not load". The view below reports
    // its own errors through describeError.
    statsError.value = describeError(err)
  }
})

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** A conversation picked from inside the console: close the drawer and show it. */
function onSidebarNavigate(): void {
  drawerOpen.value = false
  go('chat')
}
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-bg">
    <SessionSidebar variant="rail" @navigate="onSidebarNavigate" />
    <SessionSidebar
      variant="drawer"
      :open="drawerOpen"
      @close="drawerOpen = false"
      @navigate="onSidebarNavigate"
      @open-view="drawerOpen = false"
    />

    <div class="flex h-dvh min-w-0 flex-1 flex-col bg-bg">
      <header class="border-b border-border bg-surface/80 backdrop-blur-md">
        <div class="mx-auto flex w-full max-w-5xl items-center gap-3 px-4 py-3 sm:px-6">
          <button
            type="button"
            class="grid h-11 w-11 shrink-0 cursor-pointer place-items-center rounded-xl text-subtle transition-colors duration-200 hover:bg-elevated hover:text-fg lg:hidden"
            aria-label="Buka daftar percakapan"
            title="Percakapan"
            @click="drawerOpen = true"
          >
            <AppIcon name="panel" :size="18" />
          </button>

          <div
            class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-primary to-accent-strong text-primary-fg shadow-glow"
            aria-hidden="true"
          >
            <AppIcon name="database" :size="20" />
          </div>

          <div class="min-w-0 flex-1">
            <h1 class="truncate font-display text-[0.9375rem] font-semibold tracking-tight text-fg">
              Konsol Admin
            </h1>
            <p class="truncate text-xs text-subtle">
              <template v-if="stats">
                {{ stats.users }} pengguna ({{ stats.active_users }} aktif) · {{ stats.documents }} dokumen ·
                {{ stats.chunks }} chunk · {{ stats.sessions }} percakapan · {{ stats.messages }} pesan ·
                {{ formatBytes(stats.storage_bytes) }}
              </template>
              <template v-else-if="statsError">
                <span class="text-danger" :title="statsError">Ringkasan tidak tersedia</span> ·
                {{ username ?? '' }}
              </template>
              <template v-else>{{ username ?? '' }}</template>
            </p>
          </div>

          <button
            type="button"
            class="hidden cursor-pointer items-center gap-1.5 rounded-xl border border-border-strong bg-elevated px-3 py-2 text-xs font-medium text-subtle transition-colors hover:text-fg sm:flex"
            @click="go('chat')"
          >
            <AppIcon name="message" :size="14" />
            Kembali ke chat
          </button>

          <ThemeToggle />

          <button
            type="button"
            class="grid h-11 w-11 cursor-pointer place-items-center rounded-xl text-subtle transition-colors duration-200 hover:bg-elevated hover:text-fg"
            aria-label="Keluar"
            title="Keluar"
            @click="logout"
          >
            <AppIcon name="logout" :size="18" />
          </button>
        </div>

        <nav class="mx-auto flex w-full max-w-5xl gap-1 overflow-x-auto px-4 pb-2 sm:px-6" aria-label="Menu admin">
          <button
            v-for="tab in TABS"
            :key="tab.view"
            type="button"
            class="flex shrink-0 cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-sm transition-colors duration-150"
            :class="view === tab.view ? 'bg-elevated text-fg' : 'text-subtle hover:bg-elevated/60'"
            :aria-current="view === tab.view ? 'page' : undefined"
            @click="go(tab.view)"
          >
            <AppIcon :name="tab.icon" :size="15" :class="view === tab.view ? 'text-primary' : 'text-faint'" />
            {{ tab.label }}
          </button>
        </nav>
      </header>

      <main class="flex-1 overflow-y-auto overscroll-contain">
        <div class="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>
