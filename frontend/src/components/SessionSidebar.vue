<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'

import { useSessions } from '../composables/useSessions'
import type { View } from '../composables/useView'
import SessionSidebarBody from './SessionSidebarBody.vue'

/**
 * The conversation rail. `rail` is the permanent >= lg column; `drawer` wraps
 * the same body in a reka Dialog below that, so focus trapping, focus restore
 * and Esc come from the library rather than being hand-written. The body --
 * new button, filter, list, row menus -- is shared by both shells.
 */
const props = defineProps<{ variant: 'rail' | 'drawer'; open?: boolean }>()
const emit = defineEmits<{ navigate: []; openView: [view: View]; close: [] }>()

const { sessions, activeId, create, rename, remove, select } = useSessions()

const deleteOpen = ref(false)
const pendingId = ref<string | null>(null)

// Dismissal (Esc, overlay) only closes; the id is cleared from the watcher,
// which runs after the synchronous click stack, so confirmDelete always reads
// the id even when the action button's own close fires first.
watch(deleteOpen, (open) => {
  if (!open) pendingId.value = null
})

function titleOf(id: string): string {
  return sessions.value.find((s) => s.id === id)?.title ?? ''
}

async function onNew(): Promise<void> {
  await create() // a failure surfaces through useSessions' error ref in the body
  emit('navigate')
}

function onSelect(id: string): void {
  if (id === activeId.value) {
    emit('close')
    return
  }
  select(id)
  emit('navigate')
}

async function onSaveRename(id: string, title: string): Promise<void> {
  const trimmed = title.trim()
  if (!trimmed || trimmed === titleOf(id)) return
  await rename(id, trimmed)
}

async function onConfirmDelete(): Promise<void> {
  const id = pendingId.value
  deleteOpen.value = false
  if (!id) return
  const wasActive = id === activeId.value
  await remove(id)
  if (wasActive) emit('navigate') // reload the conversation that became active
}
</script>

<template>
  <!-- Rail: the permanent column, >= lg. -->
  <aside
    v-if="props.variant === 'rail'"
    class="hidden w-72 shrink-0 flex-col border-r border-border bg-rail lg:flex"
  >
    <SessionSidebarBody
      @new="onNew"
      @select-row="onSelect"
      @save-rename="onSaveRename"
      @open-view="(view: View) => emit('openView', view)"
      @delete-request="(id) => ((pendingId = id), (deleteOpen = true))"
    />
  </aside>

  <!-- Drawer: the same body below lg, in a Dialog the library manages. -->
  <DialogRoot v-else :open="props.open" @update:open="(v) => (v ? null : emit('close'))">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" />
      <DialogContent
        class="fixed inset-y-0 left-0 z-50 flex w-80 max-w-[85vw] flex-col border-r border-border bg-rail shadow-2xl focus:outline-none"
      >
        <DialogTitle class="sr-only">Daftar percakapan</DialogTitle>
        <DialogDescription class="sr-only">Pilih, ganti nama, atau hapus percakapan Anda.</DialogDescription>
        <SessionSidebarBody
          @new="onNew"
          @select-row="onSelect"
          @save-rename="onSaveRename"
          @open-view="(view: View) => emit('openView', view)"
          @delete-request="(id) => ((pendingId = id), (deleteOpen = true))"
        />
      </DialogContent>
    </DialogPortal>
  </DialogRoot>

  <!-- Delete confirmation. Never window.confirm: a native modal blocks the page. -->
  <AlertDialogRoot :open="deleteOpen" @update:open="(v) => (deleteOpen = v)">
    <AlertDialogPortal>
      <AlertDialogOverlay class="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm" />
      <AlertDialogContent
        class="fixed left-1/2 top-1/2 z-[70] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-border bg-surface p-5 shadow-2xl focus:outline-none"
      >
        <AlertDialogTitle class="font-display text-base font-semibold text-fg">
          Hapus percakapan?
        </AlertDialogTitle>
        <AlertDialogDescription class="mt-1.5 break-words text-sm leading-relaxed text-subtle">
          “{{ pendingId ? (titleOf(pendingId) || 'Tanpa judul').slice(0, 80) : '' }}” akan dihapus beserta
          seluruh isi pesannya. Tindakan ini tidak bisa dibatalkan.
        </AlertDialogDescription>
        <div class="mt-4 flex justify-end gap-2">
          <AlertDialogCancel
            class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3.5 py-2 text-sm text-subtle transition-colors hover:bg-elevated hover:text-fg"
          >
            Batal
          </AlertDialogCancel>
          <AlertDialogAction
            class="cursor-pointer rounded-xl bg-danger px-3.5 py-2 text-sm font-medium text-white transition-all hover:brightness-110 active:scale-[0.98]"
            @click="onConfirmDelete"
          >
            Hapus
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
