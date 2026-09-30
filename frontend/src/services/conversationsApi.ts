import type { ChatMessage, ConversationSummary, FeedbackValue } from '@/types';

const API_BASE = '/api';

/** Get the stored auth token for Authorization header */
function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('assistant_bot_auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface ServerMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(`${API_BASE}/conversations`, {
    headers: { ...getAuthHeaders() },
  });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchConversationMessages(id: string): Promise<ChatMessage[] | null> {
  try {
    const res = await fetch(`${API_BASE}/conversations/${id}`, {
      headers: { ...getAuthHeaders() },
    });
    if (!res.ok) return null;
    const data = await res.json();
    const msgs: ServerMessage[] = data.messages ?? [];
    return msgs.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      status: 'complete' as const,
      timestamp: new Date(m.created_at),
    }));
  } catch {
    return null;
  }
}

export async function renameConversationOnServer(id: string, title: string): Promise<void> {
  await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversationFromServer(id: string): Promise<void> {
  await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  });
}

export async function submitFeedback(
  messageId: string,
  conversationId: string,
  value: FeedbackValue,
  reason?: string | null,
  reasonText?: string | null,
  sourcePageIds?: string[],
): Promise<void> {
  if (value === null) return;
  const body: Record<string, unknown> = {
    message_id: messageId,
    conversation_id: conversationId,
    value,
  };
  if (reason) body.reason = reason;
  if (reasonText) body.reason_text = reasonText;
  if (sourcePageIds && sourcePageIds.length > 0) body.source_page_ids = sourcePageIds;
  await fetch(`${API_BASE}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(body),
  });
}

export async function exportConversation(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${id}/export`, {
    headers: { ...getAuthHeaders() },
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] || `assistant-bot-conversation.md`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
