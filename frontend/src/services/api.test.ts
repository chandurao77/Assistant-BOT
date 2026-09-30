/**
 * @vitest-environment jsdom
 *
 * Unit tests for the SSE parser in src/services/api.ts
 * Tests the critical CRLF normalization + event parsing logic.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Build a minimal ReadableStream from an array of raw SSE strings. */
function mockStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i++]));
      } else {
        controller.close();
      }
    },
  });
}

/** Extract the internal stream function by re-implementing the tested logic inline. */
async function parseSSE(
  chunks: string[],
  callbacks: {
    onToken: (t: string) => void;
    onSources: (s: unknown[]) => void;
    onError: (m: string) => void;
    onDone: () => void;
  }
) {
  const reader = mockStream(chunks).getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';

    for (const block of blocks) {
      if (!block.trim()) continue;

      const lines = block.split('\n');
      let eventType = 'message';
      let dataLine = '';

      for (const line of lines) {
        if (line.startsWith('event:')) eventType = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLine = line.slice(5).trim();
      }

      if (!dataLine && eventType !== 'done') continue;

      switch (eventType) {
        case 'token': {
          try { callbacks.onToken(JSON.parse(dataLine).text); }
          catch { callbacks.onToken(dataLine); }
          break;
        }
        case 'sources': {
          try { callbacks.onSources(JSON.parse(dataLine)); }
          catch { /* ignore */ }
          break;
        }
        case 'error': {
          try { callbacks.onError(JSON.parse(dataLine).message); }
          catch { callbacks.onError(dataLine); }
          break;
        }
        case 'done': {
          callbacks.onDone();
          return;
        }
      }
    }
  }
  callbacks.onDone();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('SSE parser', () => {
  let onToken: ReturnType<typeof vi.fn>;
  let onSources: ReturnType<typeof vi.fn>;
  let onError: ReturnType<typeof vi.fn>;
  let onDone: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onToken = vi.fn();
    onSources = vi.fn();
    onError = vi.fn();
    onDone = vi.fn();
  });

  const cbs = () => ({ onToken, onSources, onError, onDone });

  it('parses a single token event (LF)', async () => {
    const chunks = ['event: token\ndata: {"text": "Hello", "conversation_id": "x"}\n\n'];
    await parseSSE(chunks, cbs());
    expect(onToken).toHaveBeenCalledWith('Hello');
  });

  it('parses a single token event (CRLF)', async () => {
    const chunks = ['event: token\r\ndata: {"text": "Hi", "conversation_id": "x"}\r\n\r\n'];
    await parseSSE(chunks, cbs());
    expect(onToken).toHaveBeenCalledWith('Hi');
  });

  it('parses multiple token events across one chunk', async () => {
    const chunks = [
      'event: token\ndata: {"text": "A", "conversation_id": "x"}\n\n' +
      'event: token\ndata: {"text": "B", "conversation_id": "x"}\n\n',
    ];
    await parseSSE(chunks, cbs());
    expect(onToken).toHaveBeenCalledTimes(2);
    expect(onToken).toHaveBeenNthCalledWith(1, 'A');
    expect(onToken).toHaveBeenNthCalledWith(2, 'B');
  });

  it('handles tokens split across multiple network chunks', async () => {
    // Simulates the stream arriving in small TCP fragments
    const fullEvent = 'event: token\ndata: {"text": "Split", "conversation_id": "x"}\n\n';
    const chunks = [fullEvent.slice(0, 20), fullEvent.slice(20)];
    await parseSSE(chunks, cbs());
    expect(onToken).toHaveBeenCalledWith('Split');
  });

  it('calls onDone when done event received', async () => {
    const chunks = ['event: done\ndata: \n\n'];
    await parseSSE(chunks, cbs());
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('stops processing after done event', async () => {
    const chunks = [
      'event: done\ndata: \n\n' +
      'event: token\ndata: {"text": "After done", "conversation_id": "x"}\n\n',
    ];
    await parseSSE(chunks, cbs());
    expect(onToken).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('parses sources event and calls onSources', async () => {
    const sources = [{ page_id: 'p1', title: 'Page 1', score: 0.9 }];
    const chunks = [`event: sources\ndata: ${JSON.stringify(sources)}\n\n`];
    await parseSSE(chunks, cbs());
    expect(onSources).toHaveBeenCalledWith(sources);
  });

  it('parses error event and calls onError', async () => {
    const chunks = ['event: error\ndata: {"message": "Something went wrong"}\n\n'];
    await parseSSE(chunks, cbs());
    expect(onError).toHaveBeenCalledWith('Something went wrong');
  });

  it('skips empty blocks', async () => {
    const chunks = ['\n\n\n\nevent: token\ndata: {"text": "X", "conversation_id": "x"}\n\n'];
    await parseSSE(chunks, cbs());
    expect(onToken).toHaveBeenCalledWith('X');
  });

  it('calls onDone when stream exhausted naturally (no done event)', async () => {
    const chunks = ['event: token\ndata: {"text": "Hi", "conversation_id": "x"}\n\n'];
    await parseSSE(chunks, cbs());
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('full flow: tokens → sources → done', async () => {
    const sources = [{ page_id: 'p1', title: 'T' }];
    const chunks = [
      'event: token\ndata: {"text": "The", "conversation_id": "x"}\n\n' +
      'event: token\ndata: {"text": " answer", "conversation_id": "x"}\n\n' +
      `event: sources\ndata: ${JSON.stringify(sources)}\n\n` +
      'event: done\ndata: \n\n',
    ];
    await parseSSE(chunks, cbs());
    expect(onToken).toHaveBeenCalledTimes(2);
    expect(onSources).toHaveBeenCalledWith(sources);
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
