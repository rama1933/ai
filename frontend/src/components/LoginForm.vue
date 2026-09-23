<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { useAuth } from '../composables/useAuth'
import { api, describeError, SESSION_ENDED_KEY } from '../services/api'
import AppIcon from './AppIcon.vue'
import ThemeToggle from './ThemeToggle.vue'

const { login } = useAuth()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const isRegistering = ref(false)
const isSubmitting = ref(false)
const error = ref<string | null>(null)
const sessionEnded = ref(false)

// A forced sign-out leaves a note behind (api.ts). Read it once, then drop it: it
// describes the session that just ended, not this one.
onMounted(() => {
  try {
    sessionEnded.value = sessionStorage.getItem(SESSION_ENDED_KEY) === '1'
    sessionStorage.removeItem(SESSION_ENDED_KEY)
  } catch {
    sessionEnded.value = false
  }
})

const canSubmit = computed(
  () => username.value.trim().length >= 3 && password.value.length >= 8 && !isSubmitting.value,
)

async function submit(): Promise<void> {
  // Validate on submit rather than per keystroke, so the message only appears
  // once the person is actually done typing.
  if (username.value.trim().length < 3) {
    error.value = 'Username minimal 3 karakter.'
    return
  }
  if (password.value.length < 8) {
    error.value = 'Password minimal 8 karakter.'
    return
  }

  error.value = null
  sessionEnded.value = false
  isSubmitting.value = true
  try {
    if (isRegistering.value) await api.register(username.value, password.value)
    await login(username.value, password.value)
  } catch (err) {
    error.value = describeError(err)
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="relative flex min-h-dvh items-center justify-center bg-bg px-4 py-10">
    <!-- Two off-screen colour fields give the page depth without an image. They
         are decoration on a flat ground, so they are hidden from the a11y tree
         and never carry meaning. -->
    <div class="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div class="absolute -top-56 left-1/2 h-80 w-[42rem] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl"></div>
      <div class="absolute -bottom-56 right-[12%] h-72 w-72 rounded-full bg-accent-strong/10 blur-3xl"></div>
    </div>

    <div class="absolute right-3 top-3">
      <ThemeToggle />
    </div>

    <div class="relative w-full max-w-sm animate-fade-up">
      <div class="mb-6 text-center">
        <div
          class="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-primary to-accent-strong text-primary-fg shadow-glow"
          aria-hidden="true"
        >
          <AppIcon name="sparkle" :size="26" />
        </div>
        <h1 class="mt-4 font-display text-xl font-semibold tracking-tight text-fg">
          {{ isRegistering ? 'Buat akun' : 'Masuk' }}
        </h1>
        <p class="mt-1 text-sm text-subtle">
          Agentic RAG Assistant — pencarian dokumen, OCR, dan SQL, semuanya lokal.
        </p>
      </div>

      <form class="panel space-y-4 p-5" novalidate @submit.prevent="submit">
        <div>
          <label for="username" class="mb-1.5 block text-xs font-medium text-subtle">Username</label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            placeholder="mis. budi"
            class="field h-11 py-0"
            :aria-invalid="error !== null"
          />
        </div>

        <div>
          <label for="password" class="mb-1.5 block text-xs font-medium text-subtle">Password</label>
          <div class="relative">
            <input
              id="password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              :autocomplete="isRegistering ? 'new-password' : 'current-password'"
              placeholder="minimal 8 karakter"
              class="field h-11 py-0 pr-11"
              :aria-invalid="error !== null"
            />
            <button
              type="button"
              class="absolute right-1 top-1/2 grid h-9 w-9 -translate-y-1/2 cursor-pointer place-items-center rounded-lg text-subtle transition-colors hover:bg-elevated hover:text-fg"
              :aria-label="showPassword ? 'Sembunyikan password' : 'Tampilkan password'"
              :title="showPassword ? 'Sembunyikan password' : 'Tampilkan password'"
              @click="showPassword = !showPassword"
            >
              <AppIcon :name="showPassword ? 'eye-off' : 'eye'" :size="16" />
            </button>
          </div>
        </div>

        <p
          v-if="sessionEnded && !error"
          class="flex items-start gap-2 rounded-xl bg-elevated px-3 py-2.5 text-xs text-subtle ring-1 ring-border"
          role="status"
        >
          <AppIcon name="alert" :size="15" class="mt-px" />
          <span class="flex-1 leading-relaxed">
            Sesi Anda berakhir. Silakan masuk kembali — bila akun Anda dinonaktifkan, hubungi admin.
          </span>
        </p>

        <p
          v-if="error"
          class="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-xs text-danger ring-1 ring-danger/20"
          role="alert"
          aria-live="polite"
        >
          <AppIcon name="alert" :size="15" class="mt-px" />
          <span class="flex-1 leading-relaxed">{{ error }}</span>
        </p>

        <button
          type="submit"
          class="flex h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-primary text-sm font-semibold text-primary-fg shadow-glow transition-all duration-200 hover:brightness-110 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none disabled:hover:brightness-100"
          :disabled="!canSubmit"
        >
          <span
            v-if="isSubmitting"
            class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
            aria-hidden="true"
          ></span>
          {{ isSubmitting ? 'Memproses…' : isRegistering ? 'Daftar' : 'Masuk' }}
        </button>
      </form>

      <button
        type="button"
        class="mt-4 w-full cursor-pointer rounded-lg py-2 text-center text-xs text-subtle transition-colors hover:text-fg"
        @click="
          isRegistering = !isRegistering;
          error = null
        "
      >
        {{ isRegistering ? 'Sudah punya akun? Masuk' : 'Belum punya akun? Daftar' }}
      </button>
    </div>
  </div>
</template>
