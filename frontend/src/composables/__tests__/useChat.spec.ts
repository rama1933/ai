import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type StreamChatBody, type StreamEvent } from '../../services/api'
import { useChat } from '../useChat'
import { useSessions } from '../useSessions'

/** Queue one streaming turn: the spy yields the given events then finishes. */
function streamOf(events: StreamEvent[]): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(api, 'streamMessage').mockImplementation(function fakeStream() {
    return (async function* generated() {
      for (const event of events) yield event
    })()
  } as unknown as typeof api.streamMessage)
}

describe('useChat', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    // The session id now lives in the useSessions singleton; reset it so each
    // test mints its own. jsdom's Blob cannot go through the real object-url
    // functions, so stub them out.
    useSessions().activeId.value = null
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  })

  it('accumulates deltas onto one assistant message, not several', async () => {
    streamOf([
      { type: 'tool', name: 'rag_search' },
      { type: 'sources', sources: [{ filename: 'policy.pdf', score: 0.9 }] },
      { type: 'delta', text: 'Masa ' },
      { type: 'delta', text: 'retensi 5 tahun.' },
      {
        type: 'done',
        answer: 'Masa retensi 5 tahun.',
        tool_used: 'rag_search',
        sources: [{ filename: 'policy.pdf', score: 0.9 }],
      },
    ])

    const chat = useChat()
    chat.input.value = 'berapa lama retensi?'
    await chat.send()

    expect(chat.messages.value).toHaveLength(2)
    expect(chat.messages.value[0]).toMatchObject({ role: 'user', content: 'berapa lama retensi?' })
    expect(chat.messages.value[1]).toMatchObject({
      role: 'assistant',
      content: 'Masa retensi 5 tahun.',
      toolUsed: 'rag_search',
    })
    expect(chat.messages.value[1].sources?.[0].filename).toBe('policy.pdf')
    expect(chat.input.value).toBe('')
    expect(chat.isLoading.value).toBe(false)
    expect(chat.isStreaming.value).toBe(false)
  })

  it('does nothing when the input is blank', async () => {
    const spy = vi.spyOn(api, 'streamMessage')
    const chat = useChat()
    chat.input.value = '   '
    await chat.send()
    expect(spy).not.toHaveBeenCalled()
    expect(chat.messages.value).toHaveLength(0)
  })

  it('lands an error event in error and clears isStreaming', async () => {
    streamOf([
      { type: 'delta', text: 'sebagian ' },
      { type: 'error', detail: 'local LLM unavailable: dead' },
    ])

    const chat = useChat()
    chat.input.value = 'halo'
    await chat.send()

    expect(chat.error.value).toContain('local LLM unavailable')
    expect(chat.isStreaming.value).toBe(false)
    expect(chat.isLoading.value).toBe(false)
    // A truncated answer that arrives stays, matching the server's own policy.
    expect(chat.messages.value[1].content).toBe('sebagian ')
  })

  it('stops with stop(): aborts and keeps the partial text', async () => {
    vi.spyOn(api, 'streamMessage').mockImplementation(function fakeStream(
      _body: StreamChatBody,
      signal: AbortSignal | undefined,
    ) {
      return (async function* generated() {
        yield { type: 'delta', text: 'sebagian ' }
        await new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            const err = new Error('aborted')
            err.name = 'AbortError'
            reject(err)
          })
        })
      })()
    } as unknown as typeof api.streamMessage)

    const chat = useChat()
    chat.input.value = 'tanya panjang'
    const running = chat.send()
    await vi.waitFor(() => expect(chat.messages.value[1]?.content).toBe('sebagian '))
    chat.stop()
    await running

    expect(chat.messages.value).toHaveLength(2)
    expect(chat.messages.value[1].content).toBe('sebagian ')
    expect(chat.isStreaming.value).toBe(false)
    expect(chat.error.value).toBeNull()
  })

  it('retries with a fresh session id when the stored one answers 404', async () => {
    const spy = vi.spyOn(api, 'streamMessage')
    spy.mockImplementationOnce(function deadStream() {
      return (async function* generated() {
        throw Object.assign(new Error('unknown session'), { status: 404 })
      })()
    } as unknown as typeof api.streamMessage)
    spy.mockImplementationOnce(function goodStream() {
      return (async function* generated() {
        yield { type: 'done', answer: 'ok', tool_used: null, sources: [] }
      })()
    } as unknown as typeof api.streamMessage)

    const chat = useChat()
    chat.input.value = 'halo'
    await chat.send()

    expect(chat.error.value).toBeNull()
    expect(chat.messages.value[1].content).toBe('ok')
    expect(spy.mock.calls[0][0].session_id).not.toBe(spy.mock.calls[1][0].session_id)
  })

  it('attaches uploaded files, clears them after sending, and passes stored names', async () => {
    vi.spyOn(api, 'uploadFile').mockResolvedValue({
      filename: 'abc-struk.png',
      status: 'stored',
      kind: 'image',
      stored_name: 'abc-struk.png',
      display_name: 'struk.png',
      mime: 'image/png',
      size: 1,
    })
    const spy = streamOf([{ type: 'done', answer: 'ok', tool_used: 'image_ocr', sources: [] }])

    const chat = useChat()
    await chat.attach([new File(['x'], 'struk.png', { type: 'image/png' })])
    expect(chat.pending.value).toHaveLength(1)
    expect(chat.pending.value[0].storedName).toBe('abc-struk.png')

    chat.input.value = 'total berapa?'
    await chat.send()

    expect(spy.mock.calls[0][0].attachments).toEqual(['abc-struk.png'])
    expect(chat.pending.value).toHaveLength(0)
  })

  it('blocks send while an upload is in flight', async () => {
    let resolveUpload: (value: Awaited<ReturnType<typeof api.uploadFile>>) => void = () => {}
    vi.spyOn(api, 'uploadFile').mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpload = resolve
        }),
    )
    const spy = streamOf([{ type: 'done', answer: 'ok', tool_used: null, sources: [] }])

    const chat = useChat()
    void chat.attach([new File(['x'], 'slow.png', { type: 'image/png' })])
    await vi.waitFor(() => expect(chat.hasUploading.value).toBe(true))

    chat.input.value = 'halo'
    await chat.send()
    expect(spy).not.toHaveBeenCalled()

    resolveUpload({
      filename: 'abc-slow.png',
      status: 'stored',
      kind: 'image',
      stored_name: 'abc-slow.png',
      display_name: 'slow.png',
      mime: 'image/png',
      size: 1,
    })
    await vi.waitFor(() => expect(chat.hasUploading.value).toBe(false))

    await chat.send()
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy.mock.calls[0][0].attachments).toEqual(['abc-slow.png'])
  })

  it('reuses the same session id across messages', async () => {
    const spy = streamOf([{ type: 'done', answer: 'ok', tool_used: null, sources: [] }])
    const chat = useChat()

    chat.input.value = 'satu'
    await chat.send()
    chat.input.value = 'dua'
    await chat.send()

    expect(spy.mock.calls[0][0].session_id).toBe(spy.mock.calls[1][0].session_id)
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

describe('streamMessage SSE parsing', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('parses a frame split across two chunks exactly once', async () => {
    // The classic bug in a hand-rolled SSE client: the first frame arrives in
    // two network chunks and must be reassembled by the carry buffer.
    const first = 'data: {"type":"delta","text":"Ha'
    const second = 'lo"}\n\ndata: {"type":"done","answer":"Halo","tool_used":null,"sources":[]}\n\n'
    const encoder = new TextEncoder()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(encoder.encode(first))
              controller.enqueue(encoder.encode(second))
              controller.close()
            },
          }),
          { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
        ),
      ),
    )

    const events: StreamEvent[] = []
    for await (const event of api.streamMessage({ session_id: 's', message: 'm' })) {
      events.push(event)
    }
    vi.unstubAllGlobals()

    expect(events).toEqual([
      { type: 'delta', text: 'Halo' },
      { type: 'done', answer: 'Halo', tool_used: null, sources: [] },
    ])
  })

  it('drops a malformed frame without killing the stream', async () => {
    const encoder = new TextEncoder()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(encoder.encode('data: not-json\n\n'))
              controller.enqueue(encoder.encode('data: {"type":"delta","text":"ok"}\n\n'))
              controller.close()
            },
          }),
          { status: 200 },
        ),
      ),
    )

    const events: StreamEvent[] = []
    for await (const event of api.streamMessage({ session_id: 's', message: 'm' })) {
      events.push(event)
    }
    vi.unstubAllGlobals()

    expect(events).toEqual([{ type: 'delta', text: 'ok' }])
  })
})
