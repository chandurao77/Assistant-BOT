/**
 * @vitest-environment jsdom
 *
 * Unit tests for the useConversations hook (localStorage-backed conversation list).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useConversations } from './useConversations';

const CONV_LIST_KEY = 'confluence_conversations_list';
const CONV_DATA_PREFIX = 'confluence_chat_';

beforeEach(() => {
  localStorage.clear();
});

describe('useConversations', () => {
  it('starts with empty conversations list', () => {
    const { result } = renderHook(() => useConversations());
    expect(result.current.conversations).toEqual([]);
  });

  it('loads conversations from localStorage on init', () => {
    const existing = [
      { id: 'c1', title: 'Hello', preview: 'Hi', createdAt: '2025-01-01T00:00:00Z', updatedAt: '2025-01-01T00:00:00Z' },
    ];
    localStorage.setItem(CONV_LIST_KEY, JSON.stringify(existing));
    const { result } = renderHook(() => useConversations());
    expect(result.current.conversations).toHaveLength(1);
    expect(result.current.conversations[0].title).toBe('Hello');
  });

  it('upsertConversation creates a new conversation', () => {
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'Test Conv', 'Some preview');
    });

    expect(result.current.conversations).toHaveLength(1);
    expect(result.current.conversations[0].id).toBe('c1');
    expect(result.current.conversations[0].title).toBe('Test Conv');
    expect(result.current.conversations[0].preview).toBe('Some preview');
  });

  it('upsertConversation updates existing conversation preview', () => {
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'Title', 'First msg');
    });
    act(() => {
      result.current.upsertConversation('c1', 'Updated Title', 'Second msg');
    });

    expect(result.current.conversations).toHaveLength(1);
    // Title should stay the same (only updates if "New Conversation")
    expect(result.current.conversations[0].title).toBe('Title');
    expect(result.current.conversations[0].preview).toBe('Second msg');
  });

  it('upsertConversation updates title when it is "New Conversation"', () => {
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'New Conversation', 'First msg');
    });
    act(() => {
      result.current.upsertConversation('c1', 'Real Title', 'Second msg');
    });

    expect(result.current.conversations[0].title).toBe('Real Title');
  });

  it('renameConversation updates the title', () => {
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'Old', 'preview');
    });
    act(() => {
      result.current.renameConversation('c1', 'Renamed');
    });

    expect(result.current.conversations[0].title).toBe('Renamed');
  });

  it('deleteConversation removes conversation and its data', () => {
    localStorage.setItem(`${CONV_DATA_PREFIX}c1`, JSON.stringify({ messages: [], conversationId: 'c1' }));
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'To Delete', 'x');
    });
    act(() => {
      result.current.deleteConversation('c1');
    });

    expect(result.current.conversations).toHaveLength(0);
    expect(localStorage.getItem(`${CONV_DATA_PREFIX}c1`)).toBeNull();
  });

  it('moveToFolder sets the folderId on a conversation', () => {
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'Conv', 'preview');
    });
    act(() => {
      result.current.moveToFolder('c1', 'folder_abc');
    });

    expect(result.current.conversations[0].folderId).toBe('folder_abc');
  });

  it('moveToFolder with null removes from folder', () => {
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'Conv', 'preview');
    });
    act(() => {
      result.current.moveToFolder('c1', 'folder_abc');
    });
    act(() => {
      result.current.moveToFolder('c1', null);
    });

    expect(result.current.conversations[0].folderId).toBeNull();
  });

  it('loadConversationData returns stored conversation data', () => {
    const data = {
      messages: [
        { id: 'm1', role: 'user', content: 'Hello', status: 'complete', timestamp: '2025-01-01T00:00:00Z' },
      ],
      conversationId: 'c1',
    };
    localStorage.setItem(`${CONV_DATA_PREFIX}c1`, JSON.stringify(data));

    const { result } = renderHook(() => useConversations());
    const loaded = result.current.loadConversationData('c1');
    expect(loaded).not.toBeNull();
    expect(loaded!.messages).toHaveLength(1);
    expect(loaded!.messages[0].content).toBe('Hello');
    expect(loaded!.messages[0].timestamp).toBeInstanceOf(Date);
  });

  it('loadConversationData returns null for missing conversation', () => {
    const { result } = renderHook(() => useConversations());
    expect(result.current.loadConversationData('nonexistent')).toBeNull();
  });

  it('loadConversationData converts streaming status to complete', () => {
    const data = {
      messages: [
        { id: 'm1', role: 'assistant', content: 'reply', status: 'streaming', timestamp: '2025-01-01T00:00:00Z' },
      ],
      conversationId: 'c1',
    };
    localStorage.setItem(`${CONV_DATA_PREFIX}c1`, JSON.stringify(data));

    const { result } = renderHook(() => useConversations());
    const loaded = result.current.loadConversationData('c1');
    expect(loaded!.messages[0].status).toBe('complete');
  });

  it('persists conversations to localStorage on change', () => {
    const { result } = renderHook(() => useConversations());

    act(() => {
      result.current.upsertConversation('c1', 'Persisted', 'data');
    });

    const stored = JSON.parse(localStorage.getItem(CONV_LIST_KEY) || '[]');
    expect(stored).toHaveLength(1);
    expect(stored[0].title).toBe('Persisted');
  });
});
