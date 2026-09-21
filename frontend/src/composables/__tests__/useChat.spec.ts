import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../../services/api'
import { useChat } from '../useChat'
import { useSessions } from '../useSessions'

describe('useChat', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    // The session id now lives in the useSessions singleton; reset it so each
    // test mints its own.
    useSessions().activeId.value = null
  })

  it('appends the user message and the assistant reply', async () => {
    vi.spyOn(api, 'sendMessage').mockResolvedValue({
      answer: 'Masa retensi 5 tahun.',
      tool_used: 'rag_search',
      sources: [{ filename: 'policy.pdf', score: 0.9 }],
    })

    const chat = useChat()
    chat.input.value = 'berapa lama retensi?'
    await chat.send()

    expect(chat.messages.value).toHaveLength(2)
    expect(chat.messages.value[0]).toMatchObject({ role: 'user', content: 'berapa lama retensi?' })
    expect(chat.messages.value[1]).toMatchObject({ role: 'assistant', toolUsed: 'rag_search' })
    expect(chat.messages.value[1].sources?.[0].filename).toBe('policy.pdf')
    expect(chat.input.value).toBe('')
    expect(chat.isLoading.value).toBe(false)
  })

  it('does nothing when the input is blank', async () => {
    const spy = vi.spyOn(api, 'sendMessage')
    const chat = useChat()
    chat.input.value = '   '
    await chat.send()
    expect(spy).not.toHaveBeenCalled()
    expect(chat.messages.value).toHaveLength(0)
  })

  it('surfaces a backend error without losing the user message', async () => {
    vi.spyOn(api, 'sendMessage').mockRejectedValue(new Error('503 local LLM unavailable'))

    const chat = useChat()
    chat.input.value = 'halo'
    await chat.send()

    expect(chat.error.value).toContain('503')
    expect(chat.messages.value).toHaveLength(1)
    expect(chat.isLoading.value).toBe(false)
  })

  it('attaches an uploaded image and clears it after sending', async () => {
    vi.spyOn(api, 'uploadFile').mockResolvedValue({
      filename: 'abc-struk.png',
      status: 'stored',
      kind: 'image',
      stored_name: 'abc-struk.png',
      display_name: 'struk.png',
      mime: 'image/png',
      size: 1,
    })
    const sendSpy = vi.spyOn(api, 'sendMessage').mockResolvedValue({ answer: 'ok', tool_used: 'image_ocr', sources: [] })

    const chat = useChat()
    await chat.attach(new File(['x'], 'struk.png', { type: 'image/png' }))
    expect(chat.pendingImage.value).toBe('abc-struk.png')

    chat.input.value = 'total berapa?'
    await chat.send()

    expect(sendSpy).toHaveBeenCalledWith(expect.any(String), 'total berapa?', 'abc-struk.png')
    expect(chat.pendingImage.value).toBeNull()
  })

  it('reuses the same session id across messages', async () => {
    const spy = vi.spyOn(api, 'sendMessage').mockResolvedValue({ answer: 'ok', tool_used: null, sources: [] })
    const chat = useChat()

    chat.input.value = 'satu'
    await chat.send()
    chat.input.value = 'dua'
    await chat.send()

    expect(spy.mock.calls[0][0]).toBe(spy.mock.calls[1][0])
  })

  it('treats a 404 from the history endpoint as an empty conversation', async () => {
    // A session id is generated client-side, so a brand-new conversation has no row
    // until the first POST /chat and GET /chat/history answers 404. That is the
    // contract, not a failure: the empty state must not show an error banner.
    const chat = useChat()
    chat.sessionId.value = 'session-under-test'
    vi.spyOn(api, 'fetchHistory').mockRejectedValue(
      Object.assign(new Error('unknown session'), {
        isAxiosError: true,
        response: { status: 404, data: { detail: 'unknown session' } },
      }),
    )

    await chat.loadHistory()

    expect(chat.messages.value).toHaveLength(0)
    expect(chat.error.value).toBeNull()
  })

  it('still surfaces a non-404 history failure', async () => {
    const chat = useChat()
    chat.sessionId.value = 'session-under-test'
    vi.spyOn(api, 'fetchHistory').mockRejectedValue(
      Object.assign(new Error('Service Unavailable'), {
        isAxiosError: true,
        response: { status: 503, data: { detail: 'local LLM unavailable' } },
      }),
    )

    await chat.loadHistory()

    expect(chat.error.value).toContain('local LLM unavailable')
  })
})
