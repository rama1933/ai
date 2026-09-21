<script setup lang="ts">
import { ref } from 'vue'

import { useAuth } from '../composables/useAuth'
import { api } from '../services/api'

const { login } = useAuth()

const username = ref('')
const password = ref('')
const isRegistering = ref(false)
const isSubmitting = ref(false)
const error = ref<string | null>(null)

async function submit(): Promise<void> {
  if (!username.value.trim() || password.value.length < 8) {
    error.value = 'Username wajib diisi dan password minimal 8 karakter.'
    return
  }
  error.value = null
  isSubmitting.value = true
  try {
    if (isRegistering.value) await api.register(username.value, password.value)
    await login(username.value, password.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="flex h-screen items-center justify-center bg-slate-50">
    <form class="w-80 space-y-3 rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200" @submit.prevent="submit">
      <h1 class="text-base font-semibold text-slate-800">
        {{ isRegistering ? 'Daftar' : 'Masuk' }} — Agentic RAG
      </h1>

      <input
        v-model="username"
        type="text"
        autocomplete="username"
        placeholder="Username"
        class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
      />
      <input
        v-model="password"
        type="password"
        autocomplete="current-password"
        placeholder="Password (min. 8 karakter)"
        class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
      />

      <p v-if="error" class="rounded bg-red-50 px-2 py-1 text-xs text-red-700">{{ error }}</p>

      <button
        type="submit"
        class="w-full rounded-lg bg-blue-600 py-2 text-sm font-medium text-white disabled:opacity-40"
        :disabled="isSubmitting"
      >
        {{ isSubmitting ? 'Memproses…' : isRegistering ? 'Daftar' : 'Masuk' }}
      </button>

      <button
        type="button"
        class="w-full text-xs text-slate-500 hover:text-slate-700"
        @click="isRegistering = !isRegistering"
      >
        {{ isRegistering ? 'Sudah punya akun? Masuk' : 'Belum punya akun? Daftar' }}
      </button>
    </form>
  </div>
</template>
