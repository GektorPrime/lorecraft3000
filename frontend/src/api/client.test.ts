import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, generatePanel, getCharacter, listCharacters } from './client'

const originalFetch = globalThis.fetch

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('api client', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn()
  })
  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('requests the correct relative /api/v1 URL', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(jsonResponse([]))
    await listCharacters()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/v1/characters',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    )
  })

  it('sends the browser timezone so budget boundaries use local time', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(jsonResponse([]))
    await listCharacters()
    const [, init] = vi.mocked(globalThis.fetch).mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('X-Timezone')).toBeTruthy()
  })

  it('returns parsed JSON on success', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({ id: 1, name: 'Elias', avatar_url: null, avatar_initials: 'EL' }),
    )
    const character = await getCharacter(1)
    expect(character.name).toBe('Elias')
  })

  it('throws an ApiError with message/type from the backend error envelope', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(async () =>
      jsonResponse(
        { detail: { message: 'character 9999 not found', type: 'CharacterNotFoundError' } },
        404,
      ),
    )
    let caught: unknown
    try {
      await getCharacter(9999)
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught).toMatchObject({
      message: 'character 9999 not found',
      type: 'CharacterNotFoundError',
      status: 404,
    })
  })

  it('sends generation requests with reviewed prompt and idempotency protection', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(async () => jsonResponse({ id: 7 }, 201))

    await generatePanel(3, 'reviewed-prompt-hash')
    await generatePanel(3, 'reviewed-prompt-hash')

    expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    const [url, init] = vi.mocked(globalThis.fetch).mock.calls[0]
    const headers = new Headers(init?.headers)
    const secondHeaders = new Headers(vi.mocked(globalThis.fetch).mock.calls[1][1]?.headers)
    expect(url).toBe('/api/v1/panels/3/generate')
    expect(init?.method).toBe('POST')
    expect(init?.signal).toBeInstanceOf(AbortSignal)
    expect(headers.get('Idempotency-Key')).toBeTruthy()
    expect(secondHeaders.get('Idempotency-Key')).not.toBe(headers.get('Idempotency-Key'))
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_prompt_hash: 'reviewed-prompt-hash',
    })
  })
})
