import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../../services/api'
import { useChat } from '../useChat'

describe('useChat', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
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
    vi.spyOn(api, 'uploadFile').mockResolvedValue({ filename: 'abc-struk.png', status: 'stored', kind: 'image' })
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
})
