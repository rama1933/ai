<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from 'reka-ui'

import { useSessions } from '../composables/useSessions'
import AppIcon from './AppIcon.vue'

/**
 * The rail's inner panel: new-conversation button, title filter, and the
 * grouped list. Shared by the permanent rail and the mobile drawer, so this
 * component owns no shell chrome of its own.
 */
const emit = defineEmits<{
  new: []
  selectRow: [id: string]
  saveRename: [id: string, title: string]
  deleteRequest: [id: string]
}>()

const { sessions, activeId, isLoading, error } = useSessions()

const filter = ref('')
const editingId = ref<string | null>(null)
const editTitle = ref('')
const renameInput = ref<HTMLInputElement | HTMLInputElement[] | null>(null)

const GROUPS = [
  { key: 'today', label: 'Hari ini' },
  { key: 'week', label: '7 hari terakhir' },
  { key: 'older', label: 'Lebih lama' },
] as const

const groups = computed(() => {
  const query = filter.value.trim().toLowerCase()
  const visible = query
    ? sessions.value.filter((s) => (s.title ?? '').toLowerCase().includes(query))
    : sessions.value

  const startOfToday = new Date()
  startOfToday.setHours(0, 0, 0, 0)
  const weekStart = startOfToday.getTime() - 7 * 86_400_000

  const buckets: Record<(typeof GROUPS)[number]['key'], typeof visible> = { today: [], week: [], older: [] }
  for (const session of visible) {
    const at = new Date(session.updated_at).getTime()
    if (at >= startOfToday.getTime()) buckets.today.push(session)
    else if (at >= weekStart) buckets.week.push(session)
    else buckets.older.push(session)
  }
  return GROUPS.map((group) => ({ ...group, items: buckets[group.key] })).filter((g) => g.items.length > 0)
})

function titleOf(id: string): string {
  return sessions.value.find((s) => s.id === id)?.title ?? ''
}

async function startRename(id: string): Promise<void> {
  editingId.value = id
  editTitle.value = titleOf(id)
  await nextTick()
  // Only one row edits at a time, but the ref sits inside a v-for, where Vue
  // collects an array.
  const el = Array.isArray(renameInput.value) ? renameInput.value[0] : renameInput.value
  el?.focus()
  el?.select()
}

function onRenameKeydown(event: KeyboardEvent, id: string): void {
  if (event.key === 'Enter') {
    event.preventDefault()
    emit('saveRename', id, editTitle.value)
    editingId.value = null // the blur handler then no-ops
  } else if (event.key === 'Escape') {
    editingId.value = null
  }
}

function onBlurRename(id: string): void {
  if (editingId.value !== id) return // Enter already saved it
  emit('saveRename', id, editTitle.value)
  editingId.value = null
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div class="flex flex-col gap-2.5 p-3">
      <button
        type="button"
        class="flex cursor-pointer items-center gap-2 rounded-xl border border-border-strong bg-elevated px-3 py-2.5 text-sm font-medium text-fg shadow-sm transition-all duration-200 hover:border-primary/80 hover:shadow-card"
        @click="emit('new')"
      >
        <AppIcon name="plus" :size="16" />
        Percakapan baru
      </button>

      <div class="relative">
        <AppIcon name="search" :size="14" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
        <label class="sr-only" for="session-filter">Cari percakapan</label>
        <input
          id="session-filter"
          v-model="filter"
          type="search"
          placeholder="Cari percakapan…"
          class="w-full rounded-xl border border-border bg-bg py-2 pl-8 pr-3 text-xs text-fg placeholder:text-faint focus:border-primary/80 focus:outline-none"
        />
      </div>
    </div>

    <p
      v-if="error"
      class="mx-3 mb-2 rounded-xl bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger ring-1 ring-danger/20"
      role="alert"
    >
      {{ error }}
    </p>

    <nav v-if="groups.length > 0" class="min-h-0 flex-1 overflow-y-auto px-3 pb-3" aria-label="Percakapan">
      <template v-for="group in groups" :key="group.key">
        <p class="px-2 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-faint">
          {{ group.label }}
        </p>
        <ul class="flex flex-col gap-0.5">
          <li v-for="session in group.items" :key="session.id" class="relative">
            <div
              class="group flex items-center rounded-xl transition-colors duration-150"
              :class="session.id === activeId ? 'bg-elevated' : 'hover:bg-elevated/60'"
            >
              <template v-if="editingId === session.id">
                <input
                  ref="renameInput"
                  v-model="editTitle"
                  type="text"
                  maxlength="200"
                  class="w-full rounded-xl border border-primary/80 bg-bg px-3 py-2 text-sm text-fg focus:outline-none"
                  :aria-label="`Nama baru untuk ${titleOf(session.id) || 'percakapan'}`"
                  @keydown="onRenameKeydown($event, session.id)"
                  @blur="onBlurRename(session.id)"
                />
              </template>
              <template v-else>
                <button
                  type="button"
                  class="flex min-w-0 flex-1 cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm"
                  :class="session.id === activeId ? 'text-fg' : 'text-subtle'"
                  :aria-current="session.id === activeId ? 'page' : undefined"
                  @click="emit('selectRow', session.id)"
                >
                  <AppIcon
                    name="message"
                    :size="14"
                    :class="session.id === activeId ? 'text-primary' : 'text-faint'"
                  />
                  <span class="truncate">{{ session.title || 'Tanpa judul' }}</span>
                </button>

                <DropdownMenuRoot>
                  <DropdownMenuTrigger
                    class="mr-1.5 grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-lg text-faint opacity-0 transition-all duration-150 hover:bg-bg hover:text-fg focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
                    aria-label="Menu percakapan"
                  >
                    <AppIcon name="more" :size="15" />
                  </DropdownMenuTrigger>
                  <DropdownMenuPortal>
                    <DropdownMenuContent
                      align="end"
                      :side-offset="4"
                      class="z-[60] min-w-[10rem] rounded-xl border border-border bg-surface p-1 shadow-xl"
                    >
                      <DropdownMenuItem
                        class="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-subtle outline-none transition-colors data-[highlighted]:bg-elevated data-[highlighted]:text-fg"
                        @select="startRename(session.id)"
                      >
                        <AppIcon name="pencil" :size="13" />
                        Ganti nama
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        class="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-danger outline-none transition-colors data-[highlighted]:bg-danger-soft"
                        @select="emit('deleteRequest', session.id)"
                      >
                        <AppIcon name="trash" :size="13" />
                        Hapus
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenuPortal>
                </DropdownMenuRoot>
              </template>
            </div>
          </li>
        </ul>
      </template>
    </nav>

    <div v-else class="flex min-h-0 flex-1 items-center justify-center px-6 pb-6">
      <p class="text-center text-xs leading-relaxed text-faint">
        {{
          isLoading
            ? 'Memuat percakapan…'
            : filter.trim()
              ? 'Tidak ada percakapan yang cocok.'
              : 'Belum ada percakapan. Mulai satu dengan tombol di atas.'
        }}
      </p>
    </div>
  </div>
</template>
