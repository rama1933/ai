import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../../services/api'
import { useAttachments } from '../useAttachments'

const uploadResponse = (file: File, kind: 'image' | 'document') => ({
  filename: `abc-${file.name}`,
  status: kind === 'document' ? 'processed' : 'stored',
  kind,
  stored_name: `abc-${file.name}`,
  display_name: file.name,
  mime: file.type,
  size: file.size,
})

describe('useAttachments', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // jsdom's Blob cannot go through the real createObjectURL/revokeObjectURL.
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const { pending, clear } = useAttachments()
    clear()
    expect(pending.value).toHaveLength(0)
  })

  it('add() with three files produces three chips', async () => {
    vi.spyOn(api, 'uploadFile').mockImplementation(async (file: File) =>
      uploadResponse(file, file.type.startsWith('image/') ? 'image' : 'document'),
    )

    const { pending, add } = useAttachments()
    await add([
      new File(['x'], 'a.png', { type: 'image/png' }),
      new File(['y'], 'b.png', { type: 'image/png' }),
      new File(['z'], 'c.txt', { type: 'text/plain' }),
    ])

    expect(pending.value).toHaveLength(3)
    expect(pending.value.every((item) => item.status === 'ready')).toBe(true)
  })

  it('a rejected file marks only its own chip and leaves the others intact', async () => {
    vi.spyOn(api, 'uploadFile').mockImplementation(async (file: File) => {
      if (file.name === 'virus.exe') {
        throw Object.assign(new Error('extension .exe is not allowed'), {
          isAxiosError: true,
          response: { status: 400, data: { detail: 'extension .exe is not allowed' } },
        })
      }
      return uploadResponse(file, 'image')
    })

    const { pending, add } = useAttachments()
    await add([
      new File(['x'], 'good-1.png', { type: 'image/png' }),
      new File(['x'], 'virus.exe', { type: 'application/octet-stream' }),
      new File(['x'], 'good-2.png', { type: 'image/png' }),
    ])

    expect(pending.value).toHaveLength(3)
    const rejected = pending.value.find((item) => item.displayName === 'virus.exe')
    expect(rejected?.status).toBe('error')
    expect(rejected?.error).toBeTruthy()
    expect(pending.value.filter((item) => item.status === 'ready')).toHaveLength(2)
  })

  it('remove() drops one chip and revokes its preview', async () => {
    vi.spyOn(api, 'uploadFile').mockImplementation(async (file: File) => uploadResponse(file, 'image'))

    const { pending, add, remove } = useAttachments()
    await add([new File(['x'], 'a.png', { type: 'image/png' }), new File(['y'], 'b.png', { type: 'image/png' })])

    const target = pending.value[0]
    remove(target.id)

    expect(pending.value).toHaveLength(1)
    expect(pending.value[0].displayName).toBe('b.png')
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })

  it('clear() drops everything -- session switch and post-send cleanup', async () => {
    vi.spyOn(api, 'uploadFile').mockImplementation(async (file: File) => uploadResponse(file, 'image'))

    const { pending, add, clear } = useAttachments()
    await add([new File(['x'], 'a.png', { type: 'image/png' })])
    expect(pending.value).toHaveLength(1)

    clear()
    expect(pending.value).toHaveLength(0)
  })

  it('objectUrl fetches with the api, caches, and revokeAll releases every URL', async () => {
    const blobSpy = vi
      .spyOn(api, 'fetchAttachmentBlob')
      .mockResolvedValue(new Blob(['png'], { type: 'image/png' }))

    const { objectUrl, revokeAll } = useAttachments()
    const first = await objectUrl('stored-a.png')
    const second = await objectUrl('stored-a.png')
    expect(first).toBe('blob:mock')
    expect(second).toBe(first) // cached, not refetched
    expect(blobSpy).toHaveBeenCalledTimes(1)

    revokeAll()
    expect(URL.revokeObjectURL).toHaveBeenCalled()
    expect(await objectUrl('stored-a.png')).toBe('blob:mock') // cache refilled after revoke
    expect(blobSpy).toHaveBeenCalledTimes(2)
  })
})
