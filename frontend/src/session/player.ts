import { useSyncExternalStore } from "react";
import type { ClickPlace } from "../selection/store.ts";
import type { Answer, Part, RecordedSession, Statement } from "./format.ts";
import { grade, type Clicked } from "./grade.ts";

/** How a click case stands for the student. */
export interface CaseOutcome {
  /** How many times they have clicked. */
  attempts: number;
  correct: boolean;
  /** True once they asked to be shown the answer. */
  revealed: boolean;
  /** Feedback for the latest click, or null before the first. */
  statement: Statement | null;
  /** The latest click, so a wrong one can be marked on the model. */
  lastClick: Clicked | null;
}

export interface PlayerState {
  /** The session being played, or null when none is. */
  readonly session: RecordedSession | null;
  /** Identifies this play-through, so it can be kept in the history and reopened. */
  readonly runId: string | null;
  /** When this play-through began, as milliseconds since 1970. */
  readonly startedAt: number;
  /** Index of the part on screen. Equal to the number of parts once the summary is showing. */
  readonly index: number;
  /** The furthest index reached so far. Parts up to here are shown in the thread. */
  readonly reached: number;
  /** Where the damage point sits on each slider part, by part id. */
  readonly damage: Readonly<Record<string, number>>;
  /** How each click case stands, by part id. */
  readonly outcomes: Readonly<Record<string, CaseOutcome>>;
  /** Every click on a case, oldest first, in the shape sent to the backend. */
  readonly answers: readonly Answer[];
}

const IDLE: PlayerState = { session: null, runId: null, startedAt: 0, index: 0, reached: 0, damage: {}, outcomes: {}, answers: [] };

/** The part on screen, or null when no session is playing or the summary is showing. */
export function currentPart(state: PlayerState): Part | null {
  return state.session?.parts[state.index] ?? null;
}

/** True while a case is waiting for a click: not yet answered correctly, and the answer not shown. */
export function caseIsOpen(state: PlayerState): boolean {
  const part = currentPart(state);
  if (part?.kind !== "click_case") return false;
  const outcome = state.outcomes[part.id];
  return !outcome?.correct && !outcome?.revealed;
}

/**
 * Plays a recorded session: which part is on screen, where the slider is, and
 * how each case was answered.
 *
 * Lives outside React, like the selection: the 3D stage and the session panel
 * both follow it. It only keeps state; drawing is done by `Stage`.
 */
export class PlayerStore {
  private state: PlayerState = IDLE;
  private readonly listeners = new Set<() => void>();
  private readonly now: () => number;
  /** When the part on screen appeared, for timing an answer. */
  private shownAt = 0;

  constructor(now: () => number = () => performance.now() / 1000) {
    this.now = now;
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getState = (): PlayerState => this.state;

  /** Begin a session at its first part. */
  start(session: RecordedSession): void {
    this.shownAt = this.now();
    const startedAt = Date.now();
    this.update({ ...IDLE, session, startedAt, runId: `${session.session_id}-${startedAt.toString(36)}` });
  }

  /** Reopen a play-through exactly as it was left, e.g. from the history. */
  restore(saved: PlayerState): void {
    this.shownAt = this.now();
    this.update(saved);
  }

  /** Stop playing. The 3D view goes back to how the student left it. */
  close(): void {
    if (this.state.session) this.update(IDLE);
  }

  next(): void {
    this.goTo(this.state.index + 1);
  }

  back(): void {
    this.goTo(this.state.index - 1);
  }

  /** Jump to a part by index. One past the last part is the summary. */
  goTo(index: number): void {
    const { session } = this.state;
    if (!session) return;
    const clamped = Math.max(0, Math.min(session.parts.length, index));
    if (clamped === this.state.index) return;
    this.shownAt = this.now();
    this.update({ ...this.state, index: clamped, reached: Math.max(this.state.reached, clamped) });
  }

  /** Where the damage point is on the slider part on screen, or null if that part is not a slider. */
  damageAt(): number | null {
    const part = currentPart(this.state);
    return part?.kind === "damage_slider" ? (this.state.damage[part.id] ?? part.start_at) : null;
  }

  /** Move the damage point on the slider part on screen, kept inside its track. */
  setDamage(at: number): void {
    const part = currentPart(this.state);
    if (part?.kind !== "damage_slider") return;
    const clamped = Math.max(part.track.from, Math.min(part.track.to, at));
    if (clamped === this.damageAt()) return;
    this.update({ ...this.state, damage: { ...this.state.damage, [part.id]: clamped } });
  }

  /**
   * A click on the model while a case is waiting for one. Grades it and records
   * the answer. Returns false, and does nothing, when no case is open.
   */
  answer(structureId: string, place: ClickPlace): boolean {
    const part = currentPart(this.state);
    if (part?.kind !== "click_case" || !caseIsOpen(this.state)) return false;
    const clicked: Clicked = { structureId, piece: place.vessel?.pieceId ?? null, at: place.vessel?.along ?? null };
    const result = grade(part, clicked);
    const attempts = (this.state.outcomes[part.id]?.attempts ?? 0) + 1;
    const answer: Answer = {
      part_id: part.id,
      attempt: attempts,
      structure_id: structureId,
      point: place.point,
      piece: clicked.piece,
      at: clicked.at,
      correct: result.correct,
      seconds: this.now() - this.shownAt,
    };
    const outcome: CaseOutcome = { attempts, correct: result.correct, revealed: false, statement: result.statement, lastClick: clicked };
    this.update({
      ...this.state,
      outcomes: { ...this.state.outcomes, [part.id]: outcome },
      answers: [...this.state.answers, answer],
    });
    return true;
  }

  /** Show the answer to the case on screen. It then stops taking clicks. */
  reveal(): void {
    const part = currentPart(this.state);
    if (part?.kind !== "click_case" || !caseIsOpen(this.state)) return;
    const before = this.state.outcomes[part.id];
    const outcome: CaseOutcome = {
      attempts: before?.attempts ?? 0,
      correct: false,
      revealed: true,
      statement: part.feedback.correct,
      lastClick: null,
    };
    this.update({ ...this.state, outcomes: { ...this.state.outcomes, [part.id]: outcome } });
  }

  private update(next: PlayerState): void {
    this.state = next;
    this.listeners.forEach((listener) => listener());
  }
}

export const playerStore = new PlayerStore();

export function usePlayer(): PlayerState {
  return useSyncExternalStore(playerStore.subscribe, playerStore.getState);
}
