import { useEffect, useRef, useState } from 'react';
import type { ConversationFolder, ConversationSummary } from '@/types';
import { exportConversation } from '@/services/conversationsApi';

interface Props {
  conversations: ConversationSummary[];
  folders: ConversationFolder[];
  activeId: string | null;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, newTitle: string) => void;
  onMoveToFolder: (conversationId: string, folderId: string | null) => void;
  onCreateFolder: (name: string) => string;
  onRenameFolder: (id: string, name: string) => void;
  onDeleteFolder: (id: string) => void;
}

export function ConversationSidebar({
  conversations, folders, activeId, onNew, onSelect,
  onDelete, onRename, onMoveToFolder, onCreateFolder, onRenameFolder, onDeleteFolder,
}: Props) {
  const [search, setSearch] = useState('');
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());

  const query = search.toLowerCase().trim();
  const filtered = query
    ? conversations.filter(
        (c) => c.title.toLowerCase().includes(query) || c.preview?.toLowerCase().includes(query)
      )
    : conversations;

  const toggleFolder = (id: string) =>
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return next;
    });

  // Group conversations by folder
  const unfolderedConvs = filtered.filter((c) => !c.folderId);
  const folderConvsMap = new Map<string, ConversationSummary[]>();
  for (const f of folders) folderConvsMap.set(f.id, []);
  for (const c of filtered) {
    if (c.folderId && folderConvsMap.has(c.folderId)) {
      folderConvsMap.get(c.folderId)!.push(c);
    }
  }

  return (
    <aside className="w-72 flex-shrink-0 flex flex-col h-full bg-white dark:bg-gray-900 border-r border-[#f0f0f0] dark:border-gray-700/80 transition-colors">
      {/* Header */}
      <div className="px-3 py-3 border-b border-[#f0f0f0] dark:border-gray-700/80 space-y-2">
        <button
          onClick={onNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-gradient-to-r from-blue-600 to-purple-600
                     text-white text-sm font-medium hover:from-blue-700 hover:to-purple-700 active:scale-[0.98] transition-all duration-150 shadow-sm"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>

        {/* Search box */}
        <div className="relative">
          <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search conversations…"
            className="w-full text-xs pl-7 pr-2 py-1.5 rounded-lg border border-transparent bg-gray-100 dark:bg-gray-800
                       outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/30 focus:bg-white dark:focus:bg-gray-700
                       placeholder:text-gray-400 dark:placeholder:text-gray-500 text-gray-800 dark:text-gray-200 transition-all"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* New folder button */}
      <div className="px-3 py-1.5 border-b border-[#f0f0f0] dark:border-gray-700">
        <NewFolderButton onCreate={onCreateFolder} />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto py-1">
        {filtered.length === 0 && folders.length === 0 ? (
          <p className="text-xs text-gray-400 text-center mt-6 px-4">
            {query ? 'No matching conversations.' : 'No conversations yet. Ask a question to get started.'}
          </p>
        ) : (
          <>
            {/* Folders */}
            {folders.map((folder) => {
              const convs = folderConvsMap.get(folder.id) ?? [];
              const isCollapsed = collapsedFolders.has(folder.id);
              // Hide empty folders when searching (unless they still have matches)
              if (query && convs.length === 0) return null;
              return (
                <FolderSection
                  key={folder.id}
                  folder={folder}
                  conversations={convs}
                  isCollapsed={isCollapsed}
                  onToggle={() => toggleFolder(folder.id)}
                  activeId={activeId}
                  onSelect={onSelect}
                  onDelete={onDelete}
                  onRename={onRename}
                  onMoveToFolder={onMoveToFolder}
                  onRenameFolder={onRenameFolder}
                  onDeleteFolder={onDeleteFolder}
                  folders={folders}
                />
              );
            })}

            {/* Unfoldered conversations */}
            {unfolderedConvs.length > 0 && (
              <div className={folders.length > 0 ? 'mt-1 pt-1 border-t border-[#f0f0f0] dark:border-gray-700' : ''}>
                {folders.length > 0 && (
                  <p className="text-[11px] text-gray-400 uppercase tracking-wider px-3 py-1 font-medium">Chats</p>
                )}
                {unfolderedConvs.map((conv) => (
                  <ConvItem
                    key={conv.id}
                    conv={conv}
                    isActive={conv.id === activeId}
                    onSelect={onSelect}
                    onDelete={onDelete}
                    onRename={onRename}
                    onMoveToFolder={onMoveToFolder}
                    folders={folders}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

/* ── New Folder inline creator ──────────────────────────── */
function NewFolderButton({ onCreate }: { onCreate: (name: string) => string }) {
  const [isCreating, setIsCreating] = useState(false);
  const [name, setName] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isCreating) inputRef.current?.focus();
  }, [isCreating]);

  function commit() {
    const trimmed = name.trim();
    if (trimmed) onCreate(trimmed);
    setName('');
    setIsCreating(false);
  }

  if (isCreating) {
    return (
      <div className="flex items-center gap-1">
        <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        <input
          ref={inputRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') { setName(''); setIsCreating(false); }
          }}
          onBlur={commit}
          placeholder="Folder name…"
          className="flex-1 text-xs bg-white dark:bg-gray-800 border border-confluence-blue rounded px-1 py-0.5 
                     outline-none leading-tight text-gray-800 dark:text-gray-200"
        />
      </div>
    );
  }

  return (
    <button
      onClick={() => setIsCreating(true)}
      className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 hover:text-confluence-blue transition-colors"
    >
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
      </svg>
      New Folder
    </button>
  );
}

/* ── Folder section with collapsible contents ──────────── */
function FolderSection({
  folder, conversations, isCollapsed, onToggle, activeId,
  onSelect, onDelete, onRename, onMoveToFolder, onRenameFolder, onDeleteFolder, folders,
}: {
  folder: ConversationFolder;
  conversations: ConversationSummary[];
  isCollapsed: boolean;
  onToggle: () => void;
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, newTitle: string) => void;
  onMoveToFolder: (conversationId: string, folderId: string | null) => void;
  onRenameFolder: (id: string, name: string) => void;
  onDeleteFolder: (id: string) => void;
  folders: ConversationFolder[];
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(folder.name);
  const [showMenu, setShowMenu] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
  }, [isEditing]);

  useEffect(() => {
    if (!showMenu) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setShowMenu(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showMenu]);

  function commitRename() {
    const trimmed = editName.trim();
    if (trimmed && trimmed !== folder.name) onRenameFolder(folder.id, trimmed);
    else setEditName(folder.name);
    setIsEditing(false);
  }

  return (
    <div className="mb-0.5">
      {/* Folder header */}
      <div
        className="group relative flex items-center gap-1 px-2 py-1 mx-1 rounded cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800"
        onClick={onToggle}
      >
        {/* Chevron */}
        <svg
          className={`w-3 h-3 text-gray-400 flex-shrink-0 transition-transform ${isCollapsed ? '' : 'rotate-90'}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        {/* Folder icon */}
        <svg className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
          <path d="M2 6a2 2 0 012-2h5l2 2h9a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
        </svg>

        {isEditing ? (
          <input
            ref={inputRef}
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename();
              if (e.key === 'Escape') { setEditName(folder.name); setIsEditing(false); }
            }}
            onBlur={commitRename}
            onClick={(e) => e.stopPropagation()}
            className="flex-1 min-w-0 text-xs font-medium bg-white dark:bg-gray-800 border border-confluence-blue rounded px-1 py-0 
                       outline-none leading-tight text-gray-800 dark:text-gray-200"
          />
        ) : (
          <span className="flex-1 min-w-0 text-xs font-medium text-gray-700 dark:text-gray-300 truncate">
            {folder.name}
          </span>
        )}

        <span className="text-[10px] text-gray-400 flex-shrink-0">{conversations.length}</span>

        {/* 3-dot menu trigger */}
        {!isEditing && (
          <button
            onClick={(e) => { e.stopPropagation(); setShowMenu((v) => !v); }}
            className="p-0.5 rounded text-gray-300 opacity-0 group-hover:opacity-100 hover:text-gray-500 dark:hover:text-gray-200 transition-all flex-shrink-0"
            title="Folder options"
          >
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
              <circle cx="12" cy="5" r="1.2" />
              <circle cx="12" cy="12" r="1.2" />
              <circle cx="12" cy="19" r="1.2" />
            </svg>
          </button>
        )}

        {/* Folder 3-dot dropdown */}
        {showMenu && (
          <div
            ref={menuRef}
            className="absolute right-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg z-20 min-w-[140px] py-1"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => { setEditName(folder.name); setIsEditing(true); setShowMenu(false); }}
              className="w-full text-left px-3 py-1.5 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 
                     2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Rename
            </button>
            <button
              onClick={() => {
                setShowMenu(false);
                onDeleteFolder(folder.id);
                for (const c of conversations) onMoveToFolder(c.id, null);
              }}
              className="w-full text-left px-3 py-1.5 text-xs text-red-500 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Delete
            </button>
          </div>
        )}
      </div>

      {/* Folder contents */}
      {!isCollapsed && (
        <div className="ml-3">
          {conversations.length === 0 ? (
            <p className="text-[10px] text-gray-400 px-3 py-1 italic">Empty folder</p>
          ) : (
            conversations.map((conv) => (
              <ConvItem
                key={conv.id}
                conv={conv}
                isActive={conv.id === activeId}
                onSelect={onSelect}
                onDelete={onDelete}
                onRename={onRename}
                onMoveToFolder={onMoveToFolder}
                folders={folders}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* ── Conversation item with 3-dot menu (rename, delete, move-to-folder) ─ */
function ConvItem({
  conv,
  isActive,
  onSelect,
  onDelete,
  onRename,
  onMoveToFolder,
  folders,
}: {
  conv: ConversationSummary;
  isActive: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, newTitle: string) => void;
  onMoveToFolder: (conversationId: string, folderId: string | null) => void;
  folders: ConversationFolder[];
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(conv.title);
  const [showMenu, setShowMenu] = useState(false);
  const [showMoveSubmenu, setShowMoveSubmenu] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
  }, [isEditing]);

  // Close menu on outside click
  useEffect(() => {
    if (!showMenu) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
        setShowMoveSubmenu(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showMenu]);

  function commitRename() {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== conv.title) {
      onRename(conv.id, trimmed);
    } else {
      setEditTitle(conv.title);
    }
    setIsEditing(false);
  }

  return (
    <div
      className={`group relative flex items-start gap-1 px-2 py-1.5 mx-1 rounded-lg cursor-pointer 
                  ${isActive ? 'bg-[#f0f4ff] dark:bg-blue-900/30' : 'hover:bg-[#f0f4ff] dark:hover:bg-gray-800'}`}
      onClick={() => !isEditing && onSelect(conv.id)}
    >
      {/* Chat icon */}
      <svg
        className="w-4 h-4 mt-0.5 flex-shrink-0 text-gray-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 
             9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 
             12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>

      <div className="flex-1 min-w-0">
        {isEditing ? (
          <input
            ref={inputRef}
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename();
              if (e.key === 'Escape') { setEditTitle(conv.title); setIsEditing(false); }
            }}
            onBlur={commitRename}
            className="w-full text-xs font-medium bg-white dark:bg-gray-800 border border-confluence-blue rounded px-1 py-0 
                       outline-none leading-tight text-gray-800 dark:text-gray-200"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <p
            className={`text-xs font-medium truncate leading-tight 
                       ${isActive ? 'text-confluence-blue' : 'text-gray-700 dark:text-gray-300'}`}
          >
            {conv.title}
          </p>
        )}
        {conv.preview && !isEditing && (
          <p className="text-[10px] text-gray-400 truncate mt-0.5">{conv.preview}</p>
        )}
      </div>

      {/* 3-dot menu trigger */}
      {!isEditing && (
        <button
          onClick={(e) => { e.stopPropagation(); setShowMenu((v) => !v); setShowMoveSubmenu(false); }}
          className="p-0.5 rounded text-gray-300 opacity-0 group-hover:opacity-100 hover:text-gray-500 dark:hover:text-gray-200 transition-all flex-shrink-0 mt-0.5"
          title="Options"
        >
          <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
            <circle cx="12" cy="5" r="1.2" />
            <circle cx="12" cy="12" r="1.2" />
            <circle cx="12" cy="19" r="1.2" />
          </svg>
        </button>
      )}

      {/* 3-dot dropdown menu */}
      {showMenu && (
        <div
          ref={menuRef}
          className="absolute right-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg z-20 min-w-[160px] py-1"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Rename */}
          <button
            onClick={() => { setEditTitle(conv.title); setIsEditing(true); setShowMenu(false); }}
            className="w-full text-left px-3 py-1.5 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 
                   2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
            Rename
          </button>

          {/* Move to folder */}
          {folders.length > 0 && (
            <div className="relative">
              <button
                onClick={() => setShowMoveSubmenu((v) => !v)}
                className="w-full text-left px-3 py-1.5 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
                Move to folder
                <svg className="w-3 h-3 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
              {showMoveSubmenu && (
                <div className="ml-2 border-l border-gray-200 dark:border-gray-600 pl-1 py-0.5">
                  {conv.folderId && (
                    <button
                      onClick={() => { onMoveToFolder(conv.id, null); setShowMenu(false); setShowMoveSubmenu(false); }}
                      className="w-full text-left px-3 py-1 text-xs text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-1.5"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                      No Folder
                    </button>
                  )}
                  {folders
                    .filter((f) => f.id !== conv.folderId)
                    .map((f) => (
                      <button
                        key={f.id}
                        onClick={() => { onMoveToFolder(conv.id, f.id); setShowMenu(false); setShowMoveSubmenu(false); }}
                        className="w-full text-left px-3 py-1 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-1.5"
                      >
                        <svg className="w-3 h-3 text-gray-500 dark:text-gray-400" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M2 6a2 2 0 012-2h5l2 2h9a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                        </svg>
                        {f.name}
                      </button>
                    ))}
                </div>
              )}
            </div>
          )}

          {/* Export */}
          <button
            onClick={() => { setShowMenu(false); exportConversation(conv.id); }}
            className="w-full text-left px-3 py-1.5 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export as Markdown
          </button>

          {/* Divider */}
          <div className="border-t border-gray-100 dark:border-gray-700 my-1" />

          {/* Delete */}
          <button
            onClick={() => { setShowMenu(false); onDelete(conv.id); }}
            className="w-full text-left px-3 py-1.5 text-xs text-red-500 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
