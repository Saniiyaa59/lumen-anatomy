import centerlinesJson from "../../assets/regions/heart/centerlines.json";

/**
 * Where things are along a vessel.
 *
 * Each vessel's centre line comes from the atlas as pieces: a trunk and its
 * branches. A place on a vessel is "this piece, this far along it". All
 * distances are in metres, in the model's own frame (the same as model.glb).
 */

export type Point = readonly [number, number, number];

/** Where a piece branches off another: which piece, how far along it, and how far from its path the branch starts. */
export interface Attach {
  piece: string;
  at: number;
  gap: number;
}

export interface Piece {
  id: string;
  length: number;
  attach: Attach | null;
  /** Tube radius at each point. */
  radius: number[];
  points: Point[];
}

export interface CenterlinesFile {
  region: string;
  source: string;
  units: string;
  structures: Record<string, Piece[]>;
}

/** A place on a vessel. */
export interface VesselPosition {
  structureId: string;
  pieceId: string;
  /** Distance from the start of the piece. */
  along: number;
  /** Distance from where the vessel itself begins, counting the trunk before this branch. */
  fromStart: number;
  /** Distance from the given point to the centre line: about one radius for a point on the surface. */
  offset: number;
}

/** Part of one piece, between two distances along it. */
export interface Stretch {
  pieceId: string;
  from: number;
  to: number;
}

/** The nearest place on a vessel's centre line to a point. */
export interface Nearest {
  pieceIndex: number;
  along: number;
  offset: number;
}

interface Indexed {
  piece: Piece;
  structureId: string;
  /** Position of the piece among its vessel's pieces. */
  index: number;
  /** Distance along the piece at each point. */
  cumulative: number[];
  /** A box around the tube, for skipping pieces a point can't be on. */
  low: Point;
  high: Point;
}

/** Room around a tube when deciding whether a point could belong to it. */
const BOX_MARGIN = 0.002;

export class Centerlines {
  private readonly byStructure = new Map<string, Indexed[]>();
  private readonly byId = new Map<string, Indexed>();
  private readonly branches = new Map<string, Indexed[]>();

  constructor(file: CenterlinesFile) {
    for (const [structureId, pieces] of Object.entries(file.structures)) {
      const indexed = pieces.map((piece, index) => {
        const cumulative = [0];
        for (let i = 1; i < piece.points.length; i++) {
          cumulative.push(cumulative[i - 1] + distance(piece.points[i - 1], piece.points[i]));
        }
        const reach = Math.max(...piece.radius) + BOX_MARGIN;
        const axis = (k: 0 | 1 | 2) => piece.points.map((point) => point[k]);
        const low: Point = [Math.min(...axis(0)) - reach, Math.min(...axis(1)) - reach, Math.min(...axis(2)) - reach];
        const high: Point = [Math.max(...axis(0)) + reach, Math.max(...axis(1)) + reach, Math.max(...axis(2)) + reach];
        return { piece, structureId, index, cumulative, low, high };
      });
      this.byStructure.set(structureId, indexed);
      indexed.forEach((entry) => this.byId.set(entry.piece.id, entry));
    }
    for (const entry of this.byId.values()) {
      const host = entry.piece.attach?.piece;
      if (host === undefined) continue;
      this.branches.set(host, [...(this.branches.get(host) ?? []), entry]);
    }
  }

  /** True if the structure is a vessel with a centre line. */
  has(structureId: string): boolean {
    return this.byStructure.has(structureId);
  }

  pieces(structureId: string): readonly Piece[] {
    return (this.byStructure.get(structureId) ?? []).map((entry) => entry.piece);
  }

  piece(pieceId: string): Piece | undefined {
    return this.byId.get(pieceId)?.piece;
  }

  /** The vessel a piece belongs to. */
  structureOf(pieceId: string): string | undefined {
    return this.byId.get(pieceId)?.structureId;
  }

  /** The widest radius anywhere on a vessel, or 0 if it has no centre line. */
  maxRadius(structureId: string): number {
    return Math.max(0, ...this.pieces(structureId).flatMap((piece) => piece.radius));
  }

  /**
   * The nearest place on a vessel to a point on or near its surface.
   *
   * A point on the tube's surface is one radius from its own piece, so pieces
   * are compared by how far the point is from their surface, not from their
   * centre line. Plain distance would hand the base of a thin branch to the
   * thick trunk it leaves.
   */
  nearest(structureId: string, point: Point): Nearest | null {
    const pieces = this.byStructure.get(structureId);
    if (!pieces) return null;
    const inBox = pieces.filter((entry) => point.every((value, k) => value >= entry.low[k] && value <= entry.high[k]));
    let best: (Nearest & { score: number }) | null = null;
    for (const { piece, index, cumulative } of inBox.length > 0 ? inBox : pieces) {
      for (let i = 0; i + 1 < piece.points.length; i++) {
        const a = piece.points[i];
        const b = piece.points[i + 1];
        const ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
        const lengthSq = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2];
        const raw = lengthSq === 0 ? 0 : ((point[0] - a[0]) * ab[0] + (point[1] - a[1]) * ab[1] + (point[2] - a[2]) * ab[2]) / lengthSq;
        const t = Math.max(0, Math.min(1, raw));
        const offset = distance(point, [a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t]);
        const radius = piece.radius[i] + (piece.radius[i + 1] - piece.radius[i]) * t;
        const score = Math.abs(offset - radius);
        if (best === null || score < best.score) {
          best = { pieceIndex: index, along: cumulative[i] + Math.sqrt(lengthSq) * t, offset, score };
        }
      }
    }
    return best && { pieceIndex: best.pieceIndex, along: best.along, offset: best.offset };
  }

  /** Turn a point on a vessel's surface into a place on that vessel. */
  locate(structureId: string, point: Point): VesselPosition | null {
    const found = this.nearest(structureId, point);
    if (!found) return null;
    const pieceId = this.byStructure.get(structureId)![found.pieceIndex].piece.id;
    return { structureId, pieceId, along: found.along, fromStart: this.fromStart(pieceId, found.along), offset: found.offset };
  }

  /** Distance from where the vessel begins to a place on one of its pieces, following the trunk. */
  fromStart(pieceId: string, along: number): number {
    let entry = this.byId.get(pieceId);
    let total = along;
    const seen = new Set<string>();
    while (entry?.piece.attach && !seen.has(entry.piece.id)) {
      seen.add(entry.piece.id);
      const host = this.byId.get(entry.piece.attach.piece);
      if (!host || host.structureId !== entry.structureId) break;
      total += entry.piece.attach.at;
      entry = host;
    }
    return total;
  }

  /** Part of a piece, with both ends kept inside it. */
  stretch(pieceId: string, from: number, to: number): Stretch {
    const length = this.byId.get(pieceId)?.piece.length ?? 0;
    const clamp = (value: number) => Math.max(0, Math.min(length, value));
    return { pieceId, from: clamp(Math.min(from, to)), to: clamp(Math.max(from, to)) };
  }

  /**
   * Everything further from the trunk than a place: the rest of its piece, and
   * every branch that leaves after it, in this vessel or another. In an artery
   * this is what a blockage at that place cuts off.
   */
  beyond(pieceId: string, along: number): Stretch[] {
    const start = this.byId.get(pieceId);
    if (!start) return [];
    const stretches = [this.stretch(pieceId, along, start.piece.length)];
    const seen = new Set([pieceId]);
    const visit = (hostId: string, after: number) => {
      for (const branch of this.branches.get(hostId) ?? []) {
        if (branch.piece.attach!.at < after || seen.has(branch.piece.id)) continue;
        seen.add(branch.piece.id);
        stretches.push({ pieceId: branch.piece.id, from: 0, to: branch.piece.length });
        visit(branch.piece.id, 0);
      }
    };
    visit(pieceId, stretches[0].from);
    return stretches;
  }
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

export const centerlines = new Centerlines(centerlinesJson as unknown as CenterlinesFile);
