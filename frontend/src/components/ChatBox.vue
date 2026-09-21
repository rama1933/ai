<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useEventListener, useMediaQuery, useScroll, useTextareaAutosize } from '@vueuse/core'

import { useAttachments } from '../composables/useAttachments'
import { useAuth } from '../composables/useAuth'
import { useChat } from '../composables/useChat'
import { useSessions } from '../composables/useSessions'
import AppIcon from './AppIcon.vue'
import AttachmentChip from './AttachmentChip.vue'
import MessageBubble from './MessageBubble.vue'
import SessionSidebar from './SessionSidebar.vue'
import ThemeToggle from './ThemeToggle.vue'
import UploadButton from './UploadButton.vue'

const {
  messages,
  input,
  pending,
  hasUploading,
  isLoading,
  isStreaming,
  error,
  send,
  stop,
  regenerate,
  saveEdit,
  attach,
  removeAttachment,
  loadHistory,
  switchTo,
} = useChat()
const { revokeAll } = useAttachments()
const { refresh: refreshSessions } = useSessions()
const { logout } = useAuth()

const scrollRef = ref<HTMLElement | null>(null)
const drawerOpen = ref(false)
const dragging = ref(false)

// Grow the composer with its content; the class max-h-40 caps and scrolls it.
// The returned ref is the live textarea element, reused for focusing below.
const { textarea: textareaRef } = useTextareaAutosize({ input })

// An explicit `behavior` on scrollTo wins over the CSS `scroll-behavior`, so
// the reduced-motion block in style.css cannot reach this call — ask here too.
const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')

const hasConversation = computed(() => messages.value.length > 0)

// Follow the conversation while the reader is at the bottom, or while a stream
// is arriving; otherwise leave them where they scrolled and offer the pill.
const { arrivedState } = useScroll(scrollRef, { behavior: 'auto' })
const showPill = computed(() => hasConversation.value && !arrivedState.bottom && !isStreaming.value)

const lastContent = computed(() => messages.value[messages.value.length - 1]?.content)

watch([lastContent, () => messages.value.length, isLoading], async ([content]) => {
  if (content === undefined) return
  if (!arrivedState.bottom && !isStreaming.value && !isLoading.value) return
  await nextTick()
  scrollToBottom()
})

const SUGGESTIONS = [
  'Berapa hari cuti tahunan karyawan tetap?',
  'Berapa jumlah baris pada tabel documents?',
  'Halo, perkenalkan dirimu',
]

/** Drawer dismissed by selecting, creating, or deleting — close it and reload. */
async function onSidebarNavigate(): Promise<void> {
  drawerOpen.value = false
  await switchTo()
}

// Esc aborts the stream from wherever focus sits.
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (event.key === 'Escape' && isStreaming.value) stop()
})

onMounted(async () => {
  await loadHistory()
  void refreshSessions()
  scrollToBottom()
})

// Blob URLs are view-lifetime state; the chat owning them cleans them up.
onUnmounted(() => revokeAll())

function scrollToBottom(): void {
  const el = scrollRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: reducedMotion.value ? 'auto' : 'smooth' })
}

function onKeydown(event: KeyboardEvent): void {
  // isComposing guards IME input, where Enter commits a candidate rather than sending.
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

/** Screenshots and copied images arrive on the clipboard as files. */
function onPaste(event: ClipboardEvent): void {
  const files = Array.from(event.clipboardData?.files ?? [])
  if (files.length > 0) {
    event.preventDefault()
    void attach(files)
  }
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length > 0) {
    event.preventDefault()
    void attach(files)
  }
}

async function submit(): Promise<void> {
  if (!input.value.trim() || isLoading.value || isStreaming.value || hasUploading.value) return
  await send()
  void refreshSessions() // a first, client-minted session only exists server-side now
  void nextTick(() => textareaRef.value?.focus())
}

function useSuggestion(text: string): void {
  input.value = text
  void nextTick(() => textareaRef.value?.focus())
}

const canSend = computed(
  () => input.value.trim().length > 0 && !isLoading.value && !isStreaming.value && !hasUploading.value,
)
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-bg">
    <SessionSidebar variant="rail" @navigate="onSidebarNavigate" />
    <SessionSidebar
      variant="drawer"
      :open="drawerOpen"
      @close="drawerOpen = false"
      @navigate="onSidebarNavigate"
    />

    <div class="flex h-dvh min-w-0 flex-1 flex-col bg-bg">
      <header class="border-b border-border bg-surface/80 backdrop-blur-md">
        <div class="mx-auto flex w-full max-w-3xl items-center gap-3 px-4 py-3 sm:px-6">
          <button
            type="button"
            class="grid h-11 w-11 shrink-0 cursor-pointer place-items-center rounded-xl text-subtle transition-colors duration-200 hover:bg-elevated hover:text-fg lg:hidden"
            aria-label="Buka daftar percakapan"
            title="Percakapan"
            @click="drawerOpen = true"
          >
            <AppIcon name="panel" :size="18" />
          </button>

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
          <div v-if="!hasConversation && !isLoading && !isStreaming" class="animate-fade-up pt-8 text-center sm:pt-16">
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

          <MessageBubble
            v-for="(message, index) in messages"
            :key="index"
            :message="message"
            :index="index"
            @regenerate="regenerate"
            @save-edit="(i: number, text: string) => saveEdit(i, text)"
          />

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

      <!-- Appear when the reader scrolled away from the live conversation. -->
      <div v-if="showPill" class="pointer-events-none relative">
        <button
          type="button"
          class="pointer-events-auto absolute -top-14 left-1/2 grid h-9 w-9 -translate-x-1/2 cursor-pointer place-items-center rounded-full border border-border-strong bg-surface text-subtle shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:text-fg"
          aria-label="Kembali ke pesan terbaru"
          title="Ke pesan terbaru"
          @click="scrollToBottom"
        >
          <AppIcon name="send" :size="16" class="rotate-180" />
        </button>
      </div>

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

          <!-- Drop zone: a visible target over the composer while dragging. -->
          <div
            class="relative rounded-2xl transition-all duration-200"
            :class="dragging ? 'ring-2 ring-primary ring-offset-2 ring-offset-bg' : ''"
            @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false"
            @drop="onDrop"
          >
            <div
              v-if="dragging"
              class="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-2xl bg-primary-soft/80 backdrop-blur-sm"
            >
              <p class="flex items-center gap-2 text-sm font-medium text-fg">
                <AppIcon name="paperclip" :size="16" />
                Lepaskan untuk melampirkan
              </p>
            </div>

            <div v-if="pending.length" class="mb-2.5 flex flex-wrap gap-2">
              <AttachmentChip
                v-for="item in pending"
                :key="item.id"
                :name="item.displayName"
                :kind="item.mime.startsWith('image/') ? 'image' : 'document'"
                :mime="item.mime"
                :size="item.size"
                :src="item.previewUrl"
                :error="item.error"
                :uploading="item.status === 'uploading'"
                removable
                @remove="removeAttachment(item.id)"
              />
            </div>

            <div
              class="flex items-end gap-1.5 rounded-2xl border border-border-strong bg-surface p-1.5 shadow-card transition-colors focus-within:border-primary/80"
            >
              <UploadButton :disabled="isLoading || isStreaming" @files="attach" />

              <label for="composer" class="sr-only">Tulis pertanyaan</label>
              <textarea
                id="composer"
                ref="textareaRef"
                v-model="input"
                rows="1"
                placeholder="Tulis pertanyaan…"
                class="max-h-40 flex-1 resize-none self-center bg-transparent px-1 py-2 text-[0.9375rem] leading-relaxed text-fg placeholder:text-faint focus:outline-none"
                @keydown="onKeydown"
                @paste="onPaste"
              ></textarea>

              <button
                type="button"
                class="grid h-11 w-11 shrink-0 cursor-pointer place-items-center rounded-xl bg-primary text-primary-fg shadow-glow transition-all duration-200 hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none disabled:hover:brightness-100"
                :class="isStreaming ? 'bg-danger shadow-none' : ''"
                :disabled="isStreaming ? false : !canSend"
                :aria-label="isStreaming ? 'Hentikan jawaban' : 'Kirim pesan'"
                :title="isStreaming ? 'Hentikan (Esc)' : 'Kirim pesan'"
                @click="isStreaming ? stop() : submit()"
              >
                <AppIcon :name="isStreaming ? 'stop' : 'send'" :size="18" />
              </button>
            </div>
          </div>

          <p class="mt-2 hidden text-center text-[11px] text-faint sm:block">
            Enter untuk kirim · Shift + Enter untuk baris baru
          </p>
        </div>
      </footer>
    </div>
  </div>
</template>
