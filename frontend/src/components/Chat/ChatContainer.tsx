import { useCallback, useEffect, useRef, useState } from 'react';
import { useChat } from '@/hooks/useChat';
import { useConversations } from '@/hooks/useConversations';
import { useFolders } from '@/hooks/useFolders';
import { fetchConversationMessages, deleteConversationFromServer } from '@/services/conversationsApi';
import { getSpaces, triggerIngestion, getIngestionStatus } from '@/services/api';
import { useAuth } from '@/contexts/AuthContext';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { QuerySuggestions } from './QuerySuggestions';
import { ConversationSidebar } from '@/components/Sidebar/ConversationSidebar';

export function ChatContainer() {
  const {
    messages,
    isLoading,
    error,
    conversationId,
    selectedSpaces,
    streamStatus,
    sendMessage,
    clearConversation,
    stopStreaming,
    loadConversation,
    rateFeedback,
    retryLastMessage,
    setSelectedSpaces,
    uploadedFiles,
    isUploading,
    handleUpload,
    removeUpload,
  } = useChat();

  const { conversations, upsertConversation, renameConversation, deleteConversation, moveToFolder, loadConversationData } =
    useConversations();

  const { folders, createFolder, renameFolder, deleteFolder } = useFolders();

  const [availableSpaces, setAvailableSpaces] = useState<{ space_key: string; space_name: string }[]>([]);
  const [showSpaceFilter, setShowSpaceFilter] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const spaceFilterRef = useRef<HTMLDivElement>(null);

  const { user: authUser } = useAuth();
  const isAdmin = authUser?.role === 'admin';

  // Ingestion state
  const [ingestRunning, setIngestRunning] = useState(false);
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const ingestPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [ingestPercent, setIngestPercent] = useState(0);

  const pollIngestionStatus = useCallback(() => {
    if (ingestPollRef.current) return;
    ingestPollRef.current = setInterval(async () => {
      try {
        const status = (await getIngestionStatus()) as { status?: string; pages_processed?: number; current_page?: number; total_pages?: number; percent?: number; source?: string };
        if (status.status === 'running') {
          setIngestRunning(true);
          const current = status.current_page ?? status.pages_processed ?? 0;
          const total = status.total_pages ?? 0;
          const pct = status.percent ?? 0;
          setIngestPercent(pct);
          const src = status.source ? `${status.source}: ` : '';
          setIngestMessage(total > 0
            ? `${src}${current}/${total} pages (${pct}%)`
            : `${src}${current} pages processed…`
          );
        } else {
          setIngestRunning(false);
          setIngestPercent(0);
          setIngestMessage(status.status === 'completed' ? 'Ingestion complete' : null);
          clearInterval(ingestPollRef.current!);
          ingestPollRef.current = null;
        }
      } catch {
        clearInterval(ingestPollRef.current!);
        ingestPollRef.current = null;
        setIngestRunning(false);
      }
    }, 2000);
  }, []);

  const handleTriggerIngestion = useCallback(async () => {
    try {
      setIngestRunning(true);
      setIngestMessage('Starting ingestion…');
      await triggerIngestion();
      pollIngestionStatus();
    } catch {
      setIngestRunning(false);
      setIngestMessage('Ingestion failed to start');
    }
  }, [pollIngestionStatus]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (ingestPollRef.current) clearInterval(ingestPollRef.current); };
  }, []);

  // Auto-dismiss ingestion success banner after 5s
  useEffect(() => {
    if (ingestMessage && !ingestRunning) {
      const timer = setTimeout(() => setIngestMessage(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [ingestMessage, ingestRunning]);

  // Click-outside handler for space filter dropdown
  useEffect(() => {
    if (!showSpaceFilter) return;
    function handleClick(e: MouseEvent) {
      if (spaceFilterRef.current && !spaceFilterRef.current.contains(e.target as Node)) {
        setShowSpaceFilter(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showSpaceFilter]);

  // Load available spaces once on mount
  useEffect(() => {
    getSpaces().then(setAvailableSpaces).catch(() => {});
  }, []);

  // Keep the sidebar conversation list in sync after each completed answer
  useEffect(() => {
    if (!conversationId) return;
    const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant' && m.content);
    const firstUser = messages.find((m) => m.role === 'user');
    if (firstUser) {
      upsertConversation(
        conversationId,
        firstUser.content.slice(0, 60),
        lastAssistant?.content.slice(0, 80) ?? ''
      );
    }
  }, [conversationId, messages, upsertConversation]);

  async function handleSelectConversation(id: string) {
    if (id === conversationId) return;
    // 1. Try localStorage first (instant)
    let data = loadConversationData(id);
    // 2. Fall back to server if not cached locally
    if (!data) {
      const serverMsgs = await fetchConversationMessages(id);
      if (serverMsgs && serverMsgs.length > 0) {
        data = { messages: serverMsgs, conversationId: id };
      }
    }
    if (data) {
      loadConversation(data.messages, data.conversationId);
    }
  }

  function handleDeleteConversation(id: string) {
    deleteConversation(id);
    deleteConversationFromServer(id).catch(() => {});
    if (id === conversationId) {
      clearConversation();
    }
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      {sidebarOpen && (
        <ConversationSidebar
          conversations={conversations}
          folders={folders}
          activeId={conversationId}
          onNew={clearConversation}
          onSelect={handleSelectConversation}
          onDelete={handleDeleteConversation}
          onRename={renameConversation}
          onMoveToFolder={moveToFolder}
          onCreateFolder={createFolder}
          onRenameFolder={renameFolder}
          onDeleteFolder={deleteFolder}
        />
      )}

      {/* Main chat area */}
      <div className="flex flex-col flex-1 min-w-0 bg-[#f1f5f9] dark:bg-gray-900">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#e5e5e5] dark:border-gray-700/80 bg-white dark:bg-gray-800 transition-colors">
          <div className="flex items-center gap-3">
            {/* Sidebar toggle */}
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all duration-150"
              title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
              aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
            >
              {sidebarOpen ? (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              )}
            </button>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-emerald-400 shadow-sm shadow-emerald-400/50 animate-pulse" />
              <span className="text-[11px] text-gray-400 dark:text-gray-500 font-medium">Ready</span>
            </div>
            {/* Space filter */}
            {availableSpaces.length > 0 && (
              <div className="relative" ref={spaceFilterRef}>
                <button
                  onClick={() => setShowSpaceFilter((v) => !v)}
                  className={`flex items-center gap-1 text-xs px-2 py-1 rounded-md border transition-colors ${
                    selectedSpaces.length > 0
                      ? 'border-blue-400 text-blue-600 bg-blue-50 dark:bg-blue-900/30'
                      : 'border-[#e5e5e5] dark:border-gray-600 text-[#64748b] dark:text-gray-400 hover:border-gray-300'
                  }`}
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
                  </svg>
                  {selectedSpaces.length > 0 ? `${selectedSpaces.length} space${selectedSpaces.length > 1 ? 's' : ''}` : 'All spaces'}
                </button>
                {showSpaceFilter && (
                  <div
                    role="listbox"
                    aria-label="Filter by space"
                    onKeyDown={(e) => { if (e.key === 'Escape') setShowSpaceFilter(false); }}
                    className="absolute top-full left-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 
                                  rounded-lg shadow-lg z-10 min-w-[180px] py-1"
                  >
                    <button
                      onClick={() => { setSelectedSpaces([]); setShowSpaceFilter(false); }}
                      className={`w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${
                        selectedSpaces.length === 0 ? 'font-semibold text-blue-600' : 'text-gray-700 dark:text-gray-300'
                      }`}
                    >
                      All spaces
                    </button>
                    {availableSpaces.map(({ space_key, space_name }) => (
                      <button
                        key={space_key}
                        onClick={() => {
                          const next = selectedSpaces.includes(space_key)
                            ? selectedSpaces.filter((k) => k !== space_key)
                            : [...selectedSpaces, space_key];
                          setSelectedSpaces(next);
                        }}
                        className={`w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors flex items-center gap-2 ${
                          selectedSpaces.includes(space_key) ? 'text-blue-600 font-semibold' : 'text-gray-700 dark:text-gray-300'
                        }`}
                      >
                        {selectedSpaces.includes(space_key) && (
                          <svg className="w-3 h-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        )}
                        <span className={selectedSpaces.includes(space_key) ? '' : 'ml-5'}>{space_name || space_key}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-1">
            {/* Ingestion trigger — admin only */}
            {isAdmin && (
            <button
              onClick={handleTriggerIngestion}
              disabled={ingestRunning}
              className={`flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-all duration-150 ${
                ingestRunning
                  ? 'text-amber-500 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 cursor-wait'
                  : 'text-[#64748b] hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20'
              }`}
              title={ingestRunning ? (ingestMessage ?? 'Ingesting…') : 'Sync documents'}
            >
              <svg className={`w-3.5 h-3.5 ${ingestRunning ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {ingestRunning ? 'Syncing…' : 'Sync'}
            </button>
            )}
            {messages.length > 0 && (
              <button
                onClick={clearConversation}
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 px-2 py-1 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-all duration-150"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Ingestion status banner */}
        {ingestMessage && (
          <div className={`mx-4 mt-2 px-3 py-1.5 rounded-lg text-xs ${
            ingestRunning
              ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-700/50'
              : 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-700/50'
          }`}>
            <div className="flex items-center gap-2">
              {ingestRunning ? (
                <svg className="w-3.5 h-3.5 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              )}
              <span className="flex-1">{ingestMessage}</span>
              {ingestRunning && ingestPercent > 0 && (
                <span className="font-semibold tabular-nums">{ingestPercent}%</span>
              )}
            </div>
            {ingestRunning && ingestPercent > 0 && (
              <div className="mt-1.5 w-full bg-blue-200/40 dark:bg-blue-800/40 rounded-full h-1.5 overflow-hidden">
                <div
                  className="h-full bg-blue-600 dark:bg-blue-400 rounded-full transition-all duration-500 ease-out"
                  style={{ width: `${Math.min(ingestPercent, 100)}%` }}
                />
              </div>
            )}
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div className="mx-4 mt-3 px-4 py-2 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded-lg 
                          text-sm text-red-700 dark:text-red-300 flex items-center gap-2">
            <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                clipRule="evenodd"
              />
            </svg>
            {error}
          </div>
        )}

        {/* Stream status indicator */}
        {streamStatus && (
          <div className="mx-4 mt-2 flex items-center gap-2 text-xs text-blue-600 dark:text-blue-400 animate-pulse">
            <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            {streamStatus}
          </div>
        )}

        {/* Messages */}
        <MessageList
          messages={messages}
          isLoading={isLoading}
          onSelectQuestion={sendMessage}
          onFeedback={rateFeedback}
          onRetry={retryLastMessage}
          onAskAbout={sendMessage}
        />

        {/* Suggestions — only after the first exchange */}
        <QuerySuggestions
          currentQuestion={(() => { const userMsgs = messages.filter((m) => m.role === 'user'); return userMsgs[userMsgs.length - 1]?.content; })()}
          onSelect={sendMessage}
          visible={!isLoading && messages.filter((m) => m.role === 'user').length === 1}
        />

        {/* Input */}
        <ChatInput
          onSend={sendMessage}
          onStop={stopStreaming}
          onUpload={handleUpload}
          isLoading={isLoading}
          uploadedFiles={uploadedFiles}
          onRemoveUpload={removeUpload}
          isUploading={isUploading}
        />
      </div>
    </div>
  );
}

