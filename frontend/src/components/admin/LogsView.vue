<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
} from 'reka-ui'

import { api, describeError, type LogItem } from '../../services/api'
import AppIcon from '../AppIcon.vue'

/**
 * What has happened: sign-ins (including the failed ones), ingestions, chat turns
 * and admin actions. Metadata only -- there is no message text in this table, and
 * no screen here reads another account's conversation (SP2 Decision 3).
 */
const PAGE_SIZE = 50

const rows = ref<LogItem[]>([])
const actions = ref<string[]>([])
const actionsError = ref<string | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
const offset = ref(0)

const action = ref('')
const username = ref('')
const since = ref('')
const until = ref('')

const purgeOpen = ref(false)
const purgeBefore = ref('')
const purgeResult = ref<number | null>(null)

const hasPrevious = computed(() => offset.value > 0)
const hasNext = computed(() => rows.value.length === PAGE_SIZE)

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    rows.value = await api.admin.listLogs({
      action: action.value || undefined,
      username: username.value.trim() || undefined,
      // A date input yields YYYY-MM-DD. The end of a range means the end of that
      // day, or the filter would exclude everything logged on it.
      since: since.value ? `${since.value}T00:00:00` : undefined,
      until: until.value ? `${until.value}T23:59:59` : undefined,
      limit: PAGE_SIZE,
      offset: offset.value,
    })
  } catch (err) {
    error.value = describeError(err)
  } finally {
    isLoading.value = false
  }
}

function applyFilters(): void {
  offset.value = 0
  void load()
}

function resetFilters(): void {
  action.value = ''
  username.value = ''
  since.value = ''
  until.value = ''
  applyFilters()
}

function move(delta: number): void {
  offset.value = Math.max(0, offset.value + delta)
  void load()
}

function requestPurge(): void {
  purgeResult.value = null
  purgeBefore.value = ''
  purgeOpen.value = true
}

async function confirmPurge(): Promise<void> {
  const before = purgeBefore.value
  purgeOpen.value = false
  if (!before) return
  try {
    const result = await api.admin.purgeLogs(`${before}T00:00:00`)
    purgeResult.value = result.deleted
  } catch (err) {
    error.value = describeError(err)
    return
  }
  offset.value = 0
  await load()
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** A detail value as a person reads it, never as raw JSON. */
function formatDetail(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'ya' : 'tidak'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

onMounted(async () => {
  try {
    actions.value = await api.admin.logActions()
  } catch (err) {
    // An empty select and a failed call look identical otherwise, and the operator
    // would conclude the console has no such filter. The table below still works.
    actions.value = []
    actionsError.value = describeError(err)
  }
  await load()
})

// A filter change is a new query from the first page, not a page turn.
watch([action, since, until], applyFilters)
</script>

<template>
  <section class="flex flex-col gap-4">
    <form class="flex flex-wrap items-end gap-2" @submit.prevent="applyFilters">
      <div class="flex flex-col gap-1">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-faint" for="log-action">Aksi</label>
        <select
          id="log-action"
          v-model="action"
          class="cursor-pointer rounded-xl border border-border bg-surface px-3 py-2 text-sm text-fg focus:border-primary/80 focus:outline-none"
        >
          <option value="">Semua aksi</option>
          <option v-for="name in actions" :key="name" :value="name">{{ name }}</option>
        </select>
        <p v-if="actionsError" class="max-w-[14rem] text-[11px] text-danger" :title="actionsError">
          Daftar aksi gagal dimuat.
        </p>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-faint" for="log-user">Pengguna</label>
        <input
          id="log-user"
          v-model="username"
          type="search"
          placeholder="username"
          class="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-faint focus:border-primary/80 focus:outline-none"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-faint" for="log-since">Dari</label>
        <input
          id="log-since"
          v-model="since"
          type="date"
          class="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-fg focus:border-primary/80 focus:outline-none"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-faint" for="log-until">Sampai</label>
        <input
          id="log-until"
          v-model="until"
          type="date"
          class="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-fg focus:border-primary/80 focus:outline-none"
        />
      </div>

      <button
        type="submit"
        class="cursor-pointer rounded-xl border border-border-strong bg-elevated px-3.5 py-2 text-sm font-medium text-fg transition-colors hover:border-primary/80"
      >
        Terapkan
      </button>
      <button
        type="button"
        class="cursor-pointer rounded-xl px-3 py-2 text-sm text-subtle transition-colors hover:bg-elevated hover:text-fg"
        @click="resetFilters"
      >
        Reset
      </button>

      <button
        type="button"
        class="ml-auto flex cursor-pointer items-center gap-1.5 rounded-xl border border-danger/40 px-3 py-2 text-sm text-danger transition-colors hover:bg-danger-soft"
        @click="requestPurge"
      >
        <AppIcon name="trash" :size="14" />
        Bersihkan log lama
      </button>
    </form>

    <p
      v-if="purgeResult !== null"
      class="rounded-xl bg-primary-soft px-3 py-2 text-xs leading-relaxed text-fg ring-1 ring-border"
      role="status"
    >
      {{ purgeResult }} baris log lama dihapus.
    </p>
    <p
      v-if="error"
      class="rounded-xl bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger ring-1 ring-danger/20"
      role="alert"
    >
      {{ error }}
    </p>

    <div class="overflow-x-auto rounded-2xl border border-border bg-surface">
      <table class="w-full min-w-[52rem] border-collapse text-sm">
        <thead>
          <tr class="border-b border-border text-left text-[11px] uppercase tracking-wider text-faint">
            <th class="px-4 py-3 font-semibold">Waktu</th>
            <th class="px-4 py-3 font-semibold">Pengguna</th>
            <th class="px-4 py-3 font-semibold">Aksi</th>
            <th class="px-4 py-3 font-semibold">Target</th>
            <th class="px-4 py-3 font-semibold">Detail</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id" class="border-b border-border/60 align-top">
            <td class="whitespace-nowrap px-4 py-3 text-subtle">{{ formatDate(row.created_at) }}</td>
            <td class="px-4 py-3 text-fg">{{ row.username ?? '—' }}</td>
            <td class="px-4 py-3">
              <span class="rounded-lg bg-elevated px-2 py-0.5 font-mono text-[11px] text-subtle">
                {{ row.action }}
              </span>
            </td>
            <td class="max-w-[16rem] px-4 py-3">
              <span class="block break-all text-xs text-subtle">{{ row.target ?? '—' }}</span>
            </td>
            <td class="px-4 py-3">
              <ul class="flex flex-wrap gap-1.5">
                <li
                  v-for="(value, key) in row.detail"
                  :key="key"
                  class="rounded-lg border border-border bg-bg px-2 py-0.5 text-[11px] text-subtle"
                >
                  <span class="text-faint">{{ key }}</span>
                  <span class="ml-1 font-medium text-fg">{{ formatDetail(value) }}</span>
                </li>
              </ul>
            </td>
          </tr>
        </tbody>
      </table>

      <p v-if="rows.length === 0" class="px-4 py-10 text-center text-sm text-faint">
        {{ isLoading ? 'Memuat log…' : 'Tidak ada catatan yang cocok.' }}
      </p>
    </div>

    <div class="flex items-center justify-between gap-3">
      <p class="text-xs text-faint">
        <template v-if="rows.length > 0">Baris {{ offset + 1 }}–{{ offset + rows.length }}</template>
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3 py-2 text-xs text-subtle transition-colors hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!hasPrevious"
          @click="move(-PAGE_SIZE)"
        >
          Sebelumnya
        </button>
        <button
          type="button"
          class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3 py-2 text-xs text-subtle transition-colors hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!hasNext"
          @click="move(PAGE_SIZE)"
        >
          Berikutnya
        </button>
      </div>
    </div>

    <AlertDialogRoot :open="purgeOpen" @update:open="(open) => (purgeOpen = open)">
      <AlertDialogPortal>
        <AlertDialogOverlay class="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm" />
        <AlertDialogContent
          class="fixed left-1/2 top-1/2 z-[70] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-border bg-surface p-5 shadow-2xl focus:outline-none"
        >
          <AlertDialogTitle class="font-display text-base font-semibold text-fg">Bersihkan log lama?</AlertDialogTitle>
          <AlertDialogDescription class="mt-1.5 text-sm leading-relaxed text-subtle">
            Setiap baris yang lebih tua dari tanggal ini dihapus permanen. Tidak ada tombol yang menghapus
            seluruh log — tanggalnya wajib diisi.
          </AlertDialogDescription>

          <label class="mt-3 block text-[11px] font-semibold uppercase tracking-wider text-faint" for="purge-before">
            Hapus yang lebih tua dari
          </label>
          <input
            id="purge-before"
            v-model="purgeBefore"
            type="date"
            class="mt-1 w-full rounded-xl border border-border bg-bg px-3 py-2 text-sm text-fg focus:border-primary/80 focus:outline-none"
          />

          <div class="mt-4 flex justify-end gap-2">
            <AlertDialogCancel
              class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3.5 py-2 text-sm text-subtle transition-colors hover:bg-elevated hover:text-fg"
            >
              Batal
            </AlertDialogCancel>
            <AlertDialogAction
              class="cursor-pointer rounded-xl bg-danger px-3.5 py-2 text-sm font-medium text-white transition-all hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!purgeBefore"
              @click="confirmPurge"
            >
              Hapus
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialogPortal>
    </AlertDialogRoot>
  </section>
</template>
