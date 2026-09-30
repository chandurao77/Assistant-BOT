/**
 * @vitest-environment jsdom
 *
 * Unit tests for the conversationsApi service (server-side conversation fetch/actions).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchConversations,
  fetchConversationMessages,
  deleteConversationFromServer,
  submitFeedback,
} from './conversationsApi';

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('fetchConversations', () => {
  it('returns conversations on success', async () => {
    const mockData = [
      { id: 'c1', title: 'Hello', preview: '', createdAt: '2025-01-01', updatedAt: '2025-01-01' },
    ];
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    } as Response);

    const result = await fetchConversations();
    expect(result).toEqual(mockData);
    expect(fetch).toHaveBeenCalledWith('/api/conversations', expect.objectContaining({ headers: {} }));
  });

  it('returns empty array on failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false } as Response);
    const result = await fetchConversations();
    expect(result).toEqual([]);
  });

  it('includes auth header when token is stored', async () => {
    localStorage.setItem('assistant_bot_auth_token', 'test-jwt');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);

    await fetchConversations();
    expect(fetch).toHaveBeenCalledWith(
      '/api/conversations',
      expect.objectContaining({
        headers: { Authorization: 'Bearer test-jwt' },
      })
    );
  });
});

describe('fetchConversationMessages', () => {
  it('returns parsed messages on success', async () => {
    const serverMessages = {
      messages: [
        { id: 'm1', role: 'user', content: 'Hi', created_at: '2025-06-01T10:00:00Z' },
        { id: 'm2', role: 'assistant', content: 'Hello!', created_at: '2025-06-01T10:00:01Z' },
      ],
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(serverMessages),
    } as Response);

    const result = await fetchConversationMessages('c1');
    expect(result).toHaveLength(2);
    expect(result![0].status).toBe('complete');
    expect(result![0].timestamp).toBeInstanceOf(Date);
    expect(result![1].role).toBe('assistant');
  });

  it('returns null on 404', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false, status: 404 } as Response);
    const result = await fetchConversationMessages('bad-id');
    expect(result).toBeNull();
  });

  it('returns null on network error', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network error'));
    const result = await fetchConversationMessages('c1');
    expect(result).toBeNull();
  });
});

describe('deleteConversationFromServer', () => {
  it('sends DELETE request', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true } as Response);
    await deleteConversationFromServer('c1');
    expect(fetch).toHaveBeenCalledWith(
      '/api/conversations/c1',
      expect.objectContaining({ method: 'DELETE' })
    );
  });
});

describe('submitFeedback', () => {
  it('sends POST with feedback data', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true } as Response);
    await submitFeedback('msg1', 'conv1', 1);
    expect(fetch).toHaveBeenCalledWith(
      '/api/feedback',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message_id: 'msg1', conversation_id: 'conv1', value: 1 }),
      })
    );
  });

  it('skips request when value is null', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true } as Response);
    await submitFeedback('msg1', 'conv1', null);
    expect(fetch).not.toHaveBeenCalled();
  });
});
