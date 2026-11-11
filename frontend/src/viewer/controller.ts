import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { acceleratedRaycast, MeshBVH } from "three-mesh-bvh";
import heartUrl from "../../../assets/models/heart.glb?url";
import {
  structureIdForMesh,
  structures,
  type Layer,
  type Structure,
} from "../registry.ts";
import type { SelectionStore } from "../selection/store.ts";
import type { VisibilityStore } from "../visibility/store.ts";
import { baseColor, SELECTED_COLOR } from "./colors.ts";
import { LabelLayer } from "./labels.ts";

/** The model is scaled so its longest side is this many world units. */
const MODEL_SIZE = 2;
/** A press that moves less than this many pixels is a click, not a camera drag. */
const CLICK_SLOP_PX = 4;
/** At most this many vertices per structure are considered as label anchor points. */
const LABEL_ANCHOR_SAMPLES = 1500;

/**
 * How a hovered structure gets bigger, by the registry's `size_class`.
 * `scale` grows it around its middle, as a fraction of its size. `swell` also
 * pushes its surface outward, in world units, which is what makes thin vessels
 * look thicker.
 */
const HOVER_GROWTH: Record<
  Structure["size_class"],
  { scale: number; swell: number }
> = {
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

const SELECTED_TINT = new THREE.Color(SELECTED_COLOR);
const SELECTED_EMISSIVE = new THREE.Color(SELECTED_COLOR).multiplyScalar(0.3);

interface StructureVisual {
  meshes: THREE.Mesh[];
  /** Shared by all of the structure's meshes, so the structure lights up as one. */
  material: THREE.MeshStandardMaterial;
  baseColor: THREE.Color;
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

export interface VisibilityTarget {
  structureIds?: readonly string[];
  layers?: readonly Layer[];
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
  /** Shader input shared by the coronary vessels' materials; see HOVER_VERTEX_PARS. */
  private readonly surfaceLift = { value: 0 };
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
    this.ready = this.loadHeart();
  }

  /** IDs of the structures that have at least one mesh in the loaded model. */
  get structureIds(): string[] {
    return [...this.visuals.keys()];
  }

  /** The structure under a screen point, or null. Hidden structures can't be picked. */
  pick(clientX: number, clientY: number): string | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(pointer, this.camera);
    this.raycaster.far = Infinity;
    return this.firstHit();
  }

  /** Glide the camera back to where it started: the anterior view, centered, at the default zoom. */
  resetView(): void {
    const { target } = this.controls;
    this.cameraMove = {
      fromTarget: target.clone(),
      toTarget: HOME_TARGET,
      fromOrbit: new THREE.Spherical().setFromVector3(
        this.camera.position.clone().sub(target),
      ),
      toOrbit: new THREE.Spherical().setFromVector3(
        HOME_POSITION.clone().sub(HOME_TARGET),
      ),
      elapsed: 0,
    };
    // Leftover spin from the last drag would fight the glide.
    this.controls.enableDamping = false;
  }

  /** Show or hide the name labels around the heart. */
  setLabelsVisible(visible: boolean): void {
    this.labels.setVisible(visible);
  }

  /** Show or hide structures, by ID and/or by layer. The structure panel follows along. */
  setVisibility(
    { structureIds = [], layers = [] }: VisibilityTarget,
    visible: boolean,
  ): void {
    const ids = structures
      .filter(
        (structure) =>
          structureIds.includes(structure.id) ||
          layers.includes(structure.layer),
      )
      .map((structure) => structure.id);
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

  private async loadHeart(): Promise<void> {
    const gltf = await new GLTFLoader().loadAsync(heartUrl);
    if (this.disposed) return;
    const model = gltf.scene;

    const unmapped: string[] = [];
    model.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const structureId = structureIdForMesh(object.name);
      if (structureId === undefined) {
        unmapped.push(object.name);
        object.visible = false;
        return;
      }
      object.userData.structureId = structureId;
      // A search tree over the triangles. Without it every ray tests all ~300k
      // triangles, which is too slow for the label visibility checks.
      object.geometry.boundsTree = new MeshBVH(object.geometry);
      object.raycast = acceleratedRaycast;
      const exported = object.material as THREE.Material | THREE.Material[];
      (Array.isArray(exported) ? exported : [exported]).forEach((material) =>
        material.dispose(),
      );
      object.material = this.visualFor(structureId).material;
      this.visuals.get(structureId)!.meshes.push(object);
    });
    if (unmapped.length > 0) {
      console.warn(
        "heart.glb meshes missing from structures.json (hidden):",
        unmapped,
      );
    }
    const missing = structures
      .filter((structure) => !this.visuals.has(structure.id))
      .map((structure) => structure.id);
    if (missing.length > 0) {
      console.warn(
        "structures.json entries with no mesh in heart.glb:",
        missing,
      );
    }

    // Scale the whole model to MODEL_SIZE, and put the middle of the chambers at
    // the origin so the camera orbits the heart itself, not the vessels' extent.
    const size = new THREE.Box3()
      .setFromObject(model)
      .getSize(new THREE.Vector3());
    const scale = MODEL_SIZE / Math.max(size.x, size.y, size.z);
    const chambers = new THREE.Box3();
    for (const structure of structures) {
      if (structure.layer !== "chambers") continue;
      this.visuals
        .get(structure.id)
        ?.meshes.forEach((mesh) => chambers.expandByObject(mesh));
    }
    const center = (
      chambers.isEmpty() ? new THREE.Box3().setFromObject(model) : chambers
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
      if (structure.layer !== "coronary_vessels") {
        const extent = bounds.getSize(new THREE.Vector3());
        const growth = HOVER_GROWTH[structure.size_class];
        visual.hoverRise =
          (growth.scale * Math.max(extent.x, extent.y, extent.z)) / 2 +
          growth.swell;
      }
      this.labels.addStructure(structure.id, surfaceSample(visual.meshes));
    }

    this.scene.add(model);
    this.refreshVisuals();
    this.applyVisibility();
  }

  private visualFor(structureId: string): StructureVisual {
    let visual = this.visuals.get(structureId);
    if (!visual) {
      const structure = structures.find(
        (candidate) => candidate.id === structureId,
      )!;
      const color = new THREE.Color(baseColor(structure));
      const hoverGrow = { value: 0 };
      const hoverCenter = { value: new THREE.Vector3() };
      // Double-sided because valve leaflets are thin and seen from both sides.
      const material = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.55,
        side: THREE.DoubleSide,
      });
      const growth = HOVER_GROWTH[structure.size_class];
      const surfaceLift =
        structure.layer === "coronary_vessels"
          ? this.surfaceLift
          : { value: 0 };
      material.onBeforeCompile = (shader) => {
        shader.uniforms.uHoverGrow = hoverGrow;
        shader.uniforms.uHoverCenter = hoverCenter;
        shader.uniforms.uHoverScale = { value: growth.scale };
        shader.uniforms.uHoverSwell = { value: growth.swell };
        shader.uniforms.uSurfaceLift = surfaceLift;
        shader.vertexShader = shader.vertexShader
          .replace("#include <common>", `#include <common>${HOVER_VERTEX_PARS}`)
          .replace("#include <project_vertex>", HOVER_VERTEX_PROJECT);
      };
      visual = {
        meshes: [],
        material,
        baseColor: color,
        hoverGrow,
        hoverCenter,
        targetGrow: 0,
        hoverRise: 0,
      };
      this.visuals.set(structureId, visual);
    }
    return visual;
  }

  /** Recompute every structure's color and target size from the selection and hover state. */
  private readonly refreshVisuals = () => {
    const selected = new Set(this.selection.getState().selected);
    for (const [structureId, visual] of this.visuals) {
      const { material } = visual;
      if (selected.has(structureId)) {
        material.color.copy(visual.baseColor).lerp(SELECTED_TINT, 0.85);
        material.emissive.copy(SELECTED_EMISSIVE);
      } else {
        material.color.copy(visual.baseColor);
        material.emissive.setScalar(0);
      }
      // The hovered structure keeps its color and grows a little instead.
      visual.targetGrow = structureId === this.hoveredId ? 1 : 0;
    }
    if (this.hoveredId) selected.add(this.hoveredId);
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

  /** The structure of the nearest visible mesh along the raycaster's current ray, or null. */
  private firstHit(): string | null {
    const visible = [...this.visuals.values()].flatMap((visual) =>
      visual.meshes.filter((mesh) => mesh.visible),
    );
    const hit = this.raycaster.intersectObjects(visible, false)[0];
    return hit ? (hit.object.userData.structureId as string) : null;
  }

  /** The structure the camera sees when looking at a world point: the point's own structure unless something covers it. */
  private readonly structureToward = (point: THREE.Vector3): string | null => {
    const direction = point.clone().sub(this.camera.position);
    const distance = direction.length();
    this.raycaster.set(this.camera.position, direction.normalize());
    // Nothing beyond the point matters; the margin absorbs rounding.
    this.raycaster.far = distance + 0.01;
    return this.firstHit();
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
    this.selection.click(
      this.pick(event.clientX, event.clientY),
      event.shiftKey,
    );
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
