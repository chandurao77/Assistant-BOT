import { useCallback, useEffect, useState } from 'react';
import type { ConversationFolder } from '@/types';

const FOLDERS_KEY = 'confluence_conversation_folders';

function loadFolders(): ConversationFolder[] {
  try {
    const raw = localStorage.getItem(FOLDERS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveFolders(folders: ConversationFolder[]): void {
  try {
    localStorage.setItem(FOLDERS_KEY, JSON.stringify(folders));
  } catch { /* ignore */ }
}

export function useFolders() {
  const [folders, setFolders] = useState<ConversationFolder[]>(loadFolders);

  useEffect(() => {
    saveFolders(folders);
  }, [folders]);

  const createFolder = useCallback((name: string) => {
    const folder: ConversationFolder = {
      id: `folder_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      name,
      createdAt: new Date().toISOString(),
    };
    setFolders((prev) => [...prev, folder]);
    return folder.id;
  }, []);

  const renameFolder = useCallback((id: string, name: string) => {
    setFolders((prev) =>
      prev.map((f) => (f.id === id ? { ...f, name } : f))
    );
  }, []);

  const deleteFolder = useCallback((id: string) => {
    setFolders((prev) => prev.filter((f) => f.id !== id));
  }, []);

  return { folders, createFolder, renameFolder, deleteFolder };
}
