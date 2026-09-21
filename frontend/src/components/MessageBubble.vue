<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'

import type { ChatMessage } from '../composables/useChat'

const props = defineProps<{ message: ChatMessage }>()

const md = new MarkdownIt({ linkify: true, breaks: true })

// Model output is untrusted HTML once rendered; sanitize before v-html.
const rendered = computed(() => DOMPurify.sanitize(md.render(props.message.content)))
const isUser = computed(() => props.message.role === 'user')
</script>

<template>
  <div class="flex" :class="isUser ? 'justify-end' : 'justify-start'">
    <div
      class="max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm"
      :class="isUser ? 'bg-blue-600 text-white' : 'bg-white text-slate-800 ring-1 ring-slate-200'"
    >
      <div class="prose prose-sm max-w-none" v-html="rendered" />

      <div v-if="message.toolUsed" class="mt-2 text-xs opacity-70">
        tool: <span class="font-mono">{{ message.toolUsed }}</span>
      </div>

      <ul v-if="message.sources?.length" class="mt-1 space-y-0.5 text-xs opacity-70">
        <li v-for="source in message.sources" :key="source.filename">
          source: {{ source.filename }}
          <span v-if="source.score !== null">({{ source.score }})</span>
        </li>
      </ul>
    </div>
  </div>
</template>
