<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { useAuth } from '../composables/useAuth'
import { useChat } from '../composables/useChat'
import AppIcon from './AppIcon.vue'
import MessageBubble from './MessageBubble.vue'
import ThemeToggle from './ThemeToggle.vue'
import UploadButton from './UploadButton.vue'

const { messages, input, pendingImage, isLoading, error, send, attach, loadHistory } = useChat()
const { logout } = useAuth()

const scrollRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

// An explicit `behavior` on scrollTo wins over the CSS `scroll-behavior`, so
// the reduced-motion block in style.css cannot reach this call — ask here too.
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

const hasConversation = computed(() => messages.value.length > 0)

const SUGGESTIONS = [
  'Berapa hari cuti tahunan karyawan tetap?',
  'Berapa jumlah baris pada tabel documents?',
  'Halo, perkenalkan dirimu',
]

onMounted(async () => {
  await loadHistory()
  scrollToBottom()
})

/** Only follow the conversation if the reader is already at the bottom. */
function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

function scrollToBottom(): void {
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

watch([() => messages.value.length, isLoading], async () => {
  const el = scrollRef.value
  if (!el) return
  const stick = isNearBottom(el) || isLoading.value
  await nextTick()
  if (stick) el.scrollTo({ top: el.scrollHeight, behavior: reducedMotion.matches ? 'auto' : 'smooth' })
})

// Grow the composer with its content, up to a ceiling, then scroll inside it.
watch(input, async () => {
  await nextTick()
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
})

function onKeydown(event: KeyboardEvent): void {
  // isComposing guards IME input, where Enter commits a candidate rather than sending.
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

function submit(): void {
  if (!input.value.trim() || isLoading.value) return
  void send()
  void nextTick(() => textareaRef.value?.focus())
}

function useSuggestion(text: string): void {
  input.value = text
  void nextTick(() => textareaRef.value?.focus())
}

const canSend = computed(() => input.value.trim().length > 0 && !isLoading.value)
</script>

<template>
  <div class="flex h-dvh flex-col bg-bg">
    <header class="border-b border-border bg-surface/80 backdrop-blur-md">
      <div class="mx-auto flex w-full max-w-3xl items-center gap-3 px-4 py-3 sm:px-6">
        <div
          class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-primary to-accent-strong text-primary-fg shadow-glow"
          aria-hidden="true"
        >
          <AppIcon name="sparkle" :size="20" />
        </div>

        <div class="min-w-0 flex-1">
          <h1 class="truncate font-display text-[0.9375rem] font-semibold tracking-tight text-fg">
            Agentic RAG Assistant
          </h1>
          <p class="flex items-center gap-1.5 text-xs text-subtle">
            <span class="relative flex h-1.5 w-1.5" aria-hidden="true">
              <span class="absolute inline-flex h-full w-full animate-ring-pulse rounded-full bg-success"></span>
              <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-success"></span>
            </span>
            llama3.2:3b · berjalan lokal
          </p>
        </div>

        <ThemeToggle />

        <button
          type="button"
          class="grid h-11 w-11 cursor-pointer place-items-center rounded-xl text-subtle transition-colors duration-200 hover:bg-elevated hover:text-fg"
          aria-label="Keluar"
          title="Keluar"
          @click="logout"
        >
          <AppIcon name="logout" :size="18" />
        </button>
      </div>
    </header>

    <main ref="scrollRef" class="flex-1 overflow-y-auto overscroll-contain">
      <div class="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6 sm:px-6">
        <!-- Empty state doubles as the suggestion surface: a blank chat gives
             no hint of what this assistant can actually do. -->
        <div v-if="!hasConversation && !isLoading" class="animate-fade-up pt-8 text-center sm:pt-16">
          <div
            class="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-primary to-accent-strong text-primary-fg shadow-glow"
            aria-hidden="true"
          >
            <AppIcon name="sparkle" :size="26" />
          </div>
          <h2 class="mt-4 font-display text-lg font-semibold tracking-tight text-fg">
            Ada yang bisa saya bantu?
          </h2>
          <p class="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-subtle">
            Saya bisa mencari di dokumen yang Anda unggah, membaca teks dari gambar, dan
            menghitung data di database — semuanya tanpa keluar dari mesin ini.
          </p>

          <div class="mx-auto mt-6 flex max-w-lg flex-col gap-2">
            <button
              v-for="suggestion in SUGGESTIONS"
              :key="suggestion"
              type="button"
              class="cursor-pointer rounded-xl border border-border-strong bg-surface px-4 py-2.5 text-left text-sm text-subtle shadow-sm transition-all duration-200 hover:-translate-y-px hover:border-primary/80 hover:text-fg hover:shadow-card"
              @click="useSuggestion(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>
        </div>

        <MessageBubble v-for="(message, index) in messages" :key="index" :message="message" />

        <div v-if="isLoading" class="flex animate-fade-up gap-3">
          <div
            class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-primary to-accent-strong text-primary-fg shadow-glow"
            aria-hidden="true"
          >
            <AppIcon name="sparkle" :size="15" />
          </div>
          <div
            class="flex items-center gap-1.5 rounded-bubble bg-surface px-4 py-3.5 ring-1 ring-border"
            role="status"
            aria-live="polite"
          >
            <span class="sr-only">Sedang memproses</span>
            <span
              v-for="dot in 3"
              :key="dot"
              class="h-1.5 w-1.5 animate-dot-pulse rounded-full bg-subtle"
              :style="{ animationDelay: `${(dot - 1) * 160}ms` }"
              aria-hidden="true"
            ></span>
          </div>
        </div>
      </div>
    </main>

    <footer class="border-t border-border bg-surface/80 backdrop-blur-md">
      <div class="mx-auto w-full max-w-3xl px-4 pb-4 pt-3 sm:px-6">
        <div
          v-if="error"
          class="mb-2.5 flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-xs text-danger ring-1 ring-danger/20"
          role="alert"
        >
          <AppIcon name="alert" :size="15" class="mt-px" />
          <p class="flex-1 leading-relaxed">{{ error }}</p>
          <button
            type="button"
            class="cursor-pointer rounded-md p-0.5 transition-colors hover:bg-danger/10"
            aria-label="Tutup pesan kesalahan"
            @click="error = null"
          >
            <AppIcon name="close" :size="14" />
          </button>
        </div>

        <div
          v-if="pendingImage"
          class="mb-2.5 inline-flex max-w-full items-center gap-2 rounded-xl border border-border bg-elevated px-3 py-1.5 text-xs text-subtle"
        >
          <AppIcon name="image" :size="14" />
          <span class="truncate">{{ pendingImage.replace(/^[0-9a-f]{32}-/, '') }}</span>
          <span class="text-faint">siap dibaca</span>
        </div>

        <div
          class="flex items-end gap-1.5 rounded-2xl border border-border-strong bg-surface p-1.5 shadow-card transition-colors focus-within:border-primary/80"
        >
          <UploadButton :disabled="isLoading" @file="attach" />

          <label for="composer" class="sr-only">Tulis pertanyaan</label>
          <textarea
            id="composer"
            ref="textareaRef"
            v-model="input"
            rows="1"
            placeholder="Tulis pertanyaan…"
            class="max-h-40 flex-1 resize-none self-center bg-transparent px-1 py-2 text-[0.9375rem] leading-relaxed text-fg placeholder:text-faint focus:outline-none"
            @keydown="onKeydown"
          ></textarea>

          <button
            type="button"
            class="grid h-11 w-11 shrink-0 cursor-pointer place-items-center rounded-xl bg-primary text-primary-fg shadow-glow transition-all duration-200 hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none disabled:hover:brightness-100"
            :disabled="!canSend"
            aria-label="Kirim pesan"
            title="Kirim pesan"
            @click="submit"
          >
            <AppIcon name="send" :size="18" />
          </button>
        </div>

        <p class="mt-2 hidden text-center text-[11px] text-faint sm:block">
          Enter untuk kirim · Shift + Enter untuk baris baru
        </p>
      </div>
    </footer>
  </div>
</template>
