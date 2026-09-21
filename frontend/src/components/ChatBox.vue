<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

import { useChat } from '../composables/useChat'
import MessageBubble from './MessageBubble.vue'
import UploadButton from './UploadButton.vue'

const { messages, input, pendingImage, isLoading, error, send, attach, loadHistory } = useChat()
const scrollRef = ref<HTMLElement | null>(null)

onMounted(loadHistory)

watch(
  () => messages.value.length,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  },
)
</script>

<template>
  <div class="mx-auto flex h-screen max-w-3xl flex-col bg-slate-50">
    <header class="border-b border-slate-200 bg-white px-6 py-4">
      <h1 class="text-base font-semibold text-slate-800">Agentic RAG Assistant</h1>
      <p class="text-xs text-slate-500">RAG · OCR · SQL — berjalan lokal</p>
    </header>

    <main ref="scrollRef" class="flex-1 space-y-3 overflow-y-auto px-6 py-4">
      <p v-if="!messages.length" class="pt-10 text-center text-sm text-slate-400">
        Tanyakan sesuatu, atau lampirkan dokumen/gambar untuk dianalisis.
      </p>
      <MessageBubble v-for="(message, index) in messages" :key="index" :message="message" />
      <div v-if="isLoading" class="flex justify-start">
        <div class="rounded-2xl bg-white px-4 py-3 text-sm text-slate-400 ring-1 ring-slate-200">
          <span class="inline-block animate-pulse">Sedang berpikir…</span>
        </div>
      </div>
    </main>

    <p v-if="error" class="mx-6 mb-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
      {{ error }}
    </p>
    <p v-if="pendingImage" class="mx-6 mb-2 text-xs text-slate-500">
      Gambar terlampir: <span class="font-mono">{{ pendingImage }}</span>
    </p>

    <footer class="flex items-center gap-2 border-t border-slate-200 bg-white px-4 py-3">
      <UploadButton :disabled="isLoading" @file="attach" />
      <input
        v-model="input"
        type="text"
        placeholder="Tulis pertanyaan…"
        class="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
        @keyup.enter="send"
      />
      <button
        class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        :disabled="isLoading || !input.trim()"
        @click="send"
      >
        Send
      </button>
    </footer>
  </div>
</template>
