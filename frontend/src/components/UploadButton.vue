<script setup lang="ts">
import { ref } from 'vue'

import AppIcon from './AppIcon.vue'

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ files: [File[]] }>()

const inputRef = ref<HTMLInputElement | null>(null)

function onChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files ?? [])
  if (files.length > 0) emit('files', files)
  target.value = '' // allow re-selecting the same file
}
</script>

<template>
  <button
    type="button"
    class="grid h-11 w-11 shrink-0 cursor-pointer place-items-center rounded-xl text-subtle transition-colors duration-200 hover:bg-elevated hover:text-fg disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-subtle"
    :disabled="disabled"
    aria-label="Lampirkan gambar atau dokumen"
    title="Lampirkan gambar atau dokumen"
    @click="inputRef?.click()"
  >
    <AppIcon name="paperclip" :size="18" />
    <input
      ref="inputRef"
      type="file"
      multiple
      class="hidden"
      accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md"
      @change="onChange"
    />
  </button>
</template>
