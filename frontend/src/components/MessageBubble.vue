<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed, ref } from 'vue'

import type { ChatMessage } from '../composables/useChat'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ message: ChatMessage }>()

const md = new MarkdownIt({ linkify: true, breaks: true })

// Model output is untrusted HTML once rendered; sanitize before v-html.
const rendered = computed(() => DOMPurify.sanitize(md.render(props.message.content)))
const isUser = computed(() => props.message.role === 'user')

// Which tool ran is the interesting part of an answer here, so it gets a label
// a person can read rather than the raw function name.
const TOOL_META = {
  rag_search: { icon: 'search', label: 'Pencarian dokumen' },
  image_ocr: { icon: 'image', label: 'Baca gambar' },
  sql_query: { icon: 'table', label: 'Query database' },
} as const

const tool = computed(() => {
  const name = props.message.toolUsed
  if (!name) return null
  return TOOL_META[name as keyof typeof TOOL_META] ?? { icon: 'sparkle' as const, label: name }
})

const sources = computed(() => props.message.sources ?? [])

// Retrieval returns four chunks by default. Showing all of them buries the
// answer under source chips, so lead with the strongest and expand on demand.
const VISIBLE_SOURCES = 2
const showAllSources = ref(false)
const visibleSources = computed(() =>
  showAllSources.value ? sources.value : sources.value.slice(0, VISIBLE_SOURCES),
)
const hiddenSourceCount = computed(() => Math.max(0, sources.value.length - VISIBLE_SOURCES))

/** Stored names carry a 32-hex uniqueness prefix the reader does not need. */
function shortName(filename: string): string {
  return filename.replace(/^[0-9a-f]{32}-/, '')
}
</script>

<template>
  <div class="flex animate-fade-up gap-3" :class="isUser ? 'flex-row-reverse' : 'flex-row'">
    <div
      class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full"
      :class="
        isUser
          ? 'bg-elevated text-subtle ring-1 ring-border'
          : 'bg-gradient-to-br from-primary to-accent-strong text-primary-fg shadow-glow'
      "
      aria-hidden="true"
    >
      <AppIcon :name="isUser ? 'user' : 'sparkle'" :size="15" />
    </div>

    <div class="flex min-w-0 max-w-[85%] flex-col gap-2" :class="isUser ? 'items-end' : 'items-start'">
      <div
        class="rounded-bubble px-4 py-3 shadow-card"
        :class="isUser ? 'bg-primary text-primary-fg' : 'bg-surface text-fg ring-1 ring-border'"
      >
        <div class="md-body" v-html="rendered" />
      </div>

      <div v-if="tool || sources.length" class="flex flex-wrap items-center gap-1.5">
        <span
          v-if="tool"
          class="inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-2.5 py-1 text-[11px] font-medium text-fg"
        >
          <AppIcon :name="tool.icon" :size="13" />
          {{ tool.label }}
        </span>

        <span
          v-for="source in visibleSources"
          :key="source.filename"
          class="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] text-subtle"
          :title="source.filename"
        >
          <AppIcon name="file" :size="13" />
          <span class="truncate">{{ shortName(source.filename) }}</span>
          <span v-if="source.score !== null" class="tabular-nums text-faint">
            {{ source.score.toFixed(2) }}
          </span>
        </span>

        <button
          v-if="hiddenSourceCount > 0 && !showAllSources"
          type="button"
          class="cursor-pointer rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] text-subtle transition-colors hover:border-primary/40 hover:text-fg"
          @click="showAllSources = true"
        >
          +{{ hiddenSourceCount }} sumber lain
        </button>
      </div>
    </div>
  </div>
</template>
