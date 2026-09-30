import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import type { ChatMessage, ChatState, FeedbackValue, SourceDocument, UploadedFile } from '@/types';
import { streamChat, uploadFile as apiUploadFile, deleteUpload as apiDeleteUpload } from '@/services/api';
import { submitFeedback as apiFeedback } from '@/services/conversationsApi';

// ── localStorage helpers ───────────────────────────────────────────────────────
const LS_PREFIX = 'confluence_chat_';
const LEGACY_KEY = 'confluence_chat_history';
const ACTIVE_CONV_KEY = 'confluence_active_conversation';
const MAX_PERSISTED_MESSAGES = 50;

function storageKey(conversationId: string | null): string {
  return conversationId ? `${LS_PREFIX}${conversationId}` : LEGACY_KEY;
}

function loadFromStorage(
  conversationId?: string | null
): Pick<ChatState, 'messages' | 'conversationId'> {
  try {
    const key = conversationId ? storageKey(conversationId) : LEGACY_KEY;
    const raw = localStorage.getItem(key);
    if (!raw) return { messages: [], conversationId: conversationId ?? null };
    const parsed = JSON.parse(raw);
    const messages: ChatMessage[] = (parsed.messages ?? []).map((m: ChatMessage) => ({
      ...m,
      timestamp: new Date(m.timestamp),
      status: m.status === 'streaming' ? 'complete' : m.status,
    }));
    return { messages, conversationId: parsed.conversationId ?? conversationId ?? null };
  } catch {
    return { messages: [], conversationId: conversationId ?? null };
  }
}

function saveToStorage(state: ChatState): void {
  try {
    const key = storageKey(state.conversationId);
    // Mark any still-streaming messages as complete before persisting
    const messages = state.messages.map((m) =>
      m.status === 'streaming' ? { ...m, status: 'complete' as const } : m
    );
    const toSave = {
      conversationId: state.conversationId,
      messages: messages.slice(-MAX_PERSISTED_MESSAGES),
    };
    localStorage.setItem(key, JSON.stringify(toSave));
  } catch {
    // Storage full or unavailable — fail silently
  }
}

/** Save a background stream's accumulated result directly to localStorage for its conversation. */
function _saveBackgroundStream(acc: { convId: string; userMsg: ChatMessage; assistantMsg: ChatMessage }): void {
  try {
    const key = storageKey(acc.convId);
    const existing = loadFromStorage(acc.convId);
    let msgs = existing.messages;
    // Add or update the user message
    if (!msgs.some((m) => m.id === acc.userMsg.id)) {
      msgs.push(acc.userMsg);
    }
    // Add or update the assistant message
    const idx = msgs.findIndex((m) => m.id === acc.assistantMsg.id);
    if (idx >= 0) {
      msgs[idx] = acc.assistantMsg;
    } else {
      msgs.push(acc.assistantMsg);
    }
    msgs = msgs.slice(-MAX_PERSISTED_MESSAGES);
    localStorage.setItem(key, JSON.stringify({ conversationId: acc.convId, messages: msgs }));
  } catch {
    // fail silently
  }
}

// ── State ─────────────────────────────────────────────────────────────────────
function buildInitialState(): ChatState {
  const activeId = localStorage.getItem(ACTIVE_CONV_KEY);
  const persisted = loadFromStorage(activeId);
  return { ...persisted, isLoading: false, error: null, correctedQuery: null, selectedSpaces: [], streamStatus: null };
}

type Action =
  | {
      type: 'START_STREAM';
      payload: { userMsgId: string; assistantMsgId: string; content: string };
    }
  | { type: 'APPEND_TOKEN'; payload: { id: string; token: string } }
  | { type: 'SET_SOURCES'; payload: { id: string; sources: SourceDocument[]; confidence?: string; confidenceScore?: number } }
  | { type: 'SET_MESSAGE_STATUS'; payload: { id: string; status: ChatMessage['status'] } }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_CONVERSATION_ID'; payload: string }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'SET_FEEDBACK'; payload: { id: string; feedback: FeedbackValue } }
  | { type: 'SET_CORRECTED_QUERY'; payload: { original: string; corrected: string } | null }
  | { type: 'SET_SELECTED_SPACES'; payload: string[] }
  | { type: 'SET_STREAM_STATUS'; payload: string | null }
  | { type: 'LOAD_CONVERSATION'; payload: { messages: ChatMessage[]; conversationId: string } }
  | { type: 'ADD_MESSAGE'; payload: ChatMessage }
  | { type: 'PREPARE_RETRY' }
  | { type: 'CLEAR' };

function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case 'START_STREAM': {
      const { userMsgId, assistantMsgId, content } = action.payload;
      return {
        ...state,
        isLoading: true,
        error: null,
        correctedQuery: null,
        messages: [
          ...state.messages,
          {
            id: userMsgId,
            role: 'user',
            content,
            status: 'complete',
            timestamp: new Date(),
          },
          {
            id: assistantMsgId,
            role: 'assistant',
            content: '',
            sources: [],
            status: 'streaming',
            timestamp: new Date(),
          },
        ],
      };
    }

    case 'APPEND_TOKEN':
      return {
        ...state,
        streamStatus: null,
        messages: state.messages.map((m) =>
          m.id === action.payload.id
            ? { ...m, content: m.content + action.payload.token }
            : m
        ),
      };

    case 'SET_SOURCES':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.payload.id ? { ...m, sources: action.payload.sources, confidence: action.payload.confidence, confidenceScore: action.payload.confidenceScore } : m
        ),
      };

    case 'SET_MESSAGE_STATUS':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.payload.id ? { ...m, status: action.payload.status } : m
        ),
      };

    case 'SET_LOADING':
      return { ...state, isLoading: action.payload };

    case 'SET_CONVERSATION_ID':
      return { ...state, conversationId: action.payload };

    case 'SET_ERROR':
      return { ...state, error: action.payload };

    case 'SET_FEEDBACK':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.payload.id ? { ...m, feedback: action.payload.feedback } : m
        ),
      };

    case 'SET_CORRECTED_QUERY':
      return { ...state, correctedQuery: action.payload };

    case 'SET_SELECTED_SPACES':
      return { ...state, selectedSpaces: action.payload };

    case 'SET_STREAM_STATUS':
      return { ...state, streamStatus: action.payload };

    case 'LOAD_CONVERSATION':
      return {
        ...state,
        messages: action.payload.messages,
        conversationId: action.payload.conversationId,
        isLoading: false,
        correctedQuery: null,
        error: null,
      };

    case 'ADD_MESSAGE':
      return {
        ...state,
        messages: [...state.messages, action.payload],
      };

    case 'PREPARE_RETRY': {
      const msgs = [...state.messages];
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant' && msgs[i].status === 'error') {
          msgs.splice(i, 1);
          if (i > 0 && msgs[i - 1].role === 'user') {
            msgs.splice(i - 1, 1);
          }
          break;
        }
      }
      return { ...state, messages: msgs, error: null };
    }

    case 'CLEAR':
      return { messages: [], isLoading: false, conversationId: null, error: null, correctedQuery: null, selectedSpaces: state.selectedSpaces, streamStatus: null };

    default:
      return state;
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export function useChat() {
  const [state, dispatch] = useReducer(reducer, undefined, buildInitialState);
  const abortRef = useRef<AbortController | null>(null);

  // Ref to accumulate stream content independently so background streams can save results
  const streamAccRef = useRef<{
    convId: string;
    userMsg: ChatMessage;
    assistantMsg: ChatMessage;
  } | null>(null);

  // Persist messages and active conversation ID to localStorage (debounced during streaming)
  useEffect(() => {
    const timer = setTimeout(() => {
      saveToStorage(state);
    }, 300);
    if (state.conversationId) {
      localStorage.setItem(ACTIVE_CONV_KEY, state.conversationId);
    } else {
      localStorage.removeItem(ACTIVE_CONV_KEY);
    }
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.messages, state.conversationId]);

  const sendMessage = useCallback(
    (question: string) => {
      if (!question.trim() || state.isLoading) return;

      abortRef.current?.abort();

      const userMsgId = uuidv4();
      const assistantMsgId = uuidv4();
      // Generate a conversationId immediately so the chat is always trackable
      const convId = state.conversationId ?? uuidv4();

      if (!state.conversationId) {
        dispatch({ type: 'SET_CONVERSATION_ID', payload: convId });
      }

      // Initialise the background accumulator so the stream can save even if user switches away
      const userMsg: ChatMessage = { id: userMsgId, role: 'user', content: question, status: 'complete', timestamp: new Date() };
      const assistantMsg: ChatMessage = { id: assistantMsgId, role: 'assistant', content: '', sources: [], status: 'streaming', timestamp: new Date() };
      streamAccRef.current = { convId, userMsg, assistantMsg: { ...assistantMsg } };

      dispatch({ type: 'START_STREAM', payload: { userMsgId, assistantMsgId, content: question } });

      abortRef.current = streamChat(question, convId, {
        onToken: (token) => {
          dispatch({ type: 'APPEND_TOKEN', payload: { id: assistantMsgId, token } });
          // Also accumulate in background ref
          if (streamAccRef.current?.convId === convId) {
            streamAccRef.current.assistantMsg.content += token;
          }
        },
        onQueryCorrected: (original, corrected) => {
          dispatch({ type: 'SET_CORRECTED_QUERY', payload: { original, corrected } });
        },
        onStatus: (step, message) => {
          if (step === 'history_truncated') {
            // Add a persistent system-style message so the user knows context was trimmed
            dispatch({
              type: 'ADD_MESSAGE',
              payload: {
                id: uuidv4(),
                role: 'assistant',
                content: `⚠️ ${message}`,
                status: 'complete',
                timestamp: new Date(),
              },
            });
          } else {
            dispatch({ type: 'SET_STREAM_STATUS', payload: message });
          }
        },
        onSources: (sources, confidence, confidenceScore) => {
          dispatch({ type: 'SET_SOURCES', payload: { id: assistantMsgId, sources, confidence, confidenceScore } });
          if (streamAccRef.current?.convId === convId) {
            streamAccRef.current.assistantMsg.sources = sources;
            streamAccRef.current.assistantMsg.confidence = confidence;
            streamAccRef.current.assistantMsg.confidenceScore = confidenceScore;
          }
        },
        onError: (message) => {
          dispatch({
            type: 'SET_MESSAGE_STATUS',
            payload: { id: assistantMsgId, status: 'error' },
          });
          dispatch({ type: 'SET_ERROR', payload: message });
          dispatch({ type: 'SET_LOADING', payload: false });
          // Save the error state to localStorage for the original conversation
          if (streamAccRef.current?.convId === convId) {
            streamAccRef.current.assistantMsg.status = 'error';
            _saveBackgroundStream(streamAccRef.current);
            streamAccRef.current = null;
          }
        },
        onDone: () => {
          dispatch({
            type: 'SET_MESSAGE_STATUS',
            payload: { id: assistantMsgId, status: 'complete' },
          });
          dispatch({ type: 'SET_LOADING', payload: false });
          dispatch({ type: 'SET_STREAM_STATUS', payload: null });
          // Save the completed answer to localStorage for the original conversation
          if (streamAccRef.current?.convId === convId) {
            streamAccRef.current.assistantMsg.status = 'complete';
            _saveBackgroundStream(streamAccRef.current);
            streamAccRef.current = null;
          }
        },
      }, state.selectedSpaces.length > 0 ? state.selectedSpaces : undefined);
    },
    [state.isLoading, state.conversationId, state.selectedSpaces]
  );

  const clearConversation = useCallback(() => {
    // Persist the current conversation so the sidebar can still load it
    if (state.conversationId && state.messages.length > 0) {
      saveToStorage(state);
    }
    // If streaming, DON'T abort — let the stream finish in background and save via streamAccRef
    if (!state.isLoading) {
      abortRef.current?.abort();
    }
    abortRef.current = null;
    dispatch({ type: 'CLEAR' });
  }, [state]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    // Mark any streaming messages as complete in state
    state.messages.forEach((m) => {
      if (m.status === 'streaming') {
        dispatch({ type: 'SET_MESSAGE_STATUS', payload: { id: m.id, status: 'complete' } });
      }
    });
    dispatch({ type: 'SET_LOADING', payload: false });
  }, [state.messages]);

  const loadConversation = useCallback((messages: ChatMessage[], conversationId: string) => {
    // Save the current conversation before switching so partial streaming content isn't lost
    saveToStorage(state);
    // If streaming, DON'T abort — let the stream finish in background
    if (!state.isLoading) {
      abortRef.current?.abort();
    }
    abortRef.current = null;
    dispatch({ type: 'LOAD_CONVERSATION', payload: { messages, conversationId } });
  }, [state]);

  const rateFeedback = useCallback(
    async (messageId: string, value: FeedbackValue, reason?: string | null, reasonText?: string | null) => {
      dispatch({ type: 'SET_FEEDBACK', payload: { id: messageId, feedback: value } });
      if (state.conversationId && value !== null) {
        try {
          // For "outdated_information", include source page IDs so the backend can auto-reingest
          let sourcePageIds: string[] | undefined;
          if (value === -1 && reason === 'outdated_information') {
            const msg = state.messages.find(m => m.id === messageId);
            if (msg?.sources) {
              sourcePageIds = msg.sources
                .filter(s => !s.space_key.startsWith('__'))
                .map(s => s.page_id);
            }
          }
          await apiFeedback(messageId, state.conversationId, value, reason, reasonText, sourcePageIds);
        } catch {
          // non-critical — don't surface feedback errors to the user
        }
      }
    },
    [state.conversationId, state.messages]
  );

  const retryLastMessage = useCallback(() => {
    const lastUser = [...state.messages].reverse().find((m) => m.role === 'user');
    if (lastUser && !state.isLoading) {
      // Remove the failed user+assistant pair so sendMessage creates a clean replacement
      dispatch({ type: 'PREPARE_RETRY' });
      sendMessage(lastUser.content);
    }
  }, [state.messages, state.isLoading, sendMessage]);

  const setSelectedSpaces = useCallback((spaces: string[]) => {
    dispatch({ type: 'SET_SELECTED_SPACES', payload: spaces });
  }, []);

  // ── Upload state ──────────────────────────────────────────────────────────
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const handleUpload = useCallback(async (file: File) => {
    setIsUploading(true);
    try {
      // Ensure we have a conversationId so uploaded chunks belong to this session
      let convId = state.conversationId;
      if (!convId) {
        convId = uuidv4();
        dispatch({ type: 'SET_CONVERSATION_ID', payload: convId });
      }
      const result = await apiUploadFile(file, convId);
      setUploadedFiles((prev) => [
        ...prev,
        { upload_id: result.upload_id, filename: result.filename, chunks: result.chunks },
      ]);
      // Add a confirmation message so the user knows the file is ready
      dispatch({
        type: 'ADD_MESSAGE',
        payload: {
          id: uuidv4(),
          role: 'assistant',
          content: `File **${result.filename}** uploaded successfully (${result.chunks} chunks indexed). You can now ask questions about it.`,
          status: 'complete',
          timestamp: new Date(),
        },
      });
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err instanceof Error ? err.message : 'Upload failed' });
    } finally {
      setIsUploading(false);
    }
  }, [state.conversationId]);

  const removeUpload = useCallback(async (uploadId: string) => {
    setUploadedFiles((prev) => prev.filter((f) => f.upload_id !== uploadId));
    try {
      await apiDeleteUpload(uploadId);
    } catch {
      // non-critical — chunks will be cleaned up by other means
    }
  }, []);

  // Clear uploaded files when conversation is cleared
  const clearConversationWithUploads = useCallback(() => {
    // Clean up uploaded file chunks in Qdrant
    for (const f of uploadedFiles) {
      apiDeleteUpload(f.upload_id).catch(() => {});
    }
    setUploadedFiles([]);
    clearConversation();
  }, [clearConversation, uploadedFiles]);

  return {
    ...state,
    sendMessage,
    clearConversation: clearConversationWithUploads,
    stopStreaming,
    loadConversation,
    rateFeedback,
    retryLastMessage,
    setSelectedSpaces,
    uploadedFiles,
    isUploading,
    handleUpload,
    removeUpload,
  };
}

