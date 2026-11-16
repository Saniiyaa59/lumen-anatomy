import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { acceleratedRaycast, MeshBVH } from "three-mesh-bvh";
import modelUrl from "../../../assets/regions/heart/model.glb?url";
import { centerlines, type Point, type Stretch } from "../centerlines.ts";
import {
  getStructure,
  region,
  structures,
  structuresUnder,
  type Structure,
} from "../registry.ts";
import type { ClickPlace, SelectionStore } from "../selection/store.ts";
import type { Side } from "../session/format.ts";
import type { VisibilityStore } from "../visibility/store.ts";
import { baseColor, HIGHLIGHT_COLOR, SELECTED_COLOR } from "./colors.ts";
import { LabelLayer } from "./labels.ts";

/** The model is scaled so its longest side is this many world units. */
const MODEL_SIZE = 2;
/** A press that moves less than this many pixels is a click, not a camera drag. */
const CLICK_SLOP_PX = 4;
/** At most this many vertices per structure are considered as label anchor points. */
const LABEL_ANCHOR_SAMPLES = 1500;

/** How big a structure is, worked out from its shape when the model loads. */
type SizeClass = "large" | "medium" | "small";
/** A surface at least this long, in metres, is large (the chambers); smaller ones are small (leaflets, papillary muscles). */
const LARGE_SURFACE = 0.04;
/** A vessel narrower than this radius, in metres, is thin: the coronary arteries and cardiac veins. */
const THIN_VESSEL = 0.003;

/**
 * How a hovered structure gets bigger, by its size.
 * `scale` grows it around its middle, as a fraction of its size. `swell` also
 * pushes its surface outward, in world units, which is what makes thin vessels
 * look thicker.
 */
const HOVER_GROWTH: Record<SizeClass, { scale: number; swell: number }> = {
  large: { scale: 0.06, swell: 0 },
  medium: { scale: 0.06, swell: 0.004 },
  small: { scale: 0.05, swell: 0.008 },
};
/** How long a structure takes to grow or shrink back. */
const HOVER_SECONDS = 0.12;
/** Safety margin on how far the coronary vessels are lifted over a grown structure. */
const SURFACE_LIFT_MARGIN = 2;

/** Where the camera starts and returns to: the anterior view (+Z is the front of the heart). */
const HOME_POSITION = new THREE.Vector3(0, 0.15, 3.1);
const HOME_TARGET = new THREE.Vector3(0, 0, 0);
/** How long the camera takes to glide to a new view. */
const CAMERA_MOVE_SECONDS = 0.6;

/**
 * Which way the camera looks from for each side of the body. The model faces
 * +Z, with the patient's left on +X and up on +Y. Straight up and straight down
 * are tilted slightly, because the orbit controls cannot look exactly along Y.
 */
const SIDE_DIRECTIONS: Record<Side, THREE.Vector3> = {
  anterior: new THREE.Vector3(0, 0, 1),
  left: new THREE.Vector3(1, 0, 0),
  right: new THREE.Vector3(-1, 0, 0),
  posterior: new THREE.Vector3(0, 0, -1),
  superior: new THREE.Vector3(0, 1, 0.15).normalize(),
  inferior: new THREE.Vector3(0, -1, 0.15).normalize(),
};
/** Space left around framed structures, as a multiple of the tightest fit. */
const FRAME_MARGIN = 1.35;
/** How many surface points per structure are tested when choosing the side it is seen best from. */
const FRAME_SAMPLES = 24;

/** A camera glide in progress. The camera orbits its target, so it swings around the heart instead of cutting through it. */
interface CameraMove {
  fromTarget: THREE.Vector3;
  toTarget: THREE.Vector3;
  /** Camera position relative to its target, as distance and angles. */
  fromOrbit: THREE.Spherical;
  toOrbit: THREE.Spherical;
  elapsed: number;
}

// Draws a hovered structure bigger in the shader, without moving its geometry,
// so picking is unaffected. A grown chamber would swallow the coronary vessels
// lying on it, so those are drawn `uSurfaceLift` closer to the camera (depth
// only, they don't move on screen) and stay visible on top.
const HOVER_VERTEX_PARS = /* glsl */ `
uniform float uHoverGrow;
uniform vec3 uHoverCenter;
uniform float uHoverScale;
uniform float uHoverSwell;
uniform float uSurfaceLift;
`;
const HOVER_VERTEX_PROJECT = /* glsl */ `
#include <project_vertex>
if (uHoverGrow > 0.0) {
  vec4 grown = modelMatrix * vec4(transformed, 1.0);
  grown.xyz = uHoverCenter + (grown.xyz - uHoverCenter) * (1.0 + uHoverScale * uHoverGrow);
  grown.xyz += normalize(mat3(modelMatrix) * objectNormal) * (uHoverSwell * uHoverGrow);
  mvPosition = viewMatrix * grown;
  gl_Position = projectionMatrix * mvPosition;
}
if (uSurfaceLift > 0.0) {
  vec4 lifted = projectionMatrix * (mvPosition + vec4(0.0, 0.0, uSurfaceLift, 0.0));
  gl_Position.z = lifted.z / lifted.w * gl_Position.w;
}
`;

// Vessels can have part of their length painted. Each vertex carries a color
// and how strongly to apply it (`aMark`, all zero when nothing is painted).
const MARK_VERTEX_PARS = /* glsl */ `
attribute vec4 aMark;
varying vec4 vMark;
`;
const MARK_VERTEX_MAIN = /* glsl */ `
vMark = aMark;
`;
const MARK_FRAGMENT_PARS = /* glsl */ `
varying vec4 vMark;
`;
const MARK_FRAGMENT_COLOR = /* glsl */ `
#include <color_fragment>
diffuseColor.rgb = mix(diffuseColor.rgb, vMark.rgb, vMark.a);
`;

const SELECTED_TINT = new THREE.Color(SELECTED_COLOR);
const SELECTED_EMISSIVE = new THREE.Color(SELECTED_COLOR).multiplyScalar(0.3);
const HIGHLIGHT_TINT = new THREE.Color(HIGHLIGHT_COLOR);
const HIGHLIGHT_EMISSIVE = new THREE.Color(HIGHLIGHT_COLOR).multiplyScalar(0.25);

/** For each vertex of a vessel's mesh: which piece of the centre line it surrounds, and how far along. */
interface VertexPlaces {
  pieceIndex: Uint16Array;
  along: Float32Array;
}

/** One painted layer: some stretches of vessel in one color. Layers added later cover earlier ones. */
interface Paint {
  stretches: readonly Stretch[];
  color: THREE.Color;
}

interface StructureVisual {
  meshes: THREE.Mesh[];
  /** Shared by all of the structure's meshes, so the structure lights up as one. */
  material: THREE.MeshStandardMaterial;
  baseColor: THREE.Color;
  sizeClass: SizeClass;
  /** True for thin vessels lying on the heart, which are drawn over a grown chamber instead of growing into it. */
  lifted: boolean;
  /** Worked out the first time the vessel is painted; null until then, and always for non-vessels. */
  vertexPlaces: VertexPlaces[] | null;
  /** Shader inputs for the hover effect: 0 (normal size) to 1 (fully grown), and the structure's middle in world space. */
  hoverGrow: { value: number };
  hoverCenter: { value: THREE.Vector3 };
  /** The `hoverGrow` value the structure is easing toward; see `stepHoverGrow`. */
  targetGrow: number;
  /** How far the structure's surface moves when fully grown, in world units. 0 for the coronary vessels, which are lifted rather than covered. */
  hoverRise: number;
}

export interface HoverInfo {
  structureId: string;
  clientX: number;
  clientY: number;
}

/** What a click or a hover test landed on. */
export interface Hit {
  structureId: string;
  /** The exact point on the surface, in world space. */
  point: THREE.Vector3;
}

export interface VisibilityTarget {
  structureIds?: readonly string[];
  /** Atlas group ids; every structure inside a group is included. */
  groups?: readonly string[];
}

/**
 * Owns the Three.js scene, camera, renderer and controls.
 *
 * Kept outside React on purpose: the action executor (and the dev console)
 * call its methods directly, without going through React state.
 */
export class SceneController {
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100);
  /** Resolves when the heart model is loaded; rejects if it can't be. */
  readonly ready: Promise<void>;
  /** Called when the structure under the cursor changes or the cursor moves over one. */
  onHover: ((hover: HoverInfo | null) => void) | null = null;
  /**
   * Called for a click that lands on a structure, before it selects anything.
   * Return true to use the click up (a session answer, a slider move); the
   * selection then stays as it was.
   */
  onPlaceClick: ((structureId: string, place: ClickPlace) => boolean) | null =
    null;
  /** Called once per frame before drawing, for animations such as a pulse. */
  onFrame: ((deltaSeconds: number) => void) | null = null;

  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly resizeObserver: ResizeObserver;
  private readonly container: HTMLElement;
  private readonly selection: SelectionStore;
  private readonly unsubscribeSelection: () => void;
  private readonly visibility: VisibilityStore;
  private readonly unsubscribeVisibility: () => void;
  private readonly labels: LabelLayer;

  private readonly visuals = new Map<string, StructureVisual>();
  private readonly raycaster = new THREE.Raycaster();
  /** Shader input shared by the thin vessels' materials; see HOVER_VERTEX_PARS. */
  private readonly surfaceLift = { value: 0 };
  /** The loaded model. Its own frame is the atlas' (metres); the scene scales and centers it. */
  private model: THREE.Object3D | null = null;
  private readonly paints = new Map<string, Paint>();
  /** Structures a session is pointing out; drawn tinted, like a softer selection. */
  private highlighted: ReadonlySet<string> = new Set();
  private hoveredId: string | null = null;
  /** Latest cursor position waiting for a hover test on the next frame. */
  private pendingHover: { clientX: number; clientY: number } | null = null;
  private pressStart: { x: number; y: number } | null = null;
  private lastFrameTime = 0;
  private cameraMove: CameraMove | null = null;
  private disposed = false;

  constructor(
    container: HTMLElement,
    selection: SelectionStore,
    visibility: VisibilityStore,
  ) {
    this.container = container;
    this.selection = selection;
    this.visibility = visibility;

    // Only the nearest hit is ever needed, which lets rays stop early.
    this.raycaster.firstHitOnly = true;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.camera.position.copy(HOME_POSITION);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.minDistance = 0.3;
    this.controls.maxDistance = 8;

    this.scene.background = new THREE.Color(0x101418);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 1.4));
    // The key light follows the camera so the side being looked at is always lit.
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.6);
    keyLight.position.set(1, 1.5, 2);
    this.camera.add(keyLight);
    this.scene.add(this.camera);

    const canvas = this.renderer.domElement;
    canvas.addEventListener("pointerdown", this.onPointerDown);
    canvas.addEventListener("pointermove", this.onPointerMove);
    canvas.addEventListener("pointerup", this.onPointerUp);
    canvas.addEventListener("pointerleave", this.onPointerLeave);

    this.labels = new LabelLayer({
      container,
      camera: this.camera,
      structureToward: this.structureToward,
      // Pointing at a label works like pointing at its structure.
      onEnter: (structureId) => {
        this.pendingHover = null;
        this.setHovered(structureId);
      },
      onLeave: (structureId) => {
        if (this.hoveredId === structureId) this.setHovered(null);
      },
      onClick: (structureId, additive) =>
        this.selection.click(structureId, additive),
    });
    this.controls.addEventListener("change", this.labels.invalidate);
    // Grabbing the view takes over from a camera glide.
    this.controls.addEventListener("start", this.endCameraMove);

    this.unsubscribeSelection = selection.subscribe(this.refreshVisuals);
    this.unsubscribeVisibility = visibility.subscribe(this.applyVisibility);

    this.resizeObserver = new ResizeObserver(this.resize);
    this.resizeObserver.observe(container);
    this.resize();

    this.renderer.setAnimationLoop(this.tick);
    this.ready = this.loadModel();
  }

  /** IDs of the structures that have at least one mesh in the loaded model. */
  get structureIds(): string[] {
    return [...this.visuals.keys()];
  }

  /** The structure under a screen point, or null. Hidden structures can't be picked. */
  pick(clientX: number, clientY: number): string | null {
    return this.hitAt(clientX, clientY)?.structureId ?? null;
  }

  /** The structure under a screen point and the exact point hit, or null. */
  hitAt(clientX: number, clientY: number): Hit | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(pointer, this.camera);
    this.raycaster.far = Infinity;
    return this.firstHit();
  }

  /**
   * Where a hit is in the model's own frame, and for a vessel which piece of it
   * and how far along. This is what makes a click gradable by place.
   */
  placeOf(hit: Hit): ClickPlace | undefined {
    if (!this.model) return undefined;
    const local = this.model.worldToLocal(hit.point.clone());
    const point: [number, number, number] = [local.x, local.y, local.z];
    return { point, vessel: centerlines.locate(hit.structureId, point) };
  }

  /**
   * Paint stretches of vessels in a color. Used to show a region on a vessel:
   * what a blockage cuts off, an answer, a pulse.
   *
   * Paint is kept in named layers. Painting a layer again replaces what it
   * held, so something that moves (a pulse, a slider) repaints its own layer
   * and leaves the others alone. Layers added later are drawn over earlier ones.
   */
  paint(
    stretches: readonly Stretch[],
    color: THREE.ColorRepresentation,
    layer = "default",
  ): void {
    const before = this.paints.get(layer)?.stretches ?? [];
    if (stretches.length === 0) this.paints.delete(layer);
    else this.paints.set(layer, { stretches, color: new THREE.Color(color) });
    this.applyPaint([...before, ...stretches]);
  }

  /** Remove one layer of paint, or everything painted when no layer is named. */
  clearPaint(layer?: string): void {
    const layers = layer === undefined ? [...this.paints.keys()] : [layer];
    const painted = layers.flatMap(
      (name) => this.paints.get(name)?.stretches ?? [],
    );
    layers.forEach((name) => this.paints.delete(name));
    this.applyPaint(painted);
  }

  /** Tint these structures to point them out. Replaces the previous set. */
  setHighlighted(structureIds: Iterable<string>): void {
    this.highlighted = new Set(structureIds);
    this.refreshVisuals();
  }

  /**
   * Glide the camera to show these structures from one side of the body. With
   * no side given, picks the side from which most of them can be seen.
   */
  frame(structureIds: readonly string[], side: Side | null): void {
    const meshes = structureIds.flatMap(
      (id) => this.visuals.get(id)?.meshes ?? [],
    );
    if (meshes.length === 0) return;
    const bounds = new THREE.Box3();
    meshes.forEach((mesh) => bounds.expandByObject(mesh));
    const sphere = bounds.getBoundingSphere(new THREE.Sphere());
    // Fit the narrower of the view's height and width.
    const halfHeight = THREE.MathUtils.degToRad(this.camera.fov / 2);
    const halfWidth = Math.atan(Math.tan(halfHeight) * this.camera.aspect);
    const distance = THREE.MathUtils.clamp(
      (sphere.radius / Math.sin(Math.min(halfHeight, halfWidth))) * FRAME_MARGIN,
      this.controls.minDistance * 1.5,
      this.controls.maxDistance,
    );
    const direction = side
      ? SIDE_DIRECTIONS[side]
      : this.clearestSide(structureIds, sphere.center, distance);
    this.glideTo(
      sphere.center,
      sphere.center.clone().addScaledVector(direction, distance),
    );
  }

  /** Glide the camera back to where it started: the anterior view, centered, at the default zoom. */
  resetView(): void {
    this.glideTo(HOME_TARGET, HOME_POSITION);
  }

  /** Start a glide to a new camera position, looking at a new target. */
  private glideTo(target: THREE.Vector3, position: THREE.Vector3): void {
    const current = this.controls.target;
    this.cameraMove = {
      fromTarget: current.clone(),
      toTarget: target.clone(),
      fromOrbit: new THREE.Spherical().setFromVector3(
        this.camera.position.clone().sub(current),
      ),
      toOrbit: new THREE.Spherical().setFromVector3(
        position.clone().sub(target),
      ),
      elapsed: 0,
    };
    // Leftover spin from the last drag would fight the glide.
    this.controls.enableDamping = false;
  }

  /**
   * The side from which the most of these structures can be seen, looking at
   * `center` from `distance` away. Sides are tried front first, so a tie goes
   * to the more familiar view.
   */
  private clearestSide(
    structureIds: readonly string[],
    center: THREE.Vector3,
    distance: number,
  ): THREE.Vector3 {
    const samples = structureIds.flatMap((id) => {
      const points = surfaceSample(this.visuals.get(id)?.meshes ?? []);
      const stride = Math.max(1, Math.ceil(points.length / FRAME_SAMPLES));
      return points
        .filter((_, index) => index % stride === 0)
        .map((point) => ({ id, point }));
    });
    let best = SIDE_DIRECTIONS.anterior;
    let bestSeen = -1;
    for (const direction of Object.values(SIDE_DIRECTIONS)) {
      const eye = center.clone().addScaledVector(direction, distance);
      const seen = samples.filter(({ id, point }) => {
        const toward = point.clone().sub(eye);
        this.raycaster.far = toward.length() + 0.01;
        this.raycaster.set(eye, toward.normalize());
        return this.firstHit()?.structureId === id;
      }).length;
      if (seen > bestSeen) {
        best = direction;
        bestSeen = seen;
      }
    }
    return best;
  }

  /** Show or hide the name labels around the heart. */
  setLabelsVisible(visible: boolean): void {
    this.labels.setVisible(visible);
  }

  /** Show or hide structures, by ID and/or by atlas group. The structure panel follows along. */
  setVisibility(
    { structureIds = [], groups = [] }: VisibilityTarget,
    visible: boolean,
  ): void {
    const ids = new Set(structureIds.filter((id) => getStructure(id)));
    for (const group of groups) {
      structuresUnder(group).forEach((structure) => ids.add(structure.id));
    }
    this.visibility.setVisible(ids, visible);
  }

  dispose(): void {
    this.disposed = true;
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    this.unsubscribeSelection();
    this.unsubscribeVisibility();
    this.controls.removeEventListener("change", this.labels.invalidate);
    this.controls.removeEventListener("start", this.endCameraMove);
    this.labels.dispose();
    const canvas = this.renderer.domElement;
    canvas.removeEventListener("pointerdown", this.onPointerDown);
    canvas.removeEventListener("pointermove", this.onPointerMove);
    canvas.removeEventListener("pointerup", this.onPointerUp);
    canvas.removeEventListener("pointerleave", this.onPointerLeave);
    this.controls.dispose();
    this.scene.traverse((object) => {
      if (object instanceof THREE.Mesh) {
        object.geometry.dispose();
        const materials = Array.isArray(object.material)
          ? object.material
          : [object.material];
        materials.forEach((material) => material.dispose());
      }
    });
    this.renderer.dispose();
    canvas.remove();
  }

  private async loadModel(): Promise<void> {
    const gltf = await new GLTFLoader().loadAsync(modelUrl);
    if (this.disposed) return;
    const model = gltf.scene;

    // Each mesh in model.glb is one structure and is named by its id.
    const unknown: string[] = [];
    model.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const structure = getStructure(object.name);
      if (structure === undefined) {
        unknown.push(object.name);
        object.visible = false;
        return;
      }
      object.userData.structureId = structure.id;
      // A search tree over the triangles. Without it every ray tests all ~300k
      // triangles, which is too slow for the label visibility checks.
      object.geometry.boundsTree = new MeshBVH(object.geometry);
      object.raycast = acceleratedRaycast;
      if (structure.kind === "tube") {
        // The shader reads this for every vessel, so it must exist before anything is painted.
        const count = object.geometry.attributes.position.count;
        object.geometry.setAttribute(
          "aMark",
          new THREE.BufferAttribute(new Float32Array(count * 4), 4),
        );
      }
      const exported = object.material as THREE.Material | THREE.Material[];
      (Array.isArray(exported) ? exported : [exported]).forEach((material) =>
        material.dispose(),
      );
      const visual = this.visualFor(structure, object);
      object.material = visual.material;
      visual.meshes.push(object);
    });
    if (unknown.length > 0) {
      console.warn(
        "model.glb meshes missing from structures.json (hidden):",
        unknown,
      );
    }
    const missing = structures
      .filter((structure) => !this.visuals.has(structure.id))
      .map((structure) => structure.id);
    if (missing.length > 0) {
      console.warn(
        "structures.json entries with no mesh in model.glb:",
        missing,
      );
    }

    // Scale the whole model to MODEL_SIZE, and put the middle of the region's
    // own structures (the heart's chambers) at the origin, so the camera orbits
    // the heart itself, not the vessels' extent.
    const size = new THREE.Box3()
      .setFromObject(model)
      .getSize(new THREE.Vector3());
    const scale = MODEL_SIZE / Math.max(size.x, size.y, size.z);
    const core = new THREE.Box3();
    for (const structure of structures) {
      if (structure.parent !== region.region) continue;
      this.visuals
        .get(structure.id)
        ?.meshes.forEach((mesh) => core.expandByObject(mesh));
    }
    const center = (
      core.isEmpty() ? new THREE.Box3().setFromObject(model) : core
    ).getCenter(new THREE.Vector3());
    model.scale.setScalar(scale);
    model.position.copy(center).multiplyScalar(-scale);

    // The hover effect grows each structure around its own middle.
    model.updateMatrixWorld(true);
    for (const structure of structures) {
      const visual = this.visuals.get(structure.id);
      if (!visual) continue;
      const bounds = new THREE.Box3();
      visual.meshes.forEach((mesh) => bounds.expandByObject(mesh));
      bounds.getCenter(visual.hoverCenter.value);
      if (!visual.lifted) {
        const extent = bounds.getSize(new THREE.Vector3());
        const growth = HOVER_GROWTH[visual.sizeClass];
        visual.hoverRise =
          (growth.scale * Math.max(extent.x, extent.y, extent.z)) / 2 +
          growth.swell;
      }
      this.labels.addStructure(structure.id, surfaceSample(visual.meshes));
    }

    this.model = model;
    this.scene.add(model);
    this.refreshVisuals();
    this.applyVisibility();
  }

  private visualFor(structure: Structure, mesh: THREE.Mesh): StructureVisual {
    let visual = this.visuals.get(structure.id);
    if (!visual) {
      // Size comes from the shape itself: a vessel's radius, or how long a surface is.
      const isTube = structure.kind === "tube";
      let sizeClass: SizeClass;
      if (isTube) {
        sizeClass =
          centerlines.maxRadius(structure.id) < THIN_VESSEL ? "small" : "medium";
      } else {
        mesh.geometry.computeBoundingBox();
        const extent = mesh.geometry.boundingBox!.getSize(new THREE.Vector3());
        sizeClass =
          Math.max(extent.x, extent.y, extent.z) >= LARGE_SURFACE
            ? "large"
            : "small";
      }
      const lifted = isTube && sizeClass === "small";
      const color = new THREE.Color(baseColor(structure));
      const hoverGrow = { value: 0 };
      const hoverCenter = { value: new THREE.Vector3() };
      // Double-sided because valve leaflets are thin and seen from both sides.
      const material = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.55,
        side: THREE.DoubleSide,
      });
      const growth = HOVER_GROWTH[sizeClass];
      const surfaceLift = lifted ? this.surfaceLift : { value: 0 };
      material.onBeforeCompile = (shader) => {
        shader.uniforms.uHoverGrow = hoverGrow;
        shader.uniforms.uHoverCenter = hoverCenter;
        shader.uniforms.uHoverScale = { value: growth.scale };
        shader.uniforms.uHoverSwell = { value: growth.swell };
        shader.uniforms.uSurfaceLift = surfaceLift;
        shader.vertexShader = shader.vertexShader
          .replace(
            "#include <common>",
            `#include <common>${HOVER_VERTEX_PARS}${isTube ? MARK_VERTEX_PARS : ""}`,
          )
          .replace(
            "#include <project_vertex>",
            `${HOVER_VERTEX_PROJECT}${isTube ? MARK_VERTEX_MAIN : ""}`,
          );
        if (isTube) {
          shader.fragmentShader = shader.fragmentShader
            .replace("#include <common>", `#include <common>${MARK_FRAGMENT_PARS}`)
            .replace("#include <color_fragment>", MARK_FRAGMENT_COLOR);
        }
      };
      // Vessels and surfaces compile to different shaders, so they must not share a cached one.
      material.customProgramCacheKey = () => (isTube ? "vessel" : "surface");
      visual = {
        meshes: [],
        material,
        baseColor: color,
        sizeClass,
        lifted,
        vertexPlaces: null,
        hoverGrow,
        hoverCenter,
        targetGrow: 0,
        hoverRise: 0,
      };
      this.visuals.set(structure.id, visual);
    }
    return visual;
  }

  /**
   * Redraw the paint on the vessels these stretches touch.
   *
   * Each vertex of a vessel knows which piece of the centre line it surrounds
   * and how far along; a vertex inside a painted stretch gets that paint's color.
   */
  private applyPaint(touched: readonly Stretch[]): void {
    const structureIds = new Set(
      touched.map((stretch) => centerlines.structureOf(stretch.pieceId)),
    );
    for (const structureId of structureIds) {
      const visual = structureId && this.visuals.get(structureId);
      if (!visual) continue;
      const pieces = centerlines.pieces(structureId);
      // For each piece of this vessel, the painted ranges on it, in paint order.
      const ranges = pieces.map((piece) =>
        [...this.paints.values()].flatMap((paint) =>
          paint.stretches
            .filter((stretch) => stretch.pieceId === piece.id)
            .map((stretch) => ({ ...stretch, color: paint.color })),
        ),
      );
      visual.vertexPlaces ??= visual.meshes.map((mesh) =>
        vertexPlaces(structureId, mesh),
      );
      visual.meshes.forEach((mesh, meshIndex) => {
        const marks = mesh.geometry.getAttribute("aMark") as THREE.BufferAttribute;
        const { pieceIndex, along } = visual.vertexPlaces![meshIndex];
        const values = marks.array as Float32Array;
        values.fill(0);
        for (let vertex = 0; vertex < marks.count; vertex++) {
          for (const range of ranges[pieceIndex[vertex]]) {
            if (along[vertex] < range.from || along[vertex] > range.to) continue;
            values[vertex * 4] = range.color.r;
            values[vertex * 4 + 1] = range.color.g;
            values[vertex * 4 + 2] = range.color.b;
            values[vertex * 4 + 3] = 1;
          }
        }
        marks.needsUpdate = true;
      });
    }
  }

  /** Recompute every structure's color and target size from the selection and hover state. */
  private readonly refreshVisuals = () => {
    const selected = new Set(this.selection.getState().selected);
    for (const [structureId, visual] of this.visuals) {
      const { material } = visual;
      if (selected.has(structureId)) {
        material.color.copy(visual.baseColor).lerp(SELECTED_TINT, 0.85);
        material.emissive.copy(SELECTED_EMISSIVE);
      } else if (this.highlighted.has(structureId)) {
        material.color.copy(visual.baseColor).lerp(HIGHLIGHT_TINT, 0.7);
        material.emissive.copy(HIGHLIGHT_EMISSIVE);
      } else {
        material.color.copy(visual.baseColor);
        material.emissive.setScalar(0);
      }
      // The hovered structure keeps its color and grows a little instead.
      visual.targetGrow = structureId === this.hoveredId ? 1 : 0;
    }
    if (this.hoveredId) selected.add(this.hoveredId);
    this.highlighted.forEach((id) => selected.add(id));
    this.labels.setEmphasized(selected);
  };

  /** Show or hide each structure's meshes to match the visibility store. */
  private readonly applyVisibility = () => {
    const { hidden } = this.visibility.getState();
    for (const [structureId, visual] of this.visuals) {
      const visible = !hidden.has(structureId);
      visual.meshes.forEach((mesh) => {
        mesh.visible = visible;
      });
      if (!visible && this.hoveredId === structureId) this.setHovered(null);
    }
    this.labels.invalidate();
  };

  /** The nearest visible mesh along the raycaster's current ray and where the ray meets it, or null. */
  private firstHit(): Hit | null {
    const visible = [...this.visuals.values()].flatMap((visual) =>
      visual.meshes.filter((mesh) => mesh.visible),
    );
    const hit = this.raycaster.intersectObjects(visible, false)[0];
    return hit
      ? { structureId: hit.object.userData.structureId as string, point: hit.point }
      : null;
  }

  /** The structure the camera sees when looking at a world point: the point's own structure unless something covers it. */
  private readonly structureToward = (point: THREE.Vector3): string | null => {
    const direction = point.clone().sub(this.camera.position);
    const distance = direction.length();
    this.raycaster.set(this.camera.position, direction.normalize());
    // Nothing beyond the point matters; the margin absorbs rounding.
    this.raycaster.far = distance + 0.01;
    return this.firstHit()?.structureId ?? null;
  };

  /** Ease each structure toward its target size, so it grows and shrinks smoothly. */
  private stepHoverGrow(deltaSeconds: number): void {
    const step = deltaSeconds / HOVER_SECONDS;
    let rise = 0;
    for (const visual of this.visuals.values()) {
      const { hoverGrow, targetGrow } = visual;
      if (hoverGrow.value !== targetGrow) {
        hoverGrow.value =
          targetGrow > hoverGrow.value
            ? Math.min(targetGrow, hoverGrow.value + step)
            : Math.max(targetGrow, hoverGrow.value - step);
      }
      rise = Math.max(rise, hoverGrow.value * visual.hoverRise);
    }
    this.surfaceLift.value = rise * SURFACE_LIFT_MARGIN;
  }

  /** Advance the camera glide, if one is running. */
  private stepCameraMove(deltaSeconds: number): void {
    const move = this.cameraMove;
    if (!move) return;
    move.elapsed += deltaSeconds;
    const progress = Math.min(move.elapsed / CAMERA_MOVE_SECONDS, 1);
    // Ease in and out.
    const eased = progress * progress * (3 - 2 * progress);
    const { fromOrbit, toOrbit } = move;
    // Turn the short way round.
    const turn =
      THREE.MathUtils.euclideanModulo(
        toOrbit.theta - fromOrbit.theta + Math.PI,
        2 * Math.PI,
      ) - Math.PI;
    const orbit = new THREE.Spherical(
      THREE.MathUtils.lerp(fromOrbit.radius, toOrbit.radius, eased),
      THREE.MathUtils.lerp(fromOrbit.phi, toOrbit.phi, eased),
      fromOrbit.theta + turn * eased,
    );
    this.controls.target.lerpVectors(move.fromTarget, move.toTarget, eased);
    this.camera.position
      .setFromSpherical(orbit)
      .add(this.controls.target);
    if (progress === 1) this.endCameraMove();
  }

  private readonly endCameraMove = () => {
    this.cameraMove = null;
    this.controls.enableDamping = true;
  };

  private setHovered(structureId: string | null): void {
    if (structureId === this.hoveredId) return;
    this.hoveredId = structureId;
    this.renderer.domElement.style.cursor = structureId ? "pointer" : "";
    this.refreshVisuals();
    if (structureId === null) this.onHover?.(null);
  }

  private readonly onPointerDown = (event: PointerEvent) => {
    this.pressStart =
      event.button === 0 ? { x: event.clientX, y: event.clientY } : null;
  };

  private readonly onPointerMove = (event: PointerEvent) => {
    if (event.buttons !== 0) {
      // Dragging the camera: no hover feedback until the button is released.
      this.pendingHover = null;
      this.setHovered(null);
      return;
    }
    this.pendingHover = { clientX: event.clientX, clientY: event.clientY };
  };

  private readonly onPointerUp = (event: PointerEvent) => {
    const start = this.pressStart;
    this.pressStart = null;
    if (!start || event.button !== 0) return;
    if (
      Math.hypot(event.clientX - start.x, event.clientY - start.y) >
      CLICK_SLOP_PX
    )
      return;
    const hit = this.hitAt(event.clientX, event.clientY);
    const place = hit ? this.placeOf(hit) : undefined;
    if (hit && place && this.onPlaceClick?.(hit.structureId, place)) return;
    // Shift, Cmd or Ctrl adds to the selection, as in most apps.
    this.selection.click(hit?.structureId ?? null, event.shiftKey || event.metaKey || event.ctrlKey, place);
  };

  private readonly onPointerLeave = () => {
    this.pendingHover = null;
    this.setHovered(null);
  };

  private readonly tick = (time: number) => {
    // Capped so a background tab coming back doesn't skip the whole animation.
    const deltaSeconds = Math.min((time - this.lastFrameTime) / 1000, 0.1);
    this.lastFrameTime = time;
    this.stepHoverGrow(deltaSeconds);
    this.stepCameraMove(deltaSeconds);

    // Hover tests run at most once per frame, however fast the mouse moves.
    if (this.pendingHover) {
      const { clientX, clientY } = this.pendingHover;
      this.pendingHover = null;
      const structureId = this.pick(clientX, clientY);
      this.setHovered(structureId);
      if (structureId) this.onHover?.({ structureId, clientX, clientY });
    }
    this.controls.update();
    this.onFrame?.(deltaSeconds);
    this.renderer.render(this.scene, this.camera);
    // After rendering, so the labels use this frame's camera position.
    this.labels.update(deltaSeconds);
  };

  private readonly resize = () => {
    const { clientWidth: width, clientHeight: height } = this.container;
    if (width === 0 || height === 0) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
    this.labels.invalidate();
  };
}

/** For every vertex of a vessel's mesh, the piece of its centre line it surrounds and how far along. */
function vertexPlaces(structureId: string, mesh: THREE.Mesh): VertexPlaces {
  // Vertex positions are in the model's own frame, the same as the centre lines.
  const positions = mesh.geometry.attributes.position;
  const pieceIndex = new Uint16Array(positions.count);
  const along = new Float32Array(positions.count);
  for (let vertex = 0; vertex < positions.count; vertex++) {
    const point: Point = [
      positions.getX(vertex),
      positions.getY(vertex),
      positions.getZ(vertex),
    ];
    const nearest = centerlines.nearest(structureId, point);
    if (!nearest) continue;
    pieceIndex[vertex] = nearest.pieceIndex;
    along[vertex] = nearest.along;
  }
  return { pieceIndex, along };
}

/** An even sample of a structure's vertices, in world space. */
function surfaceSample(meshes: readonly THREE.Mesh[]): THREE.Vector3[] {
  const total = meshes.reduce(
    (count, mesh) => count + mesh.geometry.attributes.position.count,
    0,
  );
  const stride = Math.max(1, Math.ceil(total / LABEL_ANCHOR_SAMPLES));
  const points: THREE.Vector3[] = [];
  for (const mesh of meshes) {
    const positions = mesh.geometry.attributes.position;
    for (let index = 0; index < positions.count; index += stride) {
      points.push(
        new THREE.Vector3()
          .fromBufferAttribute(positions, index)
          .applyMatrix4(mesh.matrixWorld),
      );
    }
  }
  return points;
}
