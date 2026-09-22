<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
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

import { useAuth } from '../../composables/useAuth'
import { api, describeError, type AdminUserItem } from '../../services/api'
import AppIcon from '../AppIcon.vue'

/**
 * Who may use the system. Deactivation is the normal control and deletion is the
 * sharp one (SP2 Decision 2), so the toggle is a plain switch and delete sits
 * behind a confirmation.
 *
 * The server owns three guards -- no self-demotion, no self-deletion, never zero
 * active admins -- and this screen only mirrors them by disabling the controls it
 * knows will fail. Disabling is the courtesy; the 400 is the boundary.
 */
const { username } = useAuth()

const ROLES = ['ADMIN', 'USER', 'READ_ONLY'] as const

const rows = ref<AdminUserItem[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const query = ref('')

const form = reactive({ username: '', password: '', role: 'USER' as string })
const creating = ref(false)
const formError = ref<string | null>(null)

const deleteOpen = ref(false)
const pendingDelete = ref<AdminUserItem | null>(null)

watch(deleteOpen, (open) => {
  if (!open) pendingDelete.value = null
})

const isSelf = (row: AdminUserItem): boolean => row.username === username.value

const canCreate = computed(
  () => form.username.trim().length >= 3 && form.password.length >= 8 && !creating.value,
)

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    rows.value = await api.admin.listUsers({ q: query.value.trim() || undefined, limit: 500 })
  } catch (err) {
    error.value = describeError(err)
  } finally {
    isLoading.value = false
  }
}

function applyRow(updated: AdminUserItem): void {
  const index = rows.value.findIndex((row) => row.id === updated.id)
  if (index !== -1) rows.value[index] = updated
}

async function submitCreate(): Promise<void> {
  if (!canCreate.value) return
  creating.value = true
  formError.value = null
  notice.value = null
  try {
    const created = await api.admin.createUser({
      username: form.username.trim(),
      password: form.password,
      role: form.role,
    })
    rows.value.unshift(created)
    notice.value = `${created.username} ditambahkan.`
    form.username = ''
    form.password = ''
    form.role = 'USER'
  } catch (err) {
    formError.value = describeError(err)
  } finally {
    creating.value = false
  }
}

async function changeRole(row: AdminUserItem, event: Event): Promise<void> {
  const role = (event.target as HTMLSelectElement).value
  error.value = null
  try {
    applyRow(await api.admin.updateUser(row.id, { role }))
  } catch (err) {
    error.value = describeError(err)
    await load() // put the select back to what the server still believes
  }
}

async function toggleActive(row: AdminUserItem): Promise<void> {
  error.value = null
  notice.value = null
  try {
    const updated = await api.admin.updateUser(row.id, { is_active: !row.is_active })
    applyRow(updated)
    notice.value = `${updated.username} ${updated.is_active ? 'diaktifkan' : 'dinonaktifkan'}.`
  } catch (err) {
    error.value = describeError(err)
  }
}

function requestDelete(row: AdminUserItem): void {
  pendingDelete.value = row
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  const row = pendingDelete.value
  deleteOpen.value = false
  if (!row) return
  try {
    await api.admin.deleteUser(row.id)
  } catch (err) {
    error.value = describeError(err)
    return
  }
  rows.value = rows.value.filter((candidate) => candidate.id !== row.id)
  notice.value = `${row.username} dihapus.`
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' })
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="flex flex-col gap-4">
    <form
      class="flex flex-wrap items-end gap-2 rounded-2xl border border-border bg-surface p-4"
      @submit.prevent="submitCreate"
    >
      <div class="flex flex-col gap-1">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-faint" for="new-username">Username</label>
        <input
          id="new-username"
          v-model="form.username"
          type="text"
          minlength="3"
          maxlength="100"
          required
          class="rounded-xl border border-border bg-bg px-3 py-2 text-sm text-fg focus:border-primary/80 focus:outline-none"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-faint" for="new-password">Password</label>
        <input
          id="new-password"
          v-model="form.password"
          type="password"
          minlength="8"
          maxlength="128"
          required
          class="rounded-xl border border-border bg-bg px-3 py-2 text-sm text-fg focus:border-primary/80 focus:outline-none"
        />
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-faint" for="new-role">Peran</label>
        <select
          id="new-role"
          v-model="form.role"
          class="cursor-pointer rounded-xl border border-border bg-bg px-3 py-2 text-sm text-fg focus:border-primary/80 focus:outline-none"
        >
          <option v-for="role in ROLES" :key="role" :value="role">{{ role }}</option>
        </select>
      </div>

      <button
        type="submit"
        class="cursor-pointer rounded-xl bg-primary px-3.5 py-2 text-sm font-medium text-primary-fg shadow-glow transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        :disabled="!canCreate"
      >
        {{ creating ? 'Menambah…' : 'Tambah pengguna' }}
      </button>

      <p v-if="formError" class="text-xs text-danger" role="alert">{{ formError }}</p>
    </form>

    <div class="flex flex-wrap items-center gap-2">
      <div class="relative min-w-[12rem] flex-1">
        <AppIcon
          name="search"
          :size="14"
          class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
        />
        <label class="sr-only" for="user-filter">Cari pengguna</label>
        <input
          id="user-filter"
          v-model="query"
          type="search"
          placeholder="Cari username…"
          class="w-full rounded-xl border border-border bg-surface py-2.5 pl-8 pr-3 text-sm text-fg placeholder:text-faint focus:border-primary/80 focus:outline-none"
          @keydown.enter="load"
        />
      </div>
      <button
        type="button"
        class="cursor-pointer rounded-xl border border-border-strong bg-elevated px-3.5 py-2.5 text-sm font-medium text-fg transition-colors hover:border-primary/80"
        @click="load"
      >
        Cari
      </button>
    </div>

    <p
      v-if="notice"
      class="rounded-xl bg-primary-soft px-3 py-2 text-xs leading-relaxed text-fg ring-1 ring-border"
      role="status"
    >
      {{ notice }}
    </p>
    <p
      v-if="error"
      class="rounded-xl bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger ring-1 ring-danger/20"
      role="alert"
    >
      {{ error }}
    </p>

    <div class="overflow-x-auto rounded-2xl border border-border bg-surface">
      <table class="w-full min-w-[48rem] border-collapse text-sm">
        <thead>
          <tr class="border-b border-border text-left text-[11px] uppercase tracking-wider text-faint">
            <th class="px-4 py-3 font-semibold">Pengguna</th>
            <th class="px-4 py-3 font-semibold">Peran</th>
            <th class="px-4 py-3 font-semibold">Status</th>
            <th class="px-4 py-3 font-semibold">Sesi</th>
            <th class="px-4 py-3 font-semibold">Dokumen</th>
            <th class="px-4 py-3 font-semibold">Dibuat</th>
            <th class="px-4 py-3 font-semibold"><span class="sr-only">Aksi</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id" class="border-b border-border/60">
            <td class="px-4 py-3">
              <span class="text-fg">{{ row.username }}</span>
              <span v-if="isSelf(row)" class="ml-2 text-[11px] text-faint">(Anda)</span>
            </td>
            <td class="px-4 py-3">
              <label class="sr-only" :for="`role-${row.id}`">Peran {{ row.username }}</label>
              <select
                :id="`role-${row.id}`"
                :value="row.role"
                :disabled="isSelf(row)"
                :title="isSelf(row) ? 'Anda tidak bisa mengubah peran Anda sendiri' : undefined"
                class="cursor-pointer rounded-xl border border-border bg-bg px-2.5 py-1.5 text-xs text-fg focus:border-primary/80 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                @change="changeRole(row, $event)"
              >
                <option v-for="role in ROLES" :key="role" :value="role">{{ role }}</option>
              </select>
            </td>
            <td class="px-4 py-3">
              <button
                type="button"
                class="cursor-pointer rounded-lg px-2 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                :class="row.is_active ? 'bg-success/10 text-success' : 'bg-danger-soft text-danger'"
                :disabled="isSelf(row)"
                :title="isSelf(row) ? 'Anda tidak bisa menonaktifkan akun Anda sendiri' : undefined"
                @click="toggleActive(row)"
              >
                {{ row.is_active ? 'Aktif' : 'Nonaktif' }}
              </button>
            </td>
            <td class="px-4 py-3 text-subtle">{{ row.sessions }}</td>
            <td class="px-4 py-3 text-subtle">{{ row.documents }}</td>
            <td class="whitespace-nowrap px-4 py-3 text-subtle">{{ formatDate(row.created_at) }}</td>
            <td class="px-4 py-3 text-right">
              <button
                type="button"
                class="grid h-8 w-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-danger-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-faint"
                :disabled="isSelf(row)"
                :aria-label="`Hapus ${row.username}`"
                :title="isSelf(row) ? 'Anda tidak bisa menghapus akun Anda sendiri' : `Hapus ${row.username}`"
                @click="requestDelete(row)"
              >
                <AppIcon name="trash" :size="15" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <p v-if="rows.length === 0" class="px-4 py-10 text-center text-sm text-faint">
        {{ isLoading ? 'Memuat pengguna…' : 'Tidak ada pengguna yang cocok.' }}
      </p>
    </div>

    <AlertDialogRoot :open="deleteOpen" @update:open="(open) => (deleteOpen = open)">
      <AlertDialogPortal>
        <AlertDialogOverlay class="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm" />
        <AlertDialogContent
          class="fixed left-1/2 top-1/2 z-[70] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-border bg-surface p-5 shadow-2xl focus:outline-none"
        >
          <AlertDialogTitle class="font-display text-base font-semibold text-fg">Hapus pengguna?</AlertDialogTitle>
          <AlertDialogDescription class="mt-1.5 break-words text-sm leading-relaxed text-subtle">
            “{{ pendingDelete?.username }}” beserta seluruh percakapan dan riwayat pesannya akan dihapus, dan
            dokumennya kehilangan pemilik. Untuk mencabut akses tanpa kehilangan data, nonaktifkan saja.
          </AlertDialogDescription>
          <div class="mt-4 flex justify-end gap-2">
            <AlertDialogCancel
              class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3.5 py-2 text-sm text-subtle transition-colors hover:bg-elevated hover:text-fg"
            >
              Batal
            </AlertDialogCancel>
            <AlertDialogAction
              class="cursor-pointer rounded-xl bg-danger px-3.5 py-2 text-sm font-medium text-white transition-all hover:brightness-110 active:scale-[0.98]"
              @click="confirmDelete"
            >
              Hapus pengguna
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialogPortal>
    </AlertDialogRoot>
  </section>
</template>
