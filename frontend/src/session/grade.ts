import type { ClickCase, Statement, Target } from "./format.ts";

/** What the student clicked, as far as grading cares: the structure, and for a vessel where on it. */
export interface Clicked {
  structureId: string;
  piece: string | null;
  at: number | null;
}

/**
 * Whether a click falls on a target: inside one of its stretches of vessel
 * (with `tolerance` metres of slack past either end) or on one of its structures.
 */
export function inTarget(target: Target, click: Clicked, tolerance = 0): boolean {
  if (target.structures.includes(click.structureId)) return true;
  const { piece, at } = click;
  if (piece === null || at === null) return false;
  return target.regions.some((region) => region.piece === piece && at >= region.from - tolerance && at <= region.to + tolerance);
}

export interface Grade {
  correct: boolean;
  /** The feedback to show for this click. */
  statement: Statement;
  /** Which near miss the click hit, if it was wrong in a way the case foresaw. */
  nearMiss: number | null;
}

/**
 * Grade a click on a case. Plain comparison of places, with no judgement:
 * correct if it is on the answer, otherwise the first near miss containing it
 * supplies the feedback, otherwise the case's general "wrong" feedback does.
 */
export function grade(part: ClickCase, click: Clicked): Grade {
  if (inTarget(part.answer, click, part.answer.tolerance)) {
    return { correct: true, statement: part.feedback.correct, nearMiss: null };
  }
  const nearMiss = part.feedback.near_misses.findIndex((miss) => inTarget(miss, click));
  return nearMiss === -1
    ? { correct: false, statement: part.feedback.wrong, nearMiss: null }
    : { correct: false, statement: part.feedback.near_misses[nearMiss].statement, nearMiss };
}
