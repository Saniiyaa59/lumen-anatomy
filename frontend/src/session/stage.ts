import { centerlines, type Stretch } from "../centerlines.ts";
import { CORRECT_COLOR, DAMAGE_COLOR, LOST_COLOR, PULSE_COLOR, WRONG_COLOR } from "../viewer/colors.ts";
import type { SceneController } from "../viewer/controller.ts";
import type { VisibilityStore } from "../visibility/store.ts";
import { getStructure, structuresUnder } from "../registry.ts";
import type { Region } from "./format.ts";
import { currentPart, type PlayerStore } from "./player.ts";
import { pulseRoute, pulseStretches, type PulseRoute } from "./pulse.ts";

/** Paint layers the stage owns. */
const LAYERS = { lost: "session:lost", pulse: "session:pulse", answer: "session:answer", miss: "session:miss", damage: "session:damage" } as const;

/** Half the length of the mark drawn at a damage point or a wrong click, in metres. */
const DAMAGE_HALF = 0.0012;
const MISS_HALF = 0.003;

/** A pulse crosses its whole route in about this long, then pauses and starts again. */
const PULSE_SECONDS = 3.2;
const PULSE_PAUSE_SECONDS = 0.7;
/** The lit part of a pulse, as a share of its route, and its shortest length in metres. */
const PULSE_TAIL_SHARE = 0.16;
const PULSE_TAIL_MIN = 0.008;

const asStretch = (region: Region): Stretch => ({ pieceId: region.piece, from: region.from, to: region.to });

/** The structures a part's `hide` list covers: each id is a structure, or a group standing for everything in it. */
const hiddenBy = (ids: readonly string[]): string[] => ids.flatMap((id) => (getStructure(id) ? [id] : structuresUnder(id).map((structure) => structure.id)));

/**
 * Shows the current part of a session on the 3D model.
 *
 * It follows the player: when the part changes it moves the camera, hides and
 * highlights what the part asks for and starts any animation; as the student
 * drags the slider or answers a case it repaints the vessels. It also takes the
 * clicks a part needs, so they don't change the selection.
 *
 * Hiding goes through the same store as the structures panel, so the panel's
 * eyes always show what is hidden and the student can bring something back.
 * When the session reaches its summary or is closed, the heart is reset:
 * everything shown, nothing painted, the camera back where it started.
 */
export class Stage {
  private readonly controller: SceneController;
  private readonly player: PlayerStore;
  private readonly visibility: VisibilityStore;
  private readonly unsubscribe: () => void;
  /** The part currently staged, to tell a new part from a change within one. */
  private stagedPart: string | null = null;
  private pulse: { route: PulseRoute; head: number; tail: number; pause: number } | null = null;

  constructor(controller: SceneController, player: PlayerStore, visibility: VisibilityStore) {
    this.controller = controller;
    this.player = player;
    this.visibility = visibility;
    this.unsubscribe = player.subscribe(this.sync);
    controller.onPlaceClick = this.onPlaceClick;
    controller.onFrame = this.onFrame;
    // A session may already be playing when the model finishes loading.
    void controller.ready.then(this.sync, () => undefined);
  }

  dispose(): void {
    this.unsubscribe();
    this.controller.onPlaceClick = null;
    this.controller.onFrame = null;
    this.clearMarks();
  }

  /** Aim the camera again at what the part on screen is showing. Does nothing outside a part. */
  reframe(): void {
    const part = currentPart(this.player.getState());
    if (part) this.controller.frame(part.view.look_at, part.view.side);
  }

  /** Bring the model in line with the player's state. */
  private readonly sync = () => {
    const state = this.player.getState();
    const part = currentPart(state);
    const key = part ? `${state.session!.session_id}/${part.id}` : null;
    if (key !== this.stagedPart) {
      this.stagedPart = key;
      this.clearMarks();
      if (!part) {
        // The summary, or the session was closed: put the heart back as it starts.
        this.visibility.showAll();
        this.controller.resetView();
      } else {
        // Hide first: what is hidden decides which side the structures can be seen from.
        this.visibility.setHidden(hiddenBy(part.hide));
        this.controller.setHighlighted(part.kind === "demonstration" ? part.highlight : []);
        this.controller.frame(part.view.look_at, part.view.side);
        if (part.kind === "pulse") {
          const route = pulseRoute(centerlines, part.from, part.to);
          this.pulse = { route, head: 0, tail: Math.max(PULSE_TAIL_MIN, route.length * PULSE_TAIL_SHARE), pause: 0 };
        }
      }
    }
    if (part?.kind === "damage_slider") {
      const at = this.player.damageAt() ?? part.start_at;
      this.controller.paint(centerlines.beyond(part.track.piece, at), LOST_COLOR, LAYERS.lost);
      this.controller.paint([centerlines.stretch(part.track.piece, at - DAMAGE_HALF, at + DAMAGE_HALF)], DAMAGE_COLOR, LAYERS.damage);
    }
    if (part?.kind === "click_case") {
      const outcome = state.outcomes[part.id];
      const shown = outcome?.correct || outcome?.revealed;
      this.controller.paint(shown ? part.answer.regions.map(asStretch) : [], CORRECT_COLOR, LAYERS.answer);
      this.controller.setHighlighted(shown ? part.answer.structures : []);
      const miss = !shown && outcome?.lastClick?.piece != null && outcome.lastClick.at != null ? outcome.lastClick : null;
      this.controller.paint(
        miss ? [centerlines.stretch(miss.piece!, miss.at! - MISS_HALF, miss.at! + MISS_HALF)] : [],
        WRONG_COLOR,
        LAYERS.miss,
      );
    }
  };

  /** Remove the paint, tint and animation of the part that was showing. */
  private clearMarks(): void {
    this.pulse = null;
    Object.values(LAYERS).forEach((layer) => this.controller.clearPaint(layer));
    this.controller.setHighlighted([]);
  }

  /** Clicks a part needs: an answer to a case, or a new place for the damage point. */
  private readonly onPlaceClick: NonNullable<SceneController["onPlaceClick"]> = (structureId, place) => {
    const part = currentPart(this.player.getState());
    if (part?.kind === "click_case") return this.player.answer(structureId, place);
    if (part?.kind === "damage_slider" && place.vessel?.pieceId === part.track.piece) {
      this.player.setDamage(place.vessel.along);
      return true;
    }
    return false;
  };

  /** Move the pulse along its route. */
  private readonly onFrame = (deltaSeconds: number) => {
    const pulse = this.pulse;
    if (!pulse || pulse.route.length === 0) return;
    if (pulse.pause > 0) {
      pulse.pause -= deltaSeconds;
      if (pulse.pause <= 0) pulse.head = 0;
      return;
    }
    pulse.head += (pulse.route.length / PULSE_SECONDS) * deltaSeconds;
    this.controller.paint(pulseStretches(pulse.route, pulse.head, pulse.tail), PULSE_COLOR, LAYERS.pulse);
    if (pulse.head > pulse.route.length + pulse.tail) pulse.pause = PULSE_PAUSE_SECONDS;
  };
}
