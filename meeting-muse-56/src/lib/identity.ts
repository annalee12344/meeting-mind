/**
 * Client Identity & Note Permission Helpers.
 * 
 * Manages local anonymous client identity (UUID + display name)
 * and enforces permissions on issue notes:
 * - Only note author (matching author_id) can edit or delete their note.
 * - Other users see notes as distinct entries with the author's name.
 */

import { useState, useEffect, useCallback } from 'react';
import { generateUUID } from './overlay';

export interface UserIdentity {
  clientId: string;
  displayName: string;
}

const IDENTITY_KEY = 'mm_client_identity';

/**
 * Pure permission helper: only the author of a note can edit or delete it.
 */
export function canEditNote(
  authorId: string | null | undefined,
  currentUserId: string | null | undefined
): boolean {
  if (!authorId || !currentUserId) return false;
  return authorId.trim() === currentUserId.trim();
}

export function canDeleteNote(
  authorId: string | null | undefined,
  currentUserId: string | null | undefined
): boolean {
  return canEditNote(authorId, currentUserId);
}

/**
 * Load or initialize anonymous client identity from local storage.
 */
export function getStoredIdentity(): UserIdentity | null {
  if (typeof window === 'undefined' || !window.localStorage) {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(IDENTITY_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.clientId === 'string' && typeof parsed.displayName === 'string') {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Save client identity.
 */
export function saveStoredIdentity(displayName: string, clientId?: string): UserIdentity {
  const existing = getStoredIdentity();
  const identity: UserIdentity = {
    clientId: clientId || existing?.clientId || generateUUID(),
    displayName: displayName.trim(),
  };

  if (typeof window !== 'undefined' && window.localStorage) {
    try {
      window.localStorage.setItem(IDENTITY_KEY, JSON.stringify(identity));
    } catch (err) {
      console.warn('[Identity] Failed to persist identity:', err);
    }
  }

  return identity;
}

/**
 * Hook to manage user identity with prompt dialog support.
 */
export function useUserIdentity() {
  const [identity, setIdentity] = useState<UserIdentity | null>(() => getStoredIdentity());

  useEffect(() => {
    const loaded = getStoredIdentity();
    if (loaded) {
      setIdentity(loaded);
    }
  }, []);

  const updateDisplayName = useCallback((name: string) => {
    const saved = saveStoredIdentity(name, identity?.clientId);
    setIdentity(saved);
    return saved;
  }, [identity?.clientId]);

  return {
    identity,
    clientId: identity?.clientId || null,
    displayName: identity?.displayName || null,
    isIdentified: Boolean(identity?.displayName?.trim()),
    updateDisplayName,
  };
}
