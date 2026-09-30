/**
 * @vitest-environment jsdom
 *
 * Unit tests for the useFolders hook (localStorage-backed folder CRUD).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useFolders } from './useFolders';

const FOLDERS_KEY = 'confluence_conversation_folders';

beforeEach(() => {
  localStorage.clear();
});

describe('useFolders', () => {
  it('starts with empty folders', () => {
    const { result } = renderHook(() => useFolders());
    expect(result.current.folders).toEqual([]);
  });

  it('loads folders from localStorage on init', () => {
    const existing = [
      { id: 'f1', name: 'Work', createdAt: '2025-01-01T00:00:00Z' },
    ];
    localStorage.setItem(FOLDERS_KEY, JSON.stringify(existing));
    const { result } = renderHook(() => useFolders());
    expect(result.current.folders).toHaveLength(1);
    expect(result.current.folders[0].name).toBe('Work');
  });

  it('createFolder adds a new folder and returns its id', () => {
    const { result } = renderHook(() => useFolders());

    let newId: string;
    act(() => {
      newId = result.current.createFolder('Projects');
    });

    expect(result.current.folders).toHaveLength(1);
    expect(result.current.folders[0].name).toBe('Projects');
    expect(result.current.folders[0].id).toBe(newId!);
  });

  it('renameFolder updates folder name', () => {
    const { result } = renderHook(() => useFolders());

    let folderId: string;
    act(() => {
      folderId = result.current.createFolder('Old Name');
    });
    act(() => {
      result.current.renameFolder(folderId!, 'New Name');
    });

    expect(result.current.folders[0].name).toBe('New Name');
  });

  it('deleteFolder removes the folder', () => {
    const { result } = renderHook(() => useFolders());

    let folderId: string;
    act(() => {
      folderId = result.current.createFolder('ToDelete');
    });
    expect(result.current.folders).toHaveLength(1);

    act(() => {
      result.current.deleteFolder(folderId!);
    });
    expect(result.current.folders).toHaveLength(0);
  });

  it('persists folders to localStorage', () => {
    const { result } = renderHook(() => useFolders());

    act(() => {
      result.current.createFolder('Saved');
    });

    const stored = JSON.parse(localStorage.getItem(FOLDERS_KEY) || '[]');
    expect(stored).toHaveLength(1);
    expect(stored[0].name).toBe('Saved');
  });

  it('handles corrupt localStorage gracefully', () => {
    localStorage.setItem(FOLDERS_KEY, 'not-json');
    const { result } = renderHook(() => useFolders());
    expect(result.current.folders).toEqual([]);
  });
});
