<script setup lang="ts">
import { useClipboard } from '@vueuse/core'

import AppIcon from './AppIcon.vue'

/**
 * Per-message actions. The row appears on hover and on keyboard focus-within
 * -- hover-only is unreachable by touch and by keyboard -- and copy binds the
 * "Tersalin" state to useClipboard's own ref.
 */
const props = withDefaults(
  defineProps<{
    text: string
    role: 'user' | 'assistant'
    /** Optimistic messages carry no row id yet: turn-level actions wait. */
    disabled?: boolean
  }>(),
  { disabled: false },
)
const emit = defineEmits<{ regenerate: []; edit: [] }>()

const { copy, copied } = useClipboard({ copiedDuring: 1500 })
</script>

<template>
  <div
    class="flex items-center gap-0.5 opacity-0 transition-opacity duration-150 group-hover/bubble:opacity-100 focus-within:opacity-100"
  >
    <button
      type="button"
      class="flex cursor-pointer items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-faint transition-colors hover:bg-elevated hover:text-fg"
      :aria-label="copied ? 'Tersalin' : 'Salin pesan'"
      @click="copy(props.text)"
    >
      <AppIcon name="copy" :size="13" />
      {{ copied ? 'Tersalin' : 'Salin' }}
    </button>

    <button
      v-if="props.role === 'assistant'"
      type="button"
      class="flex cursor-pointer items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-faint transition-colors hover:bg-elevated hover:text-fg disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
      :disabled="props.disabled"
      aria-label="Regenerasi jawaban"
      @click="emit('regenerate')"
    >
      <AppIcon name="sparkle" :size="13" />
      Regenerasi
    </button>

    <button
      v-if="props.role === 'user'"
      type="button"
      class="flex cursor-pointer items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-faint transition-colors hover:bg-elevated hover:text-fg disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
      :disabled="props.disabled"
      aria-label="Edit pesan"
      @click="emit('edit')"
    >
      <AppIcon name="pencil" :size="13" />
      Edit
    </button>
  </div>
</template>
