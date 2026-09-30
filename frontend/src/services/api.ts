import type { SourceDocument, StreamTokenEvent } from '@/types';

const API_BASE = '/api';

/** Get the stored auth token for Authorization header */
function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('assistant_bot_auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface StreamCallbacks {
  onToken: (token: string, conversationId?: string) => void;
  onSources: (sources: SourceDocument[], confidence?: string, confidenceScore?: number) => void;
  onError: (message: string) => void;
  onDone: () => void;
  onQueryCorrected?: (original: string, corrected: string) => void;
  onStatus?: (step: string, message: string) => void;
}

/**
 * Stream a chat response via Server-Sent Events.
 * Returns an AbortController so the caller can cancel mid-stream.
 */
export function streamChat(
  question: string,
  conversationId: string | null,
  callbacks: StreamCallbacks,
  spaceKeys?: string[]
): AbortController {
  const controller = new AbortController();

  _streamWithEventSource(`${API_BASE}/chat/stream`, question, conversationId, callbacks, controller, spaceKeys).catch(
    (err: Error) => {
      if (err.name !== 'AbortError') {
        callbacks.onError('Connection error. Please check your network.');
      }
    }
  );

  return controller;
}

/**
 * Proper SSE implementation using raw fetch + event-type tracking.
 */
async function _streamWithEventSource(
  url: string,
  question: string,
  conversationId: string | null,
  callbacks: StreamCallbacks,
  controller: AbortController,
  spaceKeys?: string[]
): Promise<void> {
  // Apply a 120s timeout to prevent hanging connections
  const timeoutId = setTimeout(() => controller.abort(), 120_000);

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({
      question,
      conversation_id: conversationId,
      ...(spaceKeys && spaceKeys.length > 0 ? { space_keys: spaceKeys } : {}),
    }),
    signal: controller.signal,
  });

  clearTimeout(timeoutId);

  if (!response.ok || !response.body) {
    callbacks.onError(`Server error: ${response.status}`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // Normalize \r\n to \n so the block splitter works regardless of
    // whether the server sends CRLF or LF line endings.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';

    for (const block of blocks) {
      if (!block.trim()) continue;

      const lines = block.split('\n');
      let eventType = 'message';
      let dataLine = '';

      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLine = line.slice(5).trim();
        }
      }

      if (eventType === 'ping' || (!dataLine && eventType !== 'done')) continue;

      switch (eventType) {
        case 'token': {
          try {
            const parsed: StreamTokenEvent = JSON.parse(dataLine);
            callbacks.onToken(parsed.text, parsed.conversation_id);
          } catch {
            callbacks.onToken(dataLine);
          }
          break;
        }
        case 'sources': {
          try {
            const parsed = JSON.parse(dataLine);
            // Support both old format (plain array) and new format ({sources, confidence})
            if (Array.isArray(parsed)) {
              callbacks.onSources(parsed);
            } else {
              callbacks.onSources(parsed.sources || [], parsed.confidence, parsed.confidence_score);
            }
          } catch {
            /* ignore parse errors for sources */
          }
          break;
        }
        case 'query_corrected': {
          try {
            const { original, corrected } = JSON.parse(dataLine);
            callbacks.onQueryCorrected?.(original, corrected);
          } catch { /* ignore */ }
          break;
        }
        case 'status': {
          try {
            const { step, message } = JSON.parse(dataLine);
            callbacks.onStatus?.(step, message);
          } catch { /* ignore */ }
          break;
        }
        case 'error': {
          try {
            const { message } = JSON.parse(dataLine);
            callbacks.onError(message);
          } catch {
            callbacks.onError(dataLine);
          }
          break;
        }
        case 'done': {
          callbacks.onDone();
          return;
        }
      }
    }
  }

  // Stream ended naturally (reader exhausted) — mark as done
  callbacks.onDone();
}

export async function triggerIngestion(
  spaceKeys?: string[],
  fullRefresh = false
): Promise<void> {
  const response = await fetch(`${API_BASE}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ space_keys: spaceKeys, full_refresh: fullRefresh }),
  });
  if (!response.ok) throw new Error(`Ingestion trigger failed: ${response.status}`);
}

export async function fetchSuggestions(currentQuestion?: string): Promise<string[]> {
  try {
    const params = currentQuestion ? `?q=${encodeURIComponent(currentQuestion)}` : '';
    const res = await fetch(`${API_BASE}/chat/suggestions${params}`, {
      headers: { ...getAuthHeaders() },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.suggestions ?? [];
  } catch {
    return [];
  }
}

export async function getIngestionStatus(): Promise<unknown> {
  const response = await fetch(`${API_BASE}/ingest/status`);
  return response.json();
}

export async function getSpaces(): Promise<{ space_key: string; space_name: string }[]> {
  try {
    const response = await fetch(`${API_BASE}/health/spaces`, {
      headers: { ...getAuthHeaders() },
    });
    if (!response.ok) return [];
    return response.json();
  } catch {
    return [];
  }
}

export interface UploadResult {
  status: string;
  upload_id: string;
  filename: string;
  chunks: number;
  conversation_id: string;
}

export async function uploadFile(
  file: File,
  conversationId?: string | null
): Promise<UploadResult> {
  const formData = new FormData();
  formData.append('file', file);
  const url = conversationId
    ? `${API_BASE}/upload?conversation_id=${encodeURIComponent(conversationId)}`
    : `${API_BASE}/upload`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: formData,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(body.detail || `Upload failed: ${response.status}`);
  }
  return response.json();
}

export async function deleteUpload(uploadId: string): Promise<void> {
  await fetch(`${API_BASE}/upload/${encodeURIComponent(uploadId)}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  });
}
