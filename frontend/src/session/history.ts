import { useSyncExternalStore } from "react";
import { checkSession } from "./format.ts";
import { playerStore, type PlayerState, type PlayerStore } from "./player.ts";

/** One past play-through of a session, as it was left. */
export interface HistoryEntry {
  runId: string;
  /** What the student asked for; shown as the entry's title. */
  request: string;
  startedAt: number;
  /** Everything needed to reopen it: the session and where the student was in it. */
  state: PlayerState;
}

/** The part of browser storage the history needs; lets tests pass a stand-in. */
export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const STORAGE_KEY = "lumen.history.v1";
/** Oldest entries beyond this many are dropped. */
const MAX_ENTRIES = 30;

/**
 * Past sessions, newest first, kept in this browser only.
 *
 * It follows the player and saves each play-through as it goes, so closing a
 * session or reloading the page loses nothing. This stands in for real
 * storage: once the backend keeps sessions, the list should come from there.
 */
export class HistoryStore {
  private entries: readonly HistoryEntry[];
  private readonly listeners = new Set<() => void>();
  private readonly player: PlayerStore;
  private readonly storage: KeyValueStorage | null;

  constructor(player: PlayerStore, storage: KeyValueStorage | null) {
    this.player = player;
    this.storage = storage;
    this.entries = this.load();
    player.subscribe(this.record);
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getEntries = (): readonly HistoryEntry[] => this.entries;

  /** Reopen a past play-through where it was left. */
  open(runId: string): void {
    const entry = this.entries.find((candidate) => candidate.runId === runId);
    if (entry) this.player.restore(entry.state);
  }

  /** Forget a play-through. If it is the one on screen, it is closed too. */
  remove(runId: string): void {
    if (this.player.getState().runId === runId) this.player.close();
    this.save(this.entries.filter((entry) => entry.runId !== runId));
  }

  /** Save the play-through on screen, replacing its earlier copy. */
  private readonly record = () => {
    const state = this.player.getState();
    if (!state.session || !state.runId) return;
    const entry: HistoryEntry = { runId: state.runId, request: state.session.request, startedAt: state.startedAt, state };
    const others = this.entries.filter((candidate) => candidate.runId !== state.runId);
    this.save([entry, ...others].sort((a, b) => b.startedAt - a.startedAt).slice(0, MAX_ENTRIES));
  };

  private save(entries: readonly HistoryEntry[]): void {
    this.entries = entries;
    try {
      this.storage?.setItem(STORAGE_KEY, JSON.stringify(entries));
    } catch {
      // Storage is full or blocked: the list still works until the page is closed.
    }
    this.listeners.forEach((listener) => listener());
  }

  /** Read saved entries, dropping any that are damaged or no longer fit the format. */
  private load(): HistoryEntry[] {
    try {
      const saved: unknown = JSON.parse(this.storage?.getItem(STORAGE_KEY) ?? "[]");
      if (!Array.isArray(saved)) return [];
      return saved.filter(
        (entry): entry is HistoryEntry =>
          typeof entry?.runId === "string" &&
          typeof entry.request === "string" &&
          typeof entry.startedAt === "number" &&
          entry.state?.runId === entry.runId &&
          checkSession(entry.state.session).length === 0,
      );
    } catch {
      return [];
    }
  }
}

function browserStorage(): KeyValueStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export const historyStore = new HistoryStore(playerStore, typeof window === "undefined" ? null : browserStorage());

export function useHistory(): readonly HistoryEntry[] {
  return useSyncExternalStore(historyStore.subscribe, historyStore.getEntries);
}
