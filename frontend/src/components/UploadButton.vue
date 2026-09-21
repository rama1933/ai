<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ file: [File] }>()

const inputRef = ref<HTMLInputElement | null>(null)

function onChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) emit('file', file)
  target.value = '' // allow re-selecting the same file
}
</script>

<template>
  <button
    type="button"
    class="rounded-lg px-3 py-2 text-slate-500 hover:bg-slate-100 disabled:opacity-40"
    :disabled="disabled"
    title="Lampirkan gambar atau dokumen"
    @click="inputRef?.click()"
  >
    📎
    <input
      ref="inputRef"
      type="file"
      class="hidden"
      accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md"
      @change="onChange"
    />
  </button>
</template>
