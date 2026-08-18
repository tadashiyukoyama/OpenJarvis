import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getMemoryStats,
  indexMemoryPath,
  isTauri,
  searchMemory,
  storeMemory,
} from '@/lib/api';
import type { MemorySearchResult, MemoryStats } from '@/lib/api';

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function useMemorySection() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [statsError, setStatsError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MemorySearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [indexPath, setIndexPath] = useState('');
  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState('');
  const [indexError, setIndexError] = useState('');
  const [storeContent, setStoreContent] = useState('');
  const [storing, setStoring] = useState(false);
  const [storeResult, setStoreResult] = useState('');
  const [storeError, setStoreError] = useState('');
  const statsInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStats = useCallback(() => {
    getMemoryStats()
      .then((value) => {
        setStats(value);
        setStatsError('');
      })
      .catch(() => setStatsError('Could not reach memory backend'));
  }, []);

  useEffect(() => {
    loadStats();
    statsInterval.current = setInterval(loadStats, 10_000);
    return () => {
      if (statsInterval.current) clearInterval(statsInterval.current);
    };
  }, [loadStats]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchDone(false);
    try {
      setSearchResults((await searchMemory(searchQuery.trim())) || []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearchDone(true);
      setSearching(false);
    }
  };

  const handleBrowse = async () => {
    if (isTauri()) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({
          directory: true,
          multiple: false,
          title: 'Select folder to index',
        });
        if (selected) setIndexPath(selected as string);
        return;
      } catch {
        // The browser directory picker remains a safe fallback.
      }
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.setAttribute('webkitdirectory', '');
    input.onchange = () => {
      const file = input.files?.[0] as (File & { webkitRelativePath?: string }) | undefined;
      const folder = (file?.webkitRelativePath || '').split('/')[0];
      if (folder) setIndexPath(folder);
    };
    input.click();
  };

  const handleIndex = async () => {
    if (!indexPath.trim()) return;
    setIndexing(true);
    setIndexResult('');
    setIndexError('');
    try {
      const result = await indexMemoryPath(indexPath.trim());
      setIndexResult(
        `Indexed ${result.chunks_indexed} chunk${result.chunks_indexed !== 1 ? 's' : ''}`,
      );
      setIndexPath('');
      loadStats();
    } catch (error) {
      setIndexError(errorMessage(error, 'Indexing failed'));
    } finally {
      setIndexing(false);
    }
  };

  const handleStore = async () => {
    if (!storeContent.trim()) return;
    setStoring(true);
    setStoreResult('');
    setStoreError('');
    try {
      await storeMemory(storeContent.trim());
      setStoreResult('Stored successfully');
      setStoreContent('');
      loadStats();
    } catch (error) {
      setStoreError(errorMessage(error, 'Failed to store'));
    } finally {
      setStoring(false);
    }
  };

  return {
    stats,
    statsError,
    searchQuery,
    setSearchQuery,
    searchResults,
    searching,
    searchDone,
    handleSearch,
    indexPath,
    setIndexPath,
    indexing,
    indexResult,
    indexError,
    handleBrowse,
    handleIndex,
    storeContent,
    setStoreContent,
    storing,
    storeResult,
    storeError,
    handleStore,
    isDesktop: isTauri(),
  };
}
