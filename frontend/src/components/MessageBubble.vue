<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed, onMounted, ref } from 'vue'
import { DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'

import type { AttachmentRef } from '../services/api'
import type { ChatMessage } from '../composables/useChat'
import { useAttachments } from '../composables/useAttachments'
import AppIcon from './AppIcon.vue'
import AttachmentChip from './AttachmentChip.vue'

const props = defineProps<{ message: ChatMessage }>()

const { objectUrl } = useAttachments()

const md = new MarkdownIt({ linkify: true, breaks: true })

// Model output is untrusted HTML once rendered; sanitize before v-html.
const rendered = computed(() => DOMPurify.sanitize(md.render(props.message.content)))
const isUser = computed(() => props.message.role === 'user')

const attachments = computed(() => props.message.attachments ?? [])
const imageAttachments = computed(() => attachments.value.filter((a) => a.kind === 'image'))
const documentAttachments = computed(() => attachments.value.filter((a) => a.kind !== 'image'))

// Thumbnails need an authed blob URL, fetched once per attachment -- but only
// when there is no local preview: an optimistic bubble shows its own File and
// the server row does not exist yet to serve the real one.
const thumbs = ref<Record<string, string | null>>({})
onMounted(async () => {
  for (const attachment of imageAttachments.value) {
    if (attachment.previewUrl) continue
    thumbs.value[attachment.stored_name] = await objectUrl(attachment.stored_name)
  }
})

function thumbFor(attachment: AttachmentRef): string | null {
  return attachment.previewUrl ?? thumbs.value[attachment.stored_name] ?? null
}

// Full-size preview in a Dialog the library manages (focus trap, Esc).
const previewing = ref<string | null>(null)
const previewUrl = computed(() => (previewing.value ? (thumbs.value[previewing.value] ?? null) : null))
const previewName = computed(() =>
  previewing.value ? (attachments.value.find((a) => a.stored_name === previewing.value)?.display_name ?? '') : '',
)

async function download(attachment: AttachmentRef): Promise<void> {
  const url = await objectUrl(attachment.stored_name)
  if (!url) return
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = attachment.display_name
  anchor.click()
}

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
      <div v-if="imageAttachments.length" class="flex flex-wrap gap-2">
        <button
          v-for="attachment in imageAttachments"
          :key="attachment.stored_name"
          type="button"
          class="group relative h-20 w-20 cursor-zoom-in overflow-hidden rounded-xl bg-bg ring-1 ring-border transition-shadow hover:shadow-card"
          :aria-label="`Lihat ${attachment.display_name}`"
          :title="attachment.display_name"
          @click="previewing = attachment.stored_name"
        >
          <img
            v-if="thumbFor(attachment)"
            :src="thumbFor(attachment)!"
            :alt="attachment.display_name"
            class="h-full w-full object-cover"
          />
          <div v-else class="grid h-full w-full place-items-center text-faint">
            <AppIcon name="image" :size="18" />
          </div>
        </button>
      </div>

      <div
        v-if="documentAttachments.length"
        class="flex flex-wrap gap-1.5"
        :class="isUser ? 'justify-end' : ''"
      >
        <AttachmentChip
          v-for="attachment in documentAttachments"
          :key="attachment.stored_name"
          :name="attachment.display_name"
          kind="document"
          :mime="attachment.mime"
          :size="attachment.size"
          class="cursor-pointer transition-colors hover:border-primary/60"
          @click="download(attachment)"
        />
      </div>

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

    <DialogRoot :open="previewing !== null" @update:open="(v) => (previewing = v ? previewing : null)">
      <DialogPortal>
        <DialogOverlay class="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm" />
        <DialogContent
          class="fixed left-1/2 top-1/2 z-[70] max-h-[90vh] max-w-[90vw] -translate-x-1/2 -translate-y-1/2 focus:outline-none"
        >
          <DialogTitle class="sr-only">{{ previewName }}</DialogTitle>
          <img
            v-if="previewUrl"
            :src="previewUrl"
            :alt="previewName"
            class="max-h-[90vh] max-w-[90vw] rounded-xl object-contain shadow-2xl"
          />
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  </div>
</template>
