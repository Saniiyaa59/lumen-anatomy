import type { Attach, Centerlines, Stretch } from "../centerlines.ts";
import type { Place } from "./format.ts";

/** One piece a pulse travels along, and how far the pulse has gone when it reaches the start of it. */
export interface RouteSegment extends Stretch {
  startsAt: number;
}

/** Everywhere a pulse goes. `length` is the distance to the farthest end. */
export interface PulseRoute {
  segments: RouteSegment[];
  length: number;
}

/**
 * Work out a pulse's route. With an end, it is the single path from `from` to
 * `to`. Without one, the pulse spreads into every branch beyond `from`, and
 * reaches each branch when it passes the point where that branch leaves.
 */
export function pulseRoute(lines: Centerlines, from: Place, to: Place | null): PulseRoute {
  const segments: RouteSegment[] = [];
  if (to === null) {
    const starts = new Map<string, RouteSegment>();
    for (const stretch of lines.beyond(from.piece, from.at)) {
      const attach = lines.piece(stretch.pieceId)?.attach;
      const host = attach && starts.get(attach.piece);
      // A branch starts when the pulse reaches where it leaves its host.
      const startsAt = host ? host.startsAt + (attach.at - host.from) : 0;
      const segment = { ...stretch, startsAt };
      starts.set(stretch.pieceId, segment);
      segments.push(segment);
    }
  } else {
    // Walk back from the end to the start, then lay the pieces out in travel order.
    const chain: { pieceId: string; leavesHostAt: number }[] = [];
    let pieceId: string | undefined = to.piece;
    while (pieceId !== undefined && pieceId !== from.piece && chain.length < 100) {
      const attach: Attach | null | undefined = lines.piece(pieceId)?.attach;
      if (!attach) return { segments: [], length: 0 };
      chain.unshift({ pieceId, leavesHostAt: attach.at });
      pieceId = attach.piece;
    }
    if (pieceId !== from.piece) return { segments: [], length: 0 };
    let travelled = 0;
    let start = from.at;
    let current = from.piece;
    for (const link of chain) {
      segments.push({ pieceId: current, from: start, to: link.leavesHostAt, startsAt: travelled });
      travelled += link.leavesHostAt - start;
      current = link.pieceId;
      start = 0;
    }
    segments.push({ pieceId: current, from: start, to: to.at, startsAt: travelled });
  }
  const length = Math.max(0, ...segments.map((segment) => segment.startsAt + (segment.to - segment.from)));
  return { segments, length };
}

/**
 * The lit part of a route when the front of the pulse has travelled `head`
 * metres and the lit part is `tail` metres long.
 */
export function pulseStretches(route: PulseRoute, head: number, tail: number): Stretch[] {
  const lit: Stretch[] = [];
  for (const segment of route.segments) {
    const from = Math.max(segment.from, segment.from + (head - tail - segment.startsAt));
    const to = Math.min(segment.to, segment.from + (head - segment.startsAt));
    if (to > from) lit.push({ pieceId: segment.pieceId, from, to });
  }
  return lit;
}
