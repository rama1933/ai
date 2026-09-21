<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from './AppIcon.vue'

/**
 * One attachment chip. Pending chips preview from the local File; message
 * chips preview from an authed blob URL -- the caller decides what `src` is.
 */
const props = withDefaults(
  defineProps<{
    name: string
    kind?: 'image' | 'document'
    mime?: string
    size?: number
    src?: string | null
    error?: string | null
    uploading?: boolean
    removable?: boolean
  }>(),
  { kind: 'document', mime: '', size: undefined, src: null, error: null, uploading: false, removable: false },
)
const emit = defineEmits<{ remove: [] }>()

const isImage = computed(() => props.kind === 'image' || props.mime.startsWith('image/'))

const extension = computed(() => {
  const match = /\.([A-Za-z0-9]+)$/.exec(props.name)
  return match ? match[1].toUpperCase() : 'FILE'
})

const sizeLabel = computed(() => {
  if (props.size === undefined) return ''
  if (props.size < 1024) return `${props.size} B`
  if (props.size < 1024 * 1024) return `${(props.size / 1024).toFixed(0)} KB`
  return `${(props.size / (1024 * 1024)).toFixed(1)} MB`
})

/**
 * Middle truncation: `laporan-anggaran-2026-final.pdf` reads better as
 * `laporan-a…final.pdf` than as a cut-off head, because extensions and
 * trailing dates carry the meaning.
 */
const displayName = computed(() => middleTruncate(props.name, 24))

function middleTruncate(name: string, max: number): string {
  if (name.length <= max) return name
  const head = Math.ceil((max - 1) / 2)
  const tail = Math.floor((max - 1) / 2)
  return `${name.slice(0, head)}…${name.slice(name.length - tail)}`
}
</script>

<template>
  <div
    class="group relative inline-flex max-w-[15rem] items-center gap-2 rounded-xl border bg-elevated px-2 py-1.5"
    :class="error ? 'border-danger/40 bg-danger-soft' : 'border-border'"
    :title="error ?? name"
  >
    <div
      v-if="isImage && src"
      class="h-9 w-9 shrink-0 overflow-hidden rounded-lg bg-bg ring-1 ring-border"
    >
      <img :src="src" :alt="name" class="h-full w-full object-cover" />
    </div>
    <div
      v-else
      class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[10px] font-semibold tracking-wide"
      :class="error ? 'bg-danger/10 text-danger' : 'bg-bg text-subtle ring-1 ring-border'"
    >
      <AppIcon v-if="!isImage" name="file" :size="15" />
      <span v-else>{{ extension.slice(0, 4) }}</span>
    </div>

    <div class="min-w-0 leading-tight">
      <p class="truncate text-xs font-medium" :class="error ? 'text-danger' : 'text-fg'">
        {{ displayName }}
      </p>
      <p v-if="uploading" class="text-[10px] text-faint">mengunggah…</p>
      <p v-else-if="error" class="truncate text-[10px] text-danger">{{ error }}</p>
      <p v-else-if="sizeLabel" class="text-[10px] text-faint">{{ sizeLabel }} · {{ extension }}</p>
    </div>

    <button
      v-if="removable"
      type="button"
      class="grid h-5 w-5 shrink-0 cursor-pointer place-items-center rounded-md text-faint transition-colors hover:bg-bg hover:text-danger"
      aria-label="Hapus lampiran"
      title="Hapus lampiran"
      @click="emit('remove')"
    >
      <AppIcon name="close" :size="12" />
    </button>
  </div>
</template>
