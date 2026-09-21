import { computed, ref } from 'vue'

import { api, describeError } from '../services/api'

export interface PendingAttachment {
  id: string
  file: File
  /** Local object URL for image previews -- no server round trip before send. */
  previewUrl: string | null
  status: 'uploading' | 'ready' | 'error'
  storedName: string | null
  displayName: string
  mime: string
  size: number
  error: string | null
}

// Module singleton, the same shape as useSessions/useAuth: the composer and the
// message bubbles share one pending list and one blob-url cache.
const pending = ref<PendingAttachment[]>([])
const blobUrls = new Map<string, string>()
const inflight = new Map<string, Promise<string | null>>()
// Preview URLs handed over to a sent message: no longer the composer's to
// revoke when the chip list clears.
const adoptedUrls = new Set<string>()

export function useAttachments() {
  const hasUploading = computed(() => pending.value.some((item) => item.status === 'uploading'))
  const readyNames = computed(() =>
    pending.value.filter((item) => item.status === 'ready' && item.storedName).map((item) => item.storedName as string),
  )

  /**
   * Upload each file in sequence. A rejected file marks only its own chip --
   * one bad .exe among four must not discard the other three.
   */
  async function add(files: File[], onDocumentStored?: (displayName: string) => void): Promise<void> {
    for (const file of files) {
      pending.value.push({
        id: crypto.randomUUID(),
        file,
        previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
        status: 'uploading',
        storedName: null,
        displayName: file.name,
        mime: file.type,
        size: file.size,
        error: null,
      })
      // Keep the reactive proxy, not the raw object pushed above: mutations on
      // the raw object bypass the proxy and the chips would never re-render.
      const item = pending.value[pending.value.length - 1]
      try {
        const result = await api.uploadFile(file)
        item.status = 'ready'
        item.storedName = result.stored_name
        item.displayName = result.display_name
        item.mime = result.mime
        item.size = result.size
        // The note is the only signal that a PDF did something beyond attaching.
        if (result.kind === 'document') onDocumentStored?.(result.display_name)
      } catch (err) {
        item.status = 'error'
        item.error = describeError(err)
      }
    }
  }

  function remove(id: string): void {
    const index = pending.value.findIndex((item) => item.id === id)
    if (index === -1) return
    const item = pending.value[index]
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    pending.value.splice(index, 1)
  }

  /** Drop every pending chip; used after a message goes out and on session switch. */
  function clear(): void {
    for (const item of pending.value) {
      if (item.previewUrl && !adoptedUrls.has(item.previewUrl)) URL.revokeObjectURL(item.previewUrl)
    }
    pending.value = []
  }

  /**
   * Transfer preview URLs to a sent message: the chip list may clear, the
   * optimistic bubble keeps rendering its local thumbnail.
   */
  function adopt(urls: (string | null | undefined)[]): void {
    for (const url of urls) if (url) adoptedUrls.add(url)
  }

  /**
   * An object URL for a stored attachment. GET /attachments requires a bearer
   * token that <img src> cannot carry, so fetch with the token and hand the
   * browser a blob URL instead -- no second auth scheme to get wrong.
   */
  async function objectUrl(storedName: string): Promise<string | null> {
    const cached = blobUrls.get(storedName)
    if (cached) return cached
    const running = inflight.get(storedName)
    if (running) return running
    const promise = api
      .fetchAttachmentBlob(storedName)
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        blobUrls.set(storedName, url)
        return url
      })
      .catch(() => null)
      .finally(() => inflight.delete(storedName))
    inflight.set(storedName, promise)
    return promise
  }

  /** Revoke every cached blob URL; the owner component calls this on unmount. */
  function revokeAll(): void {
    for (const url of blobUrls.values()) URL.revokeObjectURL(url)
    for (const url of adoptedUrls) URL.revokeObjectURL(url)
    blobUrls.clear()
    adoptedUrls.clear()
  }

  return { pending, hasUploading, readyNames, add, remove, clear, adopt, objectUrl, revokeAll }
}
