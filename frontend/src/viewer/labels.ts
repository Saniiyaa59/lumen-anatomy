import * as THREE from "three";
import { displayName } from "../registry.ts";

/** How many candidate anchor points are kept per structure. */
const ANCHORS_PER_STRUCTURE = 8;
/** How many candidates are ray-tested per structure when choosing a visible anchor. */
const MAX_ANCHOR_TESTS = 3;
/** Seconds between visibility checks while the camera moves. Positions still update every frame. */
const VISIBILITY_INTERVAL = 0.12;
/** Roughly the heart's radius in world units; the label columns sit just outside it. */
const MODEL_RADIUS = 0.8;
/** Pixels between the heart's edge and a label column. */
const COLUMN_MARGIN = 40;
/** Narrowest space kept for label text at the screen edge, in pixels. */
const COLUMN_MIN_WIDTH = 190;
/** Length of the flat part of a leader line next to its text, in pixels. */
const ELBOW = 16;
/** Smallest vertical distance between two labels in a column, in pixels. */
const LABEL_GAP = 22;
/** Space kept clear at the top (status badge, toggle) and bottom (chips), in pixels. */
const TOP_PADDING = 56;
const BOTTOM_PADDING = 96;
/** How quickly labels glide to a new position; higher is snappier. */
const EASE_RATE = 14;

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * Pick `count` points that are spread far apart, starting with the one
 * farthest from the origin (the heart's middle), so the first choice sits on
 * the structure's outer surface.
 */
export function spreadPoints(
  points: readonly THREE.Vector3[],
  count: number,
): THREE.Vector3[] {
  if (points.length <= count) return [...points];
  const chosen: THREE.Vector3[] = [];
  const nearest = new Float32Array(points.length).fill(Infinity);
  let next = 0;
  points.forEach((point, index) => {
    if (point.lengthSq() > points[next].lengthSq()) next = index;
  });
  while (chosen.length < count) {
    const picked = points[next];
    chosen.push(picked);
    let farthest = -1;
    for (let index = 0; index < points.length; index++) {
      nearest[index] = Math.min(
        nearest[index],
        points[index].distanceToSquared(picked),
      );
      if (farthest === -1 || nearest[index] > nearest[farthest])
        farthest = index;
    }
    next = farthest;
  }
  return chosen;
}

/**
 * Place labels in a column. `desired` holds the wanted vertical positions in
 * ascending order; the result keeps that order, at least `gap` apart, inside
 * `min`..`max` where they fit (extra labels overflow at the top).
 */
export function stackLabels(
  desired: readonly number[],
  gap: number,
  min: number,
  max: number,
): number[] {
  const stacked: number[] = [];
  let previous = -Infinity;
  for (const position of desired) {
    previous = Math.max(position, previous + gap, min);
    stacked.push(previous);
  }
  let limit = max;
  for (let index = stacked.length - 1; index >= 0; index--) {
    stacked[index] = Math.min(stacked[index], limit);
    limit = stacked[index] - gap;
  }
  return stacked;
}

export interface LabelLayerOptions {
  container: HTMLElement;
  camera: THREE.PerspectiveCamera;
  /** The structure first hit by a ray from the camera toward a world point, or null. */
  structureToward(point: THREE.Vector3): string | null;
  onEnter(structureId: string): void;
  onLeave(structureId: string): void;
  onClick(structureId: string, additive: boolean): void;
}

interface Label {
  structureId: string;
  /** Points on the structure's surface that the leader line may attach to. */
  candidates: THREE.Vector3[];
  /** The candidate currently in use, or null while the structure can't be seen. */
  anchor: THREE.Vector3 | null;
  text: HTMLButtonElement;
  line: SVGPolylineElement;
  dot: SVGCircleElement;
  /** Current position of the text's inner edge, eased toward its target. */
  x: number;
  y: number;
  /** False until the label has been positioned once, so it appears in place instead of sliding in. */
  placed: boolean;
}

interface Placement {
  label: Label;
  anchorX: number;
  anchorY: number;
}

/**
 * Names every visible structure with a faint leader line, like an atlas plate.
 *
 * Labels sit in two columns beside the heart. A structure is only labeled
 * while some point on it can be seen from the camera, so hidden or covered
 * structures (e.g. valves inside the chambers) get no label.
 */
export class LabelLayer {
  private readonly options: LabelLayerOptions;
  private readonly root: HTMLDivElement;
  private readonly svg: SVGSVGElement;
  private readonly labels = new Map<string, Label>();
  private visible = true;
  /** True when the camera or the scene changed, so visible anchors must be chosen again. */
  private stale = true;
  private sinceVisibilityCheck = Infinity;

  constructor(options: LabelLayerOptions) {
    this.options = options;
    this.root = document.createElement("div");
    this.root.className = "scene-labels";
    this.svg = document.createElementNS(SVG_NS, "svg");
    this.root.appendChild(this.svg);
    options.container.appendChild(this.root);
  }

  /** Register a structure and the surface points its label may point at. */
  addStructure(structureId: string, surfacePoints: THREE.Vector3[]): void {
    const text = document.createElement("button");
    text.type = "button";
    text.className = "scene-label";
    text.textContent = displayName(structureId);
    text.addEventListener("pointerenter", () =>
      this.options.onEnter(structureId),
    );
    text.addEventListener("pointerleave", () =>
      this.options.onLeave(structureId),
    );
    text.addEventListener("click", (event) =>
      this.options.onClick(structureId, event.shiftKey),
    );
    const line = document.createElementNS(SVG_NS, "polyline");
    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("r", "2.5");
    this.svg.append(line, dot);
    this.root.appendChild(text);
    this.labels.set(structureId, {
      structureId,
      candidates: spreadPoints(surfacePoints, ANCHORS_PER_STRUCTURE),
      anchor: null,
      text,
      line,
      dot,
      x: 0,
      y: 0,
      placed: false,
    });
    this.stale = true;
  }

  setVisible(visible: boolean): void {
    this.visible = visible;
    this.root.hidden = !visible;
    if (visible) this.invalidate();
  }

  /** Call when the camera moves or structures are shown or hidden. */
  readonly invalidate = (): void => {
    this.stale = true;
  };

  /** Draw these structures' labels at full strength (the hovered and selected ones). */
  setEmphasized(structureIds: ReadonlySet<string>): void {
    for (const label of this.labels.values()) {
      const emphasized = structureIds.has(label.structureId);
      for (const element of [label.text, label.line, label.dot]) {
        element.classList.toggle("is-emphasized", emphasized);
      }
    }
  }

  /** Call once per frame. */
  update(deltaSeconds: number): void {
    if (!this.visible) return;
    this.sinceVisibilityCheck += deltaSeconds;
    if (this.stale && this.sinceVisibilityCheck >= VISIBILITY_INTERVAL) {
      this.stale = false;
      this.sinceVisibilityCheck = 0;
      this.chooseAnchors();
    }
    this.layOut(deltaSeconds);
  }

  dispose(): void {
    this.root.remove();
  }

  /** For each structure, find a surface point the camera can see, preferring the current one. */
  private chooseAnchors(): void {
    const { camera, structureToward } = this.options;
    for (const label of this.labels.values()) {
      const byDistance = [...label.candidates].sort(
        (a, b) =>
          a.distanceToSquared(camera.position) -
          b.distanceToSquared(camera.position),
      );
      const order = label.anchor
        ? [label.anchor, ...byDistance.filter((c) => c !== label.anchor)]
        : byDistance;
      label.anchor =
        order
          .slice(0, MAX_ANCHOR_TESTS)
          .find((point) => structureToward(point) === label.structureId) ??
        null;
    }
  }

  private layOut(deltaSeconds: number): void {
    const { container, camera } = this.options;
    const width = container.clientWidth;
    const height = container.clientHeight;
    const project = (point: THREE.Vector3) => {
      const ndc = point.clone().project(camera);
      return {
        x: ((ndc.x + 1) / 2) * width,
        y: ((1 - ndc.y) / 2) * height,
        onScreen: Math.abs(ndc.x) <= 1 && Math.abs(ndc.y) <= 1 && ndc.z < 1,
      };
    };

    // The columns sit just outside the heart, but never off the screen.
    const center = project(new THREE.Vector3());
    const right = new THREE.Vector3().setFromMatrixColumn(
      camera.matrixWorld,
      0,
    );
    const radius =
      project(right.multiplyScalar(MODEL_RADIUS)).x - center.x + COLUMN_MARGIN;
    const leftX = Math.max(
      COLUMN_MIN_WIDTH,
      Math.min(center.x - radius, width / 2 - ELBOW),
    );
    const rightX = Math.min(
      width - COLUMN_MIN_WIDTH,
      Math.max(center.x + radius, width / 2 + ELBOW),
    );

    const columns: { left: Placement[]; right: Placement[] } = {
      left: [],
      right: [],
    };
    for (const label of this.labels.values()) {
      const anchor = label.anchor && project(label.anchor);
      if (!anchor || !anchor.onScreen) {
        this.hide(label);
        continue;
      }
      (anchor.x < center.x ? columns.left : columns.right).push({
        label,
        anchorX: anchor.x,
        anchorY: anchor.y,
      });
    }

    const ease = 1 - Math.exp(-deltaSeconds * EASE_RATE);
    for (const side of ["left", "right"] as const) {
      const placements = columns[side].sort((a, b) => a.anchorY - b.anchorY);
      const targetX = side === "left" ? leftX : rightX;
      const targetYs = stackLabels(
        placements.map((placement) => placement.anchorY),
        LABEL_GAP,
        TOP_PADDING,
        height - BOTTOM_PADDING,
      );
      placements.forEach(({ label, anchorX, anchorY }, index) => {
        if (label.placed) {
          label.x += (targetX - label.x) * ease;
          label.y += (targetYs[index] - label.y) * ease;
        } else {
          label.x = targetX;
          label.y = targetYs[index];
          label.placed = true;
        }
        this.draw(label, side, anchorX, anchorY);
      });
    }
  }

  private draw(
    label: Label,
    side: "left" | "right",
    anchorX: number,
    anchorY: number,
  ): void {
    const { text, line, dot, x, y } = label;
    // The line runs from the structure to a short flat stretch beside the text.
    const elbowX = side === "left" ? x + ELBOW : x - ELBOW;
    line.setAttribute(
      "points",
      `${anchorX},${anchorY} ${elbowX},${y} ${x},${y}`,
    );
    dot.setAttribute("cx", String(anchorX));
    dot.setAttribute("cy", String(anchorY));
    // Left-column text ends at x; right-column text starts there.
    const shift = side === "left" ? "calc(-100% - 6px)" : "6px";
    text.style.transform = `translate(${x}px, ${y}px) translate(${shift}, -50%)`;
    for (const element of [text, line, dot]) {
      element.classList.add("is-shown");
    }
  }

  private hide(label: Label): void {
    if (!label.placed) return;
    label.placed = false;
    for (const element of [label.text, label.line, label.dot]) {
      element.classList.remove("is-shown");
    }
  }
}
