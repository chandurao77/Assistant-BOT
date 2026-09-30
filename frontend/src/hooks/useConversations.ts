import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage, ConversationSummary } from '@/types';
import { fetchConversations, deleteConversationFromServer, renameConversationOnServer } from '@/services/conversationsApi';

const CONV_LIST_KEY = 'confluence_conversations_list';
const CONV_DATA_PREFIX = 'confluence_chat_';

export interface ConversationData {
  messages: ChatMessage[];
  conversationId: string;
}

function loadList(): ConversationSummary[] {
  try {
    const raw = localStorage.getItem(CONV_LIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveList(list: ConversationSummary[]): void {
  try {
    localStorage.setItem(CONV_LIST_KEY, JSON.stringify(list));
  } catch { /* ignore */ }
}

function loadConvData(id: string): ConversationData | null {
  try {
    const raw = localStorage.getItem(`${CONV_DATA_PREFIX}${id}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const messages: ChatMessage[] = (parsed.messages ?? []).map((m: ChatMessage) => ({
      ...m,
      timestamp: new Date(m.timestamp),
      status: m.status === 'streaming' ? 'complete' : m.status,
    }));
    return { messages, conversationId: parsed.conversationId ?? id };
  } catch {
    return null;
  }
}

function removeConvData(id: string): void {
  try { localStorage.removeItem(`${CONV_DATA_PREFIX}${id}`); } catch { /* ignore */ }
}

export function useConversations() {
  const [conversations, setConversations] = useState<ConversationSummary[]>(loadList);
  const hasFetched = useRef(false);

  // Fetch from server on mount — merge with localStorage cache
  useEffect(() => {
    if (hasFetched.current) return;
    hasFetched.current = true;

    fetchConversations()
      .then((serverList) => {
        if (serverList.length > 0) {
          setConversations((local) => {
            // Merge: server is source of truth, but preserve local-only fields (folderId)
            const localMap = new Map(local.map((c) => [c.id, c]));
            const merged = serverList.map((sc) => {
              const lc = localMap.get(sc.id);
              return lc ? { ...sc, folderId: lc.folderId } : sc;
            });
            // Add any local-only conversations not on server (offline/unsaved)
            const serverIds = new Set(serverList.map((c) => c.id));
            const localOnly = local.filter((c) => !serverIds.has(c.id));
            return [...merged, ...localOnly];
          });
        }
      })
      .catch(() => {
        // Server unavailable — keep localStorage data as fallback
      });
  }, []);

  // Sync to localStorage whenever list changes
  useEffect(() => {
    saveList(conversations);
  }, [conversations]);

  /**
   * Register or update a conversation in the list.
   * Called by ChatContainer whenever a new message arrives.
   */
  const upsertConversation = useCallback(
    (id: string, title: string, preview: string) => {
      setConversations((prev) => {
        const now = new Date().toISOString();
        const existing = prev.find((c) => c.id === id);
        if (existing) {
          return prev.map((c) =>
            c.id === id
              ? { ...c, title: c.title === 'New Conversation' ? title : c.title, preview, updatedAt: now }
              : c
          );
        }
        return [
          { id, title, preview, createdAt: now, updatedAt: now },
          ...prev,
        ];
      });
    },
    []
  );

  const renameConversation = useCallback((id: string, newTitle: string) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === id ? { ...c, title: newTitle, updatedAt: new Date().toISOString() } : c
      )
    );
    // Fire-and-forget server rename
    renameConversationOnServer(id, newTitle).catch(() => {});
  }, []);

  const deleteConversation = useCallback((id: string) => {
    removeConvData(id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
    // Fire-and-forget server delete
    deleteConversationFromServer(id).catch(() => {});
  }, []);

  const moveToFolder = useCallback((conversationId: string, folderId: string | null) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === conversationId ? { ...c, folderId, updatedAt: new Date().toISOString() } : c
      )
    );
  }, []);

  const loadConversationData = useCallback((id: string): ConversationData | null => {
    return loadConvData(id);
  }, []);

  return { conversations, upsertConversation, renameConversation, deleteConversation, moveToFolder, loadConversationData };
}
