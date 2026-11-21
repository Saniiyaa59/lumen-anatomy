import { useSyncExternalStore } from "react";
import type { ClickPlace } from "../selection/store.ts";
import type { Answer, ChoiceAnswer, ClickAnswer, Part, PlanItem, Question, SessionInPlay, Statement, Summary } from "./format.ts";
import { grade, type Clicked } from "./grade.ts";

/** How a click case or a multiple-choice question stands for the student. */
export interface CaseOutcome {
  /** How many times they have clicked or picked. */
  attempts: number;
  correct: boolean;
  /** True once they asked to be shown the answer. */
  revealed: boolean;
  /** Feedback for the latest click, or null before the first. */
  statement: Statement | null;
  /** The latest click, so a wrong one can be marked on the model. Always null for a question. */
  lastClick: Clicked | null;
  /** For a question, the options picked so far, in order, counted from 0. */
  picks?: number[];
}

/** One line of what the tutor and the student said before the plan. */
export interface ChatLine {
  from: "tutor" | "student";
  text: string;
}

/** A session whose tutor is waiting for the student to answer a question before it plans. */
export interface Asking {
  session_id: string;
  request: string;
  /** What has been said so far, oldest first; the last line is the tutor's open question. */
  chat: ChatLine[];
  question: Question;
}

/** Something said during a session, shown in the thread after the part it was said on. */
export interface SessionMessage {
  from: "student" | "tutor";
  /** The student's words, or a tutor's line that has no source (a question it asked). Empty for a sourced answer. */
  text: string;
  statements: Statement[];
  /** Index of the part on screen when it was said, or -1 if said before any part (while exploring). */
  after: number;
  /** Structures the tutor's answer points to; empty for the student. */
  pointTo?: string[];
}

export interface PlayerState {
  /** Set while the tutor waits for an answer before planning; `session` is null until it has planned. */
  readonly asking: Asking | null;
  /** The session being played, or null when none is. */
  readonly session: SessionInPlay | null;
  /** True when the parts come from the backend one at a time; false for a recorded session held in full. */
  readonly live: boolean;
  /** True while waiting for the backend: starting a session, or fetching the next part or the summary. */
  readonly pending: boolean;
  /** What went wrong with the last request to the backend, in words for the student; null when nothing did. */
  readonly error: string | null;
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
  /** How each click case and multiple-choice question stands, by part id. */
  readonly outcomes: Readonly<Record<string, CaseOutcome>>;
  /** Every click on a case and pick on a question, oldest first, in the shape sent to the backend. */
  readonly answers: readonly Answer[];
  /** What the student and the tutor said during the session, oldest first. */
  readonly messages: readonly SessionMessage[];
}

export const IDLE: PlayerState = {
  asking: null,
  session: null,
  live: false,
  pending: false,
  error: null,
  runId: null,
  startedAt: 0,
  index: 0,
  reached: 0,
  damage: {},
  outcomes: {},
  answers: [],
  messages: [],
};

/**
 * What has to be fetched before the student can move on from the part on
 * screen: the next part, the summary, or nothing because it is already here.
 */
export function nextNeeds(state: PlayerState): "part" | "summary" | null {
  const { session, index } = state;
  if (!session) return null;
  if (index + 1 < session.plan.length) return index + 1 < session.parts.length ? null : "part";
  return session.summary === null ? "summary" : null;
}

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

/** True while a multiple-choice question is waiting for a pick: not yet answered correctly, and the answer not shown. */
export function questionIsOpen(state: PlayerState): boolean {
  const part = currentPart(state);
  if (part?.kind !== "multiple_choice") return false;
  const outcome = state.outcomes[part.id];
  return !outcome?.correct && !outcome?.revealed;
}

/** True while the part on screen is a case or question still waiting for an answer. */
export function quizIsOpen(state: PlayerState): boolean {
  return caseIsOpen(state) || questionIsOpen(state);
}

/**
 * True while names on the model would give an answer away: a case asking for a
 * place, or a question about what is highlighted.
 */
export function namesHidden(state: PlayerState): boolean {
  const part = currentPart(state);
  return caseIsOpen(state) || (part?.kind === "multiple_choice" && part.highlight.length > 0 && questionIsOpen(state));
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

  /** Begin a session at its first part. A live session may start with no parts yet. */
  start(session: SessionInPlay, live = false): void {
    this.shownAt = this.now();
    const startedAt = Date.now();
    this.update({ ...IDLE, session, live, startedAt, runId: `${session.session_id}-${startedAt.toString(36)}` });
  }

  /** Add a part that has arrived from the backend. A part already held is ignored. */
  addPart(part: Part): void {
    const { session } = this.state;
    if (!session || session.parts.some((held) => held.id === part.id)) return;
    if (session.parts.length === 0) this.shownAt = this.now();
    this.update({ ...this.state, session: { ...session, parts: [...session.parts, part] } });
  }

  /** Replace the plan, when the backend sends a changed one. */
  setPlan(plan: PlanItem[]): void {
    const { session } = this.state;
    if (session) this.update({ ...this.state, session: { ...session, plan } });
  }

  /** Add the summary, once the backend has sent it. */
  setSummary(summary: Summary): void {
    const { session } = this.state;
    if (session) this.update({ ...this.state, session: { ...session, summary } });
  }

  /** Replace what has been said during the session. */
  setMessages(messages: readonly SessionMessage[]): void {
    this.update({ ...this.state, messages });
  }

  /** Show the tutor's question, or clear it. */
  setAsking(asking: Asking | null): void {
    this.update({ ...this.state, asking });
  }

  setPending(pending: boolean): void {
    if (pending !== this.state.pending) this.update({ ...this.state, pending });
  }

  setError(error: string | null): void {
    if (error !== this.state.error) this.update({ ...this.state, error });
  }

  /** Reopen a play-through exactly as it was left, e.g. from the history. */
  restore(saved: PlayerState): void {
    this.shownAt = this.now();
    this.update(saved);
  }

  /** Stop playing and clear any error. The heart is reset. */
  close(): void {
    if (this.state !== IDLE) this.update(IDLE);
  }

  next(): void {
    this.goTo(this.state.index + 1);
  }

  back(): void {
    this.goTo(this.state.index - 1);
  }

  /**
   * Jump to a part by index. One past the last part is the summary. Only what
   * has arrived can be shown: the summary needs every part and the summary itself.
   */
  goTo(index: number): void {
    const { session } = this.state;
    if (!session) return;
    const total = session.plan.length;
    const complete = session.parts.length >= total && session.summary !== null;
    const last = complete ? total : Math.max(0, session.parts.length - 1);
    const clamped = Math.max(0, Math.min(last, index));
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
    const answer: ClickAnswer = {
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

  /**
   * A pick on the multiple-choice question on screen. Grades it and records the
   * answer. Returns false, and does nothing, when no question is open, the
   * option does not exist or it was already picked.
   */
  pick(choice: number): boolean {
    const part = currentPart(this.state);
    if (part?.kind !== "multiple_choice" || !questionIsOpen(this.state)) return false;
    const option = part.options[choice];
    const before = this.state.outcomes[part.id];
    if (!option || before?.picks?.includes(choice)) return false;
    const attempts = (before?.attempts ?? 0) + 1;
    const answer: ChoiceAnswer = { part_id: part.id, attempt: attempts, choice, correct: option.correct, seconds: this.now() - this.shownAt };
    const outcome: CaseOutcome = {
      attempts,
      correct: option.correct,
      revealed: false,
      statement: option.feedback,
      lastClick: null,
      picks: [...(before?.picks ?? []), choice],
    };
    this.update({
      ...this.state,
      outcomes: { ...this.state.outcomes, [part.id]: outcome },
      answers: [...this.state.answers, answer],
    });
    return true;
  }

  /** Show the answer to the case or question on screen. It then stops taking answers. */
  reveal(): void {
    const part = currentPart(this.state);
    if (!quizIsOpen(this.state) || (part?.kind !== "click_case" && part?.kind !== "multiple_choice")) return;
    const before = this.state.outcomes[part.id];
    const outcome: CaseOutcome = {
      attempts: before?.attempts ?? 0,
      correct: false,
      revealed: true,
      statement: part.kind === "click_case" ? part.feedback.correct : part.options.find((option) => option.correct)!.feedback,
      lastClick: null,
      ...(before?.picks ? { picks: before.picks } : {}),
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
