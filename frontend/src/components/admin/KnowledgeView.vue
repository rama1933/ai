<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
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

import { api, describeError, type ChunkItem, type KnowledgeItem } from '../../services/api'
import AppIcon from '../AppIcon.vue'

/**
 * What the assistant knows: every ingested document, its chunks, and the two things
 * you would want to do about it -- look inside, or remove it. It gets in as an
 * uploaded file, as pasted text, or as a URL; all three become the same stored file
 * server-side, so the table shows one kind of row.
 *
 * A document is its stored filename (SP2 Decision 1), which is what the API groups
 * by and what every call here addresses.
 */
const PAGE_SIZE = 25

const rows = ref<KnowledgeItem[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const query = ref('')
const offset = ref(0)

const expandedFilename = ref<string | null>(null)
const chunks = ref<ChunkItem[]>([])
const isLoadingChunks = ref(false)

const deleteOpen = ref(false)
const pendingDelete = ref<KnowledgeItem | null>(null)

// Dismissal (Esc, overlay, Batal) only closes; the row is cleared from the watcher,
// which runs after the synchronous click stack. The action button's own close fires
// before its handler, so without this the confirm would read a null row and delete
// nothing. Same pattern as SessionSidebar's delete dialog.
watch(deleteOpen, (open) => {
  if (!open) pendingDelete.value = null
})

const uploading = ref(false)
const uploadError = ref<string | null>(null)

// Three ways in, one at a time: a file, pasted text, or a URL. The panel is which
// of the latter two is open, so switching sources cannot leave a half-typed draft
// behind a closed panel.
const panel = ref<'text' | 'url' | null>(null)
const draftTitle = ref('')
const draftText = ref('')
const draftUrl = ref('')

function openPanel(which: 'text' | 'url'): void {
  panel.value = panel.value === which ? null : which
  uploadError.value = null
}

const hasPrevious = computed(() => offset.value > 0)
const hasNext = computed(() => rows.value.length === PAGE_SIZE)

// Only the newest request may write. A search typed over a page turn can otherwise
// land out of order, and the table would show the older answer under the newer query.
let loadToken = 0

async function load(): Promise<void> {
  const token = ++loadToken
  isLoading.value = true
  error.value = null
  try {
    const result = await api.admin.listDocuments({
      q: query.value.trim() || undefined,
      limit: PAGE_SIZE,
      offset: offset.value,
    })
    if (token === loadToken) rows.value = result
  } catch (err) {
    if (token === loadToken) error.value = describeError(err)
  } finally {
    isLoading.value = false
  }
}

function search(): void {
  offset.value = 0
  void load()
}

// Typing filters as you go; Enter still short-circuits the wait. Debounced so a
// fast typist costs one query, not one per keystroke.
const searchSoon = useDebounceFn(search, 300)
watch(query, () => searchSoon())

function clearSearch(): void {
  query.value = ''
  search()
}

/** Stored names carry a 32-hex uniqueness prefix the operator does not need;
 * it is shown only when it is the whole story, i.e. when it differs from the
 * name the uploader gave. */
function storedName(filename: string): string {
  return filename.replace(/^[0-9a-f]{32}-/, '')
}

function move(delta: number): void {
  offset.value = Math.max(0, offset.value + delta)
  void load()
}

async function toggleChunks(row: KnowledgeItem): Promise<void> {
  if (expandedFilename.value === row.filename) {
    collapse()
    return
  }
  const requested = row.filename
  expandedFilename.value = requested
  chunks.value = []
  isLoadingChunks.value = true
  try {
    const result = await api.admin.listChunks(requested)
    // A row opened, collapsed or switched while this was in flight must not have its
    // chunks written under whichever header is showing now.
    if (expandedFilename.value === requested) chunks.value = result
  } catch (err) {
    if (expandedFilename.value === requested) {
      error.value = describeError(err)
      expandedFilename.value = null
    }
  } finally {
    isLoadingChunks.value = false
  }
}

function collapse(): void {
  expandedFilename.value = null
  chunks.value = []
}

function requestDelete(row: KnowledgeItem): void {
  pendingDelete.value = row
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  const row = pendingDelete.value
  deleteOpen.value = false
  if (!row) return
  try {
    await api.admin.deleteDocument(row.filename)
  } catch (err) {
    error.value = describeError(err)
    return
  }
  if (expandedFilename.value === row.filename) collapse()
  await load()
}

/** Every source lands the same way: index it, then show the corpus it joined. A
 * failed one keeps its draft on screen so the operator does not retype it. */
async function ingest(run: () => Promise<unknown>): Promise<void> {
  uploading.value = true
  uploadError.value = null
  try {
    await run()
    panel.value = null
    draftTitle.value = ''
    draftText.value = ''
    draftUrl.value = ''
    offset.value = 0
    await load()
  } catch (err) {
    uploadError.value = describeError(err)
  } finally {
    uploading.value = false
  }
}

async function onFileChosen(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // allow re-selecting the same file
  if (!file) return
  await ingest(() => api.ingestDocument(file))
}

async function submitText(): Promise<void> {
  const content = draftText.value.trim()
  if (!content) return
  await ingest(() => api.ingestText({ content, title: draftTitle.value.trim() || undefined }))
}

async function submitUrl(): Promise<void> {
  const url = draftUrl.value.trim()
  if (!url) return
  await ingest(() => api.ingestUrl({ url, title: draftTitle.value.trim() || undefined }))
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatNumber(value: number): string {
  return value.toLocaleString('id-ID')
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <!-- Filter and submit live in one control: a search field with a separate
           "Cari" button beside it makes the operator travel to confirm what the
           field already knows. -->
      <div class="relative min-w-[14rem] flex-1">
        <AppIcon
          name="search"
          :size="15"
          class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
        />
        <label class="sr-only" for="knowledge-search">Cari dokumen</label>
        <input
          id="knowledge-search"
          v-model="query"
          type="search"
          placeholder="Cari nama berkas…"
          class="field pl-9 pr-9"
          @keydown.enter="search"
        />
        <button
          v-if="query"
          type="button"
          class="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-elevated hover:text-fg"
          aria-label="Bersihkan pencarian"
          title="Bersihkan pencarian"
          @click="clearSearch"
        >
          <AppIcon name="close" :size="14" />
        </button>
      </div>

      <button
        type="button"
        class="flex cursor-pointer items-center gap-2 rounded-xl border border-border-strong bg-surface px-3.5 py-2 text-sm font-medium text-fg transition-colors hover:border-primary/80 hover:text-primary"
        :class="panel === 'text' ? 'border-primary/80 text-primary' : ''"
        :aria-expanded="panel === 'text'"
        aria-controls="knowledge-text-panel"
        @click="openPanel('text')"
      >
        <AppIcon name="pencil" :size="15" />
        Tempel teks
      </button>

      <button
        type="button"
        class="flex cursor-pointer items-center gap-2 rounded-xl border border-border-strong bg-surface px-3.5 py-2 text-sm font-medium text-fg transition-colors hover:border-primary/80 hover:text-primary"
        :class="panel === 'url' ? 'border-primary/80 text-primary' : ''"
        :aria-expanded="panel === 'url'"
        aria-controls="knowledge-url-panel"
        @click="openPanel('url')"
      >
        <AppIcon name="link" :size="15" />
        Dari URL
      </button>

      <label
        class="ml-auto flex cursor-pointer items-center gap-2 rounded-xl bg-primary px-3.5 py-2 text-sm font-medium text-primary-fg shadow-glow transition-all hover:brightness-110 active:scale-[0.99]"
        :class="uploading ? 'pointer-events-none opacity-60' : ''"
      >
        <AppIcon name="plus" :size="15" />
        {{ uploading ? 'Mengindeks…' : 'Unggah dokumen' }}
        <!-- A plain file input rather than UploadButton: that one is a paperclip
             sized for the composer, and bending it into a labelled button here
             would cost more than these two lines. -->
        <input
          type="file"
          class="hidden"
          accept=".pdf,.txt,.md"
          :disabled="uploading"
          @change="onFileChosen"
        />
      </label>
    </div>

    <form
      v-if="panel === 'text'"
      id="knowledge-text-panel"
      class="panel flex flex-col gap-3 p-4"
      @submit.prevent="submitText"
    >
      <label class="text-xs font-medium text-subtle" for="knowledge-text-title">Judul (opsional)</label>
      <input
        id="knowledge-text-title"
        v-model="draftTitle"
        type="text"
        maxlength="200"
        placeholder="mis. Kebijakan cuti tahunan"
        class="field"
      />
      <label class="text-xs font-medium text-subtle" for="knowledge-text-body">Isi</label>
      <textarea
        id="knowledge-text-body"
        v-model="draftText"
        rows="8"
        placeholder="Tempel teks yang harus diketahui asisten…"
        class="field resize-y leading-relaxed"
      />
      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3.5 py-2 text-sm text-subtle transition-colors hover:text-fg"
          @click="panel = null"
        >
          Batal
        </button>
        <button
          type="submit"
          class="cursor-pointer rounded-xl bg-primary px-3.5 py-2 text-sm font-medium text-primary-fg transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="uploading || !draftText.trim()"
        >
          {{ uploading ? 'Mengindeks…' : 'Indeks teks' }}
        </button>
      </div>
    </form>

    <form
      v-if="panel === 'url'"
      id="knowledge-url-panel"
      class="panel flex flex-col gap-3 p-4"
      @submit.prevent="submitUrl"
    >
      <label class="text-xs font-medium text-subtle" for="knowledge-url">Alamat halaman</label>
      <input
        id="knowledge-url"
        v-model="draftUrl"
        type="url"
        required
        placeholder="https://contoh.id/kebijakan-cuti"
        class="field"
      />
      <label class="text-xs font-medium text-subtle" for="knowledge-url-title">Judul (opsional)</label>
      <input
        id="knowledge-url-title"
        v-model="draftTitle"
        type="text"
        maxlength="200"
        placeholder="Kosongkan untuk memakai nama dari URL"
        class="field"
      />
      <p class="text-[11px] leading-relaxed text-faint">
        Halaman diambil sekali oleh server lalu disimpan sebagai teks, jadi isinya tidak berubah
        sendiri kalau halaman aslinya berubah.
      </p>
      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3.5 py-2 text-sm text-subtle transition-colors hover:text-fg"
          @click="panel = null"
        >
          Batal
        </button>
        <button
          type="submit"
          class="cursor-pointer rounded-xl bg-primary px-3.5 py-2 text-sm font-medium text-primary-fg transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="uploading || !draftUrl.trim()"
        >
          {{ uploading ? 'Mengindeks…' : 'Ambil & indeks' }}
        </button>
      </div>
    </form>

    <p
      v-if="uploadError"
      class="rounded-xl bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger ring-1 ring-danger/20"
      role="alert"
    >
      {{ uploadError }}
    </p>
    <p
      v-if="error"
      class="rounded-xl bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger ring-1 ring-danger/20"
      role="alert"
    >
      {{ error }}
    </p>

    <div class="panel overflow-x-auto">
      <table class="w-full min-w-[44rem] border-collapse text-sm">
        <thead>
          <tr class="table-head">
            <th class="px-4 py-3 font-semibold">Dokumen</th>
            <th class="px-4 py-3 text-right font-semibold">Chunk</th>
            <th class="px-4 py-3 text-right font-semibold">Karakter</th>
            <th class="px-4 py-3 font-semibold">Pemilik</th>
            <th class="px-4 py-3 font-semibold">Diunggah</th>
            <th class="px-4 py-3 font-semibold"><span class="sr-only">Aksi</span></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in rows" :key="row.filename">
            <tr class="table-row align-top">
              <td class="max-w-[22rem] px-4 py-3">
                <button
                  type="button"
                  class="group/doc flex cursor-pointer items-start gap-2 text-left text-fg transition-colors hover:text-primary"
                  :aria-expanded="expandedFilename === row.filename"
                  @click="toggleChunks(row)"
                >
                  <AppIcon
                    name="chevron"
                    :size="14"
                    class="mt-1 text-faint transition-transform duration-200"
                    :class="expandedFilename === row.filename ? 'rotate-90 text-primary' : ''"
                  />
                  <span class="min-w-0">
                    <span class="block break-all font-medium">{{ row.display_name }}</span>
                    <span
                      v-if="storedName(row.filename) !== row.display_name"
                      class="mt-0.5 block break-all font-mono text-[11px] text-faint"
                    >
                      {{ storedName(row.filename) }}
                    </span>
                  </span>
                </button>
              </td>
              <td class="px-4 py-3 text-right tabular-nums text-subtle">{{ formatNumber(row.chunks) }}</td>
              <td class="px-4 py-3 text-right tabular-nums text-subtle">{{ formatNumber(row.chars) }}</td>
              <td class="px-4 py-3 text-subtle">{{ row.owner ?? '—' }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-subtle">{{ formatDate(row.created_at) }}</td>
              <td class="px-4 py-3 text-right">
                <button
                  type="button"
                  class="grid h-8 w-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-danger-soft hover:text-danger"
                  :aria-label="`Hapus ${row.display_name}`"
                  :title="`Hapus ${row.display_name}`"
                  @click="requestDelete(row)"
                >
                  <AppIcon name="trash" :size="15" />
                </button>
              </td>
            </tr>

            <tr v-if="expandedFilename === row.filename" class="border-b border-border/60 bg-bg">
              <td colspan="6" class="px-4 py-4">
                <p v-if="isLoadingChunks" class="text-xs text-faint">Memuat chunk…</p>
                <ol v-else class="flex flex-col gap-2">
                  <li v-for="chunk in chunks" :key="chunk.chunk_index" class="panel p-3">
                    <p class="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-subtle">
                      Chunk {{ chunk.chunk_index }} · {{ formatNumber(chunk.chars) }} karakter
                    </p>
                    <p class="whitespace-pre-wrap break-words text-xs leading-relaxed text-subtle">
                      {{ chunk.content }}
                    </p>
                  </li>
                </ol>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div v-if="rows.length === 0" class="flex flex-col items-center gap-2 px-4 py-14 text-center">
        <div class="grid h-11 w-11 place-items-center rounded-xl bg-elevated text-faint" aria-hidden="true">
          <AppIcon :name="isLoading ? 'history' : 'database'" :size="20" />
        </div>
        <p class="text-sm text-subtle">{{ isLoading ? 'Memuat dokumen…' : 'Belum ada dokumen.' }}</p>
        <p v-if="!isLoading" class="max-w-xs text-xs leading-relaxed text-faint">
          Unggah berkas, tempel teks, atau ambil dari URL untuk mulai mengisi basis pengetahuan.
        </p>
      </div>
    </div>

    <div class="flex items-center justify-between gap-3">
      <p class="text-xs text-faint">
        <template v-if="rows.length > 0">
          Baris {{ offset + 1 }}–{{ offset + rows.length }}
        </template>
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3 py-2 text-xs font-medium text-subtle transition-colors hover:border-primary/80 hover:text-fg disabled:cursor-not-allowed disabled:border-border disabled:opacity-40 disabled:hover:text-subtle"
          :disabled="!hasPrevious"
          @click="move(-PAGE_SIZE)"
        >
          Sebelumnya
        </button>
        <button
          type="button"
          class="cursor-pointer rounded-xl border border-border-strong bg-surface px-3 py-2 text-xs font-medium text-subtle transition-colors hover:border-primary/80 hover:text-fg disabled:cursor-not-allowed disabled:border-border disabled:opacity-40 disabled:hover:text-subtle"
          :disabled="!hasNext"
          @click="move(PAGE_SIZE)"
        >
          Berikutnya
        </button>
      </div>
    </div>

    <AlertDialogRoot :open="deleteOpen" @update:open="(open) => (deleteOpen = open)">
      <AlertDialogPortal>
        <AlertDialogOverlay class="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm" />
        <AlertDialogContent
          class="fixed left-1/2 top-1/2 z-[70] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-border bg-surface p-5 shadow-2xl focus:outline-none"
        >
          <AlertDialogTitle class="font-display text-base font-semibold text-fg">Hapus dokumen?</AlertDialogTitle>
          <AlertDialogDescription class="mt-1.5 break-words text-sm leading-relaxed text-subtle">
            “{{ pendingDelete?.display_name }}” beserta seluruh chunk-nya akan dihapus dari basis pengetahuan,
            dan berkas unggahannya ikut terhapus. Tindakan ini tidak bisa dibatalkan.
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
              Hapus dokumen
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialogPortal>
    </AlertDialogRoot>
  </section>
</template>
