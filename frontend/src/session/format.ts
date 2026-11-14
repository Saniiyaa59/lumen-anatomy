import { centerlines } from "../centerlines.ts";
import { getGroup, getStructure, region } from "../registry.ts";

/**
 * The shape of a study session as it travels between the backend and the
 * browser. Described field by field in docs/session_format.md; keep the two in
 * step. Field names are snake_case to match the JSON, and distances are metres
 * along a centre-line piece, as in centerlines.json.
 */

export const SESSION_FORMAT = "lumen.session/0.1";

/** Where a fact came from. Every piece of text the student reads has one. */
export type Source =
  | { type: "notes"; file: string; page: number }
  | { type: "atlas"; article: string; url: string | null }
  | { type: "web"; title: string; url: string }
  /** Measured on the 3D model itself, e.g. a length. */
  | { type: "model" };

export interface Statement {
  text: string;
  source: Source;
}

/** A place on a vessel: a centre-line piece and a distance along it. */
export interface Place {
  piece: string;
  at: number;
}

/** Part of one centre-line piece. */
export interface Region {
  piece: string;
  from: number;
  to: number;
}

export const SIDES = ["anterior", "posterior", "left", "right", "superior", "inferior"] as const;
export type Side = (typeof SIDES)[number];

/** What the camera should show. The viewer works out the camera position. */
export interface View {
  /** Structure ids to frame. */
  look_at: string[];
  /** The side to look from, or null to let the viewer pick one where they can be seen. */
  side: Side | null;
}

interface PartBase {
  id: string;
  title: string;
  view: View;
  /** What is hidden for this part, e.g. what is in the way: structure ids, or group ids to hide everything in a group. */
  hide: string[];
  /** What the student reads, in order. */
  statements: Statement[];
}

/** The model turns, hides what is in the way and highlights structures. */
export interface Demonstration extends PartBase {
  kind: "demonstration";
  highlight: string[];
}

/** A pulse runs along a vessel. With no end it spreads into every branch beyond the start. */
export interface Pulse extends PartBase {
  kind: "pulse";
  from: Place;
  to: Place | null;
}

/** The student drags a damage point along one piece; everything beyond it greys out. */
export interface DamageSlider extends PartBase {
  kind: "damage_slider";
  track: Region;
  start_at: number;
  /** Text shown while the damage point is inside a zone. */
  zones: { regions: Region[]; statement: Statement }[];
}

/** Where on the model a click counts: stretches of vessel and/or whole structures. */
export interface Target {
  regions: Region[];
  structures: string[];
}

/** A short patient story; the student clicks where the problem is. */
export interface ClickCase extends PartBase {
  kind: "click_case";
  /** An invented patient, so it has no source. The facts behind the answer are in `feedback`. */
  story: string;
  question: string;
  /** `tolerance` is how far past the end of a region a click still counts, in metres. */
  answer: Target & { tolerance: number };
  feedback: {
    correct: Statement;
    wrong: Statement;
    /** Wrong places that deserve their own explanation. */
    near_misses: (Target & { statement: Statement })[];
  };
}

export type Part = Demonstration | Pulse | DamageSlider | ClickCase;

export const PART_KINDS = ["demonstration", "pulse", "damage_slider", "click_case"] as const satisfies readonly Part["kind"][];

export interface PlanItem {
  part_id: string;
  title: string;
  kind: Part["kind"];
}

/** What the agent can show on the model and what it can only explain in words. */
export interface Scope {
  can_show: string[];
  words_only: string[];
}

export interface Summary {
  solid: string[];
  shaky: string[];
  sources: Source[];
}

/** The backend's first reply: what it understood and what it plans. */
export interface SessionStart {
  format: typeof SESSION_FORMAT;
  session_id: string;
  region: string;
  request: string;
  scope: Scope;
  plan: PlanItem[];
}

/** A whole session in one file: the start, every part and the summary. Used for the sample and for replaying. */
export interface RecordedSession extends SessionStart {
  parts: Part[];
  summary: Summary;
}

/** What the browser sends after the student answers a click case. */
export interface Answer {
  part_id: string;
  /** 1 for the first try. */
  attempt: number;
  structure_id: string;
  /** The exact point clicked, in the model's frame. */
  point: [number, number, number];
  /** For a vessel, where on it; both null otherwise. */
  piece: string | null;
  at: number | null;
  correct: boolean;
  /** Time from the case appearing to the click. */
  seconds: number;
}

/** Slack when comparing distances with a piece's length, for rounding in the files. */
const EPSILON = 1e-4;

type Fields = Record<string, unknown>;

/** How many entries a list field has, whether or not they are valid. Used so one bad entry is reported once, not also as "empty". */
function listed(fields: Fields, key: string): number {
  const value = fields[key];
  return Array.isArray(value) ? value.length : 0;
}

/** Collects everything wrong with a session, each with the path to the field. */
class Check {
  readonly problems: string[] = [];

  fail(path: string, message: string): void {
    this.problems.push(`${path}: ${message}`);
  }

  object(value: unknown, path: string): Fields | null {
    if (typeof value === "object" && value !== null && !Array.isArray(value)) return value as Fields;
    this.fail(path, "must be an object");
    return null;
  }

  text(fields: Fields, key: string, path: string): string | null {
    const value = fields[key];
    if (typeof value === "string" && value.trim() !== "") return value;
    this.fail(`${path}.${key}`, "must be a non-empty string");
    return null;
  }

  number(fields: Fields, key: string, path: string): number | null {
    const value = fields[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    this.fail(`${path}.${key}`, "must be a number");
    return null;
  }

  list(fields: Fields, key: string, path: string): unknown[] {
    const value = fields[key];
    if (Array.isArray(value)) return value;
    this.fail(`${path}.${key}`, "must be a list");
    return [];
  }

  texts(fields: Fields, key: string, path: string): string[] {
    const items = this.list(fields, key, path);
    items.forEach((item, i) => {
      if (typeof item !== "string" || item.trim() === "") this.fail(`${path}.${key}[${i}]`, "must be a non-empty string");
    });
    return items.filter((item): item is string => typeof item === "string");
  }

  structures(fields: Fields, key: string, path: string): string[] {
    const ids = this.texts(fields, key, path);
    ids.forEach((id, i) => {
      if (!getStructure(id)) this.fail(`${path}.${key}[${i}]`, `"${id}" is not a structure in this region`);
    });
    return ids;
  }

  /** Ids that may each be a structure or an atlas group. */
  structuresOrGroups(fields: Fields, key: string, path: string): void {
    this.texts(fields, key, path).forEach((id, i) => {
      if (!getStructure(id) && !getGroup(id)) this.fail(`${path}.${key}[${i}]`, `"${id}" is not a structure or a group in this region`);
    });
  }

  source(value: unknown, path: string): void {
    const fields = this.object(value, path);
    if (!fields) return;
    switch (fields.type) {
      case "notes": {
        this.text(fields, "file", path);
        const page = this.number(fields, "page", path);
        if (page !== null && (!Number.isInteger(page) || page < 1)) this.fail(`${path}.page`, "must be a page number, 1 or more");
        break;
      }
      case "atlas":
        this.text(fields, "article", path);
        if (fields.url !== null) this.link(fields, path);
        break;
      case "web":
        this.text(fields, "title", path);
        this.link(fields, path);
        break;
      case "model":
        break;
      default:
        this.fail(`${path}.type`, 'must be "notes", "atlas", "web" or "model"');
    }
  }

  private link(fields: Fields, path: string): void {
    const url = this.text(fields, "url", path);
    if (url !== null && !/^https?:\/\//.test(url)) this.fail(`${path}.url`, "must start with http:// or https://");
  }

  statement(value: unknown, path: string): void {
    const fields = this.object(value, path);
    if (!fields) return;
    this.text(fields, "text", path);
    this.source(fields.source, `${path}.source`);
  }

  place(value: unknown, path: string): Place | null {
    const fields = this.object(value, path);
    if (!fields) return null;
    const piece = this.text(fields, "piece", path);
    const at = this.number(fields, "at", path);
    if (piece === null || at === null) return null;
    const length = centerlines.piece(piece)?.length;
    if (length === undefined) {
      this.fail(`${path}.piece`, `"${piece}" is not a centre-line piece in this region`);
      return null;
    }
    if (at < 0 || at > length + EPSILON) {
      this.fail(`${path}.at`, `${at} is outside the piece, which is ${length} m long`);
      return null;
    }
    return { piece, at };
  }

  region(value: unknown, path: string): Region | null {
    const fields = this.object(value, path);
    if (!fields) return null;
    const piece = this.text(fields, "piece", path);
    const from = this.number(fields, "from", path);
    const to = this.number(fields, "to", path);
    if (piece === null || from === null || to === null) return null;
    const length = centerlines.piece(piece)?.length;
    if (length === undefined) {
      this.fail(`${path}.piece`, `"${piece}" is not a centre-line piece in this region`);
      return null;
    }
    if (from < 0 || to > length + EPSILON || from >= to) {
      this.fail(path, `from ${from} to ${to} is not a stretch of the piece, which is ${length} m long`);
      return null;
    }
    return { piece, from, to };
  }

  regions(fields: Fields, key: string, path: string): Region[] {
    return this.list(fields, key, path)
      .map((item, i) => this.region(item, `${path}.${key}[${i}]`))
      .filter((item): item is Region => item !== null);
  }

  target(fields: Fields, path: string): Target {
    return { regions: this.regions(fields, "regions", path), structures: this.structures(fields, "structures", path) };
  }

  view(value: unknown, path: string): void {
    const fields = this.object(value, path);
    if (!fields) return;
    if (this.structures(fields, "look_at", path).length === 0) this.fail(`${path}.look_at`, "must name at least one structure");
    if (fields.side !== null && !SIDES.includes(fields.side as Side)) {
      this.fail(`${path}.side`, `must be null or one of ${SIDES.join(", ")}`);
    }
  }

  part(value: unknown, path: string): { id: string; kind: string } | null {
    const fields = this.object(value, path);
    if (!fields) return null;
    const id = this.text(fields, "id", path);
    this.text(fields, "title", path);
    this.view(fields.view, `${path}.view`);
    this.structuresOrGroups(fields, "hide", path);
    const statements = this.list(fields, "statements", path);
    statements.forEach((item, i) => this.statement(item, `${path}.statements[${i}]`));

    switch (fields.kind) {
      case "demonstration":
        this.structures(fields, "highlight", path);
        if (statements.length === 0) this.fail(`${path}.statements`, "a demonstration needs at least one statement");
        break;
      case "pulse": {
        const from = this.place(fields.from, `${path}.from`);
        const to = fields.to === null ? null : this.place(fields.to, `${path}.to`);
        if (from && to) {
          const beyond = centerlines.beyond(from.piece, from.at);
          const reached = beyond.some((stretch) => stretch.pieceId === to.piece && to.at >= stretch.from - EPSILON);
          if (!reached) this.fail(`${path}.to`, "is not further along the vessel than the start, so a pulse can't run there");
        }
        break;
      }
      case "damage_slider": {
        const track = this.region(fields.track, `${path}.track`);
        const start = this.number(fields, "start_at", path);
        if (track && start !== null && (start < track.from || start > track.to)) {
          this.fail(`${path}.start_at`, `${start} is outside the track (${track.from} to ${track.to})`);
        }
        this.list(fields, "zones", path).forEach((zone, i) => {
          const zonePath = `${path}.zones[${i}]`;
          const zoneFields = this.object(zone, zonePath);
          if (!zoneFields) return;
          this.regions(zoneFields, "regions", zonePath);
          if (listed(zoneFields, "regions") === 0) this.fail(`${zonePath}.regions`, "must name at least one stretch");
          this.statement(zoneFields.statement, `${zonePath}.statement`);
        });
        break;
      }
      case "click_case":
        this.clickCase(fields, path);
        break;
      default:
        this.fail(`${path}.kind`, `must be one of ${PART_KINDS.join(", ")}`);
    }
    return id === null || typeof fields.kind !== "string" ? null : { id, kind: fields.kind };
  }

  private clickCase(fields: Fields, path: string): void {
    this.text(fields, "story", path);
    this.text(fields, "question", path);

    let answer: Target = { regions: [], structures: [] };
    const answerFields = this.object(fields.answer, `${path}.answer`);
    if (answerFields) {
      answer = this.target(answerFields, `${path}.answer`);
      if (listed(answerFields, "regions") + listed(answerFields, "structures") === 0) {
        this.fail(`${path}.answer`, "must name at least one stretch of vessel or one structure");
      }
      const tolerance = this.number(answerFields, "tolerance", `${path}.answer`);
      if (tolerance !== null && tolerance < 0) this.fail(`${path}.answer.tolerance`, "must be 0 or more");
    }

    const feedback = this.object(fields.feedback, `${path}.feedback`);
    if (!feedback) return;
    this.statement(feedback.correct, `${path}.feedback.correct`);
    this.statement(feedback.wrong, `${path}.feedback.wrong`);
    this.list(feedback, "near_misses", `${path}.feedback`).forEach((miss, i) => {
      const missPath = `${path}.feedback.near_misses[${i}]`;
      const missFields = this.object(miss, missPath);
      if (!missFields) return;
      const target = this.target(missFields, missPath);
      if (listed(missFields, "regions") + listed(missFields, "structures") === 0) {
        this.fail(missPath, "must name at least one stretch of vessel or one structure");
      }
      this.statement(missFields.statement, `${missPath}.statement`);
      // A place can't be both right and a near miss.
      const overlapsAnswer =
        target.structures.some((id) => answer.structures.includes(id)) ||
        target.regions.some((a) => answer.regions.some((b) => a.piece === b.piece && a.from < b.to && b.from < a.to));
      if (overlapsAnswer) this.fail(missPath, "overlaps the correct answer");
    });
  }
}

/**
 * Everything wrong with a recorded session, or an empty list if it is sound.
 *
 * Checks the shape and that every id, piece and distance refers to something
 * real on the loaded model. It cannot check that an atlas article exists (the
 * articles file is not loaded in the browser) or that the anatomy is right.
 */
export function checkSession(data: unknown): string[] {
  const check = new Check();
  const session = check.object(data, "session");
  if (!session) return check.problems;

  if (session.format !== SESSION_FORMAT) check.fail("session.format", `must be "${SESSION_FORMAT}"`);
  check.text(session, "session_id", "session");
  check.text(session, "request", "session");
  if (session.region !== region.region) check.fail("session.region", `must be "${region.region}", the region this viewer has loaded`);

  const scope = check.object(session.scope, "session.scope");
  if (scope) {
    check.texts(scope, "can_show", "session.scope");
    check.texts(scope, "words_only", "session.scope");
  }

  const parts = new Map<string, string>();
  check.list(session, "parts", "session").forEach((item, i) => {
    const part = check.part(item, `session.parts[${i}]`);
    if (!part) return;
    if (parts.has(part.id)) check.fail(`session.parts[${i}].id`, `"${part.id}" is used by more than one part`);
    parts.set(part.id, part.kind);
  });

  const plan = check.list(session, "plan", "session");
  if (plan.length === 0) check.fail("session.plan", "must have at least one item");
  plan.forEach((item, i) => {
    const path = `session.plan[${i}]`;
    const fields = check.object(item, path);
    if (!fields) return;
    check.text(fields, "title", path);
    const partId = check.text(fields, "part_id", path);
    if (partId === null) return;
    if (!parts.has(partId)) check.fail(`${path}.part_id`, `"${partId}" is not the id of a part`);
    else if (parts.get(partId) !== fields.kind) check.fail(`${path}.kind`, `must be "${parts.get(partId)}", the kind of part "${partId}"`);
  });

  const summary = check.object(session.summary, "session.summary");
  if (summary) {
    check.texts(summary, "solid", "session.summary");
    check.texts(summary, "shaky", "session.summary");
    check.list(summary, "sources", "session.summary").forEach((item, i) => check.source(item, `session.summary.sources[${i}]`));
  }
  return check.problems;
}

/** A recorded session, checked. Throws with every problem listed if it does not fit the format. */
export function parseSession(data: unknown): RecordedSession {
  const problems = checkSession(data);
  if (problems.length > 0) {
    throw new Error(`The session does not fit the format:\n- ${problems.join("\n- ")}`);
  }
  return data as RecordedSession;
}
