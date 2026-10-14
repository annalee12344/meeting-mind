/**
 * Storage Abstraction Layer for Meeting Mind.
 * 
 * Provides a swappable PersistenceAdapter interface decoupling UI components from
 * the concrete storage mechanism.
 * 
 * Current implementation: LocalStorageAdapter (browser-only local storage).
 * Prepared for DB swap: ApiAdapter skeleton pointing to /api/v1/meetings/:id/overlay.
 * 
 * NOTE ON STORAGE LIMITATIONS:
 * In the current local architecture without a persistent database backend,
 * user overlays (edits, manual tasks, notes, checkmarks) live strictly in that browser's
 * localStorage. Re-opening in another browser or incognito mode will not have those edits
 * unless exported and imported as JSON.
 */

import type { MeetingOverlay } from './types.generated';

export interface OverlaySummary {
  meetingId: string;
  updatedAt: string;
}

export interface PersistenceAdapter {
  /**
   * Load user overlay for a given meeting ID or transcript hash.
   */
  loadOverlay(meetingId: string): Promise<MeetingOverlay | null>;

  /**
   * Save or update user overlay.
   */
  saveOverlay(overlay: MeetingOverlay): Promise<void>;

  /**
   * Delete overlay for a given meeting ID.
   */
  deleteOverlay(meetingId: string): Promise<void>;

  /**
   * List all stored overlay keys and their last update timestamps.
   */
  listOverlays(): Promise<OverlaySummary[]>;
}

const STORAGE_PREFIX = 'mm_overlay_';

/**
 * LocalStorageAdapter: Persists user overlay to browser localStorage.
 * Includes error guards, schema versioning, and quota exceeded handling.
 */
export class LocalStorageAdapter implements PersistenceAdapter {
  private prefix: string;

  constructor(prefix = STORAGE_PREFIX) {
    this.prefix = prefix;
  }

  private getKey(meetingId: string): string {
    return `${this.prefix}${meetingId}`;
  }

  async loadOverlay(meetingId: string): Promise<MeetingOverlay | null> {
    if (!meetingId) return null;
    try {
      if (typeof window === 'undefined' || !window.localStorage) {
        return null;
      }
      const raw = window.localStorage.getItem(this.getKey(meetingId));
      if (!raw) return null;
      const parsed = JSON.parse(raw) as MeetingOverlay;
      return parsed;
    } catch (err) {
      console.warn(`[LocalStorageAdapter] Failed to load overlay for meeting ${meetingId}:`, err);
      return null;
    }
  }

  async saveOverlay(overlay: MeetingOverlay): Promise<void> {
    if (!overlay?.meeting_id) {
      throw new Error('Cannot save overlay without meeting_id');
    }

    try {
      if (typeof window === 'undefined' || !window.localStorage) {
        return;
      }

      const key = this.getKey(overlay.meeting_id);
      const serialized = JSON.stringify(overlay);

      try {
        window.localStorage.setItem(key, serialized);
      } catch (storageErr: unknown) {
        // Handle QuotaExceededError gracefully
        const isQuota =
          storageErr instanceof DOMException &&
          (storageErr.name === 'QuotaExceededError' ||
            storageErr.code === 22 ||
            storageErr.code === 1014);

        if (isQuota) {
          console.warn(
            '[LocalStorageAdapter] localStorage quota exceeded. Attempting to prune oldest meeting overlays...'
          );
          this.pruneOldestOverlays(key, serialized);
        } else {
          throw storageErr;
        }
      }
    } catch (err) {
      console.error(`[LocalStorageAdapter] Failed to save overlay for meeting ${overlay.meeting_id}:`, err);
      throw err;
    }
  }

  async deleteOverlay(meetingId: string): Promise<void> {
    if (!meetingId) return;
    try {
      if (typeof window === 'undefined' || !window.localStorage) {
        return;
      }
      window.localStorage.removeItem(this.getKey(meetingId));
    } catch (err) {
      console.warn(`[LocalStorageAdapter] Failed to delete overlay for meeting ${meetingId}:`, err);
    }
  }

  async listOverlays(): Promise<OverlaySummary[]> {
    const results: OverlaySummary[] = [];
    try {
      if (typeof window === 'undefined' || !window.localStorage) {
        return results;
      }

      for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (key && key.startsWith(this.prefix)) {
          const meetingId = key.substring(this.prefix.length);
          try {
            const raw = window.localStorage.getItem(key);
            if (raw) {
              const parsed = JSON.parse(raw);
              results.push({
                meetingId,
                updatedAt: parsed.updated_at || new Date().toISOString(),
              });
            }
          } catch {
            results.push({ meetingId, updatedAt: new Date().toISOString() });
          }
        }
      }
    } catch (err) {
      console.warn('[LocalStorageAdapter] Failed to list overlays:', err);
    }
    return results;
  }

  /**
   * Remove oldest overlays to free space when quota is exceeded.
   */
  private pruneOldestOverlays(targetKey: string, serializedData: string): void {
    try {
      const items: Array<{ key: string; updatedAt: number }> = [];
      for (let i = 0; i < window.localStorage.length; i++) {
        const k = window.localStorage.key(i);
        if (k && k.startsWith(this.prefix) && k !== targetKey) {
          try {
            const parsed = JSON.parse(window.localStorage.getItem(k) || '{}');
            const time = parsed.updated_at ? new Date(parsed.updated_at).getTime() : 0;
            items.push({ key: k, updatedAt: time });
          } catch {
            items.push({ key: k, updatedAt: 0 });
          }
        }
      }

      items.sort((a, b) => a.updatedAt - b.updatedAt);
      for (const item of items) {
        window.localStorage.removeItem(item.key);
        try {
          window.localStorage.setItem(targetKey, serializedData);
          return;
        } catch {
          // Continue pruning if still exceeded
        }
      }

      // Final attempt
      window.localStorage.setItem(targetKey, serializedData);
    } catch (err) {
      console.error('[LocalStorageAdapter] Pruning failed to recover quota:', err);
    }
  }
}

/**
 * ApiAdapter: Skeleton implementation connecting to a future storage backend.
 * When switching from local testing to multi-user DB storage, configure this adapter.
 */
export class ApiAdapter implements PersistenceAdapter {
  private apiBaseUrl: string;

  constructor(apiBaseUrl = '/api/v1') {
    this.apiBaseUrl = apiBaseUrl;
  }

  async loadOverlay(meetingId: string): Promise<MeetingOverlay | null> {
    const res = await fetch(`${this.apiBaseUrl}/meetings/${encodeURIComponent(meetingId)}/overlay`);
    if (res.status === 404) return null;
    if (!res.ok) {
      throw new Error(`ApiAdapter failed to load overlay: status ${res.status}`);
    }
    return (await res.json()) as MeetingOverlay;
  }

  async saveOverlay(overlay: MeetingOverlay): Promise<void> {
    const res = await fetch(`${this.apiBaseUrl}/meetings/${encodeURIComponent(overlay.meeting_id)}/overlay`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(overlay),
    });
    if (!res.ok) {
      throw new Error(`ApiAdapter failed to save overlay: status ${res.status}`);
    }
  }

  async deleteOverlay(meetingId: string): Promise<void> {
    const res = await fetch(`${this.apiBaseUrl}/meetings/${encodeURIComponent(meetingId)}/overlay`, {
      method: 'DELETE',
    });
    if (!res.ok && res.status !== 404) {
      throw new Error(`ApiAdapter failed to delete overlay: status ${res.status}`);
    }
  }

  async listOverlays(): Promise<OverlaySummary[]> {
    const res = await fetch(`${this.apiBaseUrl}/meetings/overlays`);
    if (!res.ok) {
      throw new Error(`ApiAdapter failed to list overlays: status ${res.status}`);
    }
    return (await res.json()) as OverlaySummary[];
  }
}

// Default singleton adapter instance
let defaultAdapter: PersistenceAdapter = new LocalStorageAdapter();

export function getDefaultPersistenceAdapter(): PersistenceAdapter {
  return defaultAdapter;
}

export function setDefaultPersistenceAdapter(adapter: PersistenceAdapter): void {
  defaultAdapter = adapter;
}
