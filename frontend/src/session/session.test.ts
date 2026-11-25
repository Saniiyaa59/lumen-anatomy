import { describe, expect, it } from "vitest";
import sample from "../../../assets/fixtures/sessions/coronary_arteries.json";
import { Centerlines, centerlines, type CenterlinesFile, type Piece, type Point } from "../centerlines.ts";
import type { ClickPlace } from "../selection/store.ts";
import { parseSession, type ClickCase, type MultipleChoice } from "./format.ts";
import { grade, inTarget } from "./grade.ts";
import { caseIsOpen, currentPart, followUpRequest, namesHidden, outOfPicks, PlayerStore, questionIsOpen, quizIsOpen, quizResults } from "./player.ts";
import { pulseRoute, pulseStretches } from "./pulse.ts";

const session = parseSession(sample);
const theCase = session.parts.find((part): part is ClickCase => part.kind === "click_case")!;
const theQuestion = session.parts.find((part): part is MultipleChoice => part.kind === "multiple_choice")!;
const LAD = "anterior_interventricular_artery";

/** A click on a vessel, in the shape the viewer produces. */
function clickOn(structureId: string, pieceId: string, along: number): ClickPlace {
  return { point: [0, 0, 0], vessel: { structureId, pieceId, along, fromStart: along, offset: 0.001 } };
}

describe("grading a click", () => {
  const on = (structureId: string, piece: string | null, at: number | null) => grade(theCase, { structureId, piece, at });

  it("accepts a click on the answer", () => {
    const result = on(LAD, `${LAD}.0`, 0.02);
    expect(result.correct).toBe(true);
    expect(result.statement).toBe(theCase.feedback.correct);
  });

  it("allows the tolerance past the end of the answer, and no more", () => {
    expect(on(LAD, `${LAD}.0`, 0.0465 + 0.0015).correct).toBe(true);
    expect(on(LAD, `${LAD}.0`, 0.0465 + 0.0025).correct).toBe(false);
  });

  it("explains a click too far up, on the left coronary artery", () => {
    const result = on("left_coronary_artery", "left_coronary_artery.0", 0.01);
    expect(result.correct).toBe(false);
    expect(result.nearMiss).toBe(0);
    expect(result.statement.text).toContain("Too far up");
  });

  it("explains a click on the right artery but past the first septal branch", () => {
    const result = on(LAD, `${LAD}.0`, 0.08);
    expect(result.nearMiss).toBe(1);
    expect(result.statement.text).toContain("too far along");
  });

  it("explains a click anywhere on a near-miss structure", () => {
    expect(on("circumflex_artery_of_heart", "circumflex_artery_of_heart.3", 0.01).nearMiss).toBe(2);
  });

  it("gives the general feedback for anything else, vessel or not", () => {
    expect(on("right_coronary_artery", "right_coronary_artery.0", 0.05)).toEqual({ correct: false, statement: theCase.feedback.wrong, nearMiss: null });
    expect(on("left_ventricle", null, null).statement).toBe(theCase.feedback.wrong);
  });

  it("does not match a branch of the right artery that is a different piece", () => {
    expect(on(LAD, `${LAD}.5`, 0.01).correct).toBe(false);
  });

  it("matches a whole-structure target wherever the click lands on it", () => {
    const target = { regions: [], structures: ["left_ventricle"] };
    expect(inTarget(target, { structureId: "left_ventricle", piece: null, at: null })).toBe(true);
    expect(inTarget(target, { structureId: "right_ventricle", piece: null, at: null })).toBe(false);
  });
});

describe("a pulse's route", () => {
  function piece(id: string, points: Point[], attach: Piece["attach"] = null): Piece {
    let length = 0;
    for (let i = 1; i < points.length; i++) length += Math.hypot(...points[i].map((value, k) => value - points[i - 1][k]));
    return { id, length, attach, radius: points.map(() => 0.001), points };
  }
  // A trunk along x from 0 to 0.1, a branch leaving it at 0.04, and a twig leaving that branch at 0.01.
  const tree = new Centerlines({
    region: "test",
    source: "test",
    units: "metres",
    structures: {
      trunk: [piece("trunk.0", [[0, 0, 0], [0.1, 0, 0]])],
      branch: [
        piece("branch.0", [[0.04, 0, 0], [0.04, 0.03, 0]], { piece: "trunk.0", at: 0.04, gap: 0 }),
        piece("branch.1", [[0.04, 0.01, 0], [0.04, 0.01, 0.02]], { piece: "branch.0", at: 0.01, gap: 0 }),
      ],
    },
  } satisfies CenterlinesFile);

  it("with no end, reaches each branch when the pulse passes where it leaves", () => {
    const route = pulseRoute(tree, { piece: "trunk.0", at: 0.01 }, null);
    const startsAt = Object.fromEntries(route.segments.map((segment) => [segment.pieceId, segment.startsAt]));
    expect(startsAt["trunk.0"]).toBe(0);
    expect(startsAt["branch.0"]).toBeCloseTo(0.03);
    expect(startsAt["branch.1"]).toBeCloseTo(0.04);
    expect(route.length).toBeCloseTo(0.09);
  });

  it("with an end, follows the single path there", () => {
    const route = pulseRoute(tree, { piece: "trunk.0", at: 0.01 }, { piece: "branch.1", at: 0.015 });
    expect(route.segments.map((segment) => [segment.pieceId, segment.from, segment.to])).toEqual([
      ["trunk.0", 0.01, 0.04],
      ["branch.0", 0, 0.01],
      ["branch.1", 0, 0.015],
    ]);
    expect(route.length).toBeCloseTo(0.055);
  });

  it("is empty when the end is not beyond the start", () => {
    expect(pulseRoute(tree, { piece: "branch.0", at: 0 }, { piece: "trunk.0", at: 0.09 }).segments).toEqual([]);
  });

  it("lights the window behind the front, on every branch it has reached", () => {
    const route = pulseRoute(tree, { piece: "trunk.0", at: 0 }, null);
    const lit = pulseStretches(route, 0.05, 0.02);
    const byPiece = Object.fromEntries(lit.map((stretch) => [stretch.pieceId, [stretch.from, stretch.to]]));
    expect(byPiece["trunk.0"][0]).toBeCloseTo(0.03);
    expect(byPiece["trunk.0"][1]).toBeCloseTo(0.05);
    // The branch left the trunk at 0.04, so the front is 0.01 along it.
    expect(byPiece["branch.0"][0]).toBe(0);
    expect(byPiece["branch.0"][1]).toBeCloseTo(0.01);
    expect(byPiece["branch.1"]).toBeUndefined();
  });

  it("lights nothing before the start or after the far end has passed", () => {
    const route = pulseRoute(tree, { piece: "trunk.0", at: 0 }, null);
    expect(pulseStretches(route, 0, 0.02)).toEqual([]);
    expect(pulseStretches(route, route.length + 0.021, 0.02)).toEqual([]);
  });

  it("runs the sample's pulse from the left coronary artery into both of its branches", () => {
    const pulse = session.parts.find((part) => part.kind === "pulse")!;
    const route = pulseRoute(centerlines, pulse.from, pulse.to);
    const vessels = new Set(route.segments.map((segment) => centerlines.structureOf(segment.pieceId)));
    expect(vessels).toContain(LAD);
    expect(vessels).toContain("circumflex_artery_of_heart");
    // Both branches start when the pulse reaches the end of the left coronary artery.
    const lca = centerlines.piece("left_coronary_artery.0")!.length;
    expect(route.segments.find((segment) => segment.pieceId === `${LAD}.0`)!.startsAt).toBeCloseTo(lca, 3);
  });
});

describe("PlayerStore", () => {
  /** A store whose clock ticks 1, 2, 3… so times are predictable. */
  function play() {
    let time = 0;
    const store = new PlayerStore(() => ++time);
    store.start(session);
    return store;
  }
  const caseIndex = session.parts.indexOf(theCase);
  const sliderIndex = session.parts.findIndex((part) => part.kind === "damage_slider");

  it("starts at the first part and steps through to the summary", () => {
    const store = play();
    expect(currentPart(store.getState())?.id).toBe("origins");
    for (let i = 0; i < session.parts.length; i++) store.next();
    expect(store.getState().index).toBe(session.parts.length);
    expect(currentPart(store.getState())).toBeNull();
    store.next();
    expect(store.getState().index).toBe(session.parts.length);
  });

  it("does not step back past the first part", () => {
    const store = play();
    store.back();
    expect(store.getState().index).toBe(0);
  });

  it("keeps the damage point inside the slider's track", () => {
    const store = play();
    expect(store.damageAt()).toBeNull();
    store.goTo(sliderIndex);
    expect(store.damageAt()).toBe(0.08);
    store.setDamage(0.03);
    expect(store.damageAt()).toBe(0.03);
    store.setDamage(5);
    expect(store.damageAt()).toBe(0.1145);
    store.setDamage(-1);
    expect(store.damageAt()).toBe(0);
  });

  it("remembers the damage point when the student comes back to the slider", () => {
    const store = play();
    store.goTo(sliderIndex);
    store.setDamage(0.03);
    store.next();
    store.back();
    expect(store.damageAt()).toBe(0.03);
  });

  it("ignores clicks unless a case is waiting for one", () => {
    const store = play();
    expect(store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.02))).toBe(false);
    expect(store.getState().answers).toEqual([]);
  });

  it("records a wrong click, then a right one, in the shape sent to the backend", () => {
    const store = play();
    store.goTo(caseIndex);
    expect(caseIsOpen(store.getState())).toBe(true);

    expect(store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.08))).toBe(true);
    let outcome = store.getState().outcomes[theCase.id];
    expect(outcome).toMatchObject({ attempts: 1, correct: false, revealed: false });
    expect(outcome.statement?.text).toContain("too far along");
    expect(caseIsOpen(store.getState())).toBe(true);

    store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.02));
    outcome = store.getState().outcomes[theCase.id];
    expect(outcome).toMatchObject({ attempts: 2, correct: true });
    expect(caseIsOpen(store.getState())).toBe(false);

    expect(store.getState().answers).toEqual([
      { part_id: theCase.id, attempt: 1, structure_id: LAD, point: [0, 0, 0], piece: `${LAD}.0`, at: 0.08, correct: false, seconds: 1 },
      { part_id: theCase.id, attempt: 2, structure_id: LAD, point: [0, 0, 0], piece: `${LAD}.0`, at: 0.02, correct: true, seconds: 2 },
    ]);
  });

  it("stops taking clicks once the case is answered", () => {
    const store = play();
    store.goTo(caseIndex);
    store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.02));
    expect(store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.09))).toBe(false);
    expect(store.getState().answers).toHaveLength(1);
  });

  it("records a click that is not on a vessel", () => {
    const store = play();
    store.goTo(caseIndex);
    store.answer("left_ventricle", { point: [0.01, 1.28, 0.05], vessel: null });
    expect(store.getState().answers[0]).toMatchObject({ structure_id: "left_ventricle", piece: null, at: null, correct: false });
  });

  it("shows the answer on request, without counting it as correct", () => {
    const store = play();
    store.goTo(caseIndex);
    store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.08));
    store.reveal();
    expect(store.getState().outcomes[theCase.id]).toMatchObject({ attempts: 1, correct: false, revealed: true, statement: theCase.feedback.correct });
    expect(caseIsOpen(store.getState())).toBe(false);
    expect(store.getState().answers).toHaveLength(1);
  });

  it("clears everything when the session is closed", () => {
    const store = play();
    store.goTo(caseIndex);
    store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.02));
    store.close();
    expect(store.getState()).toMatchObject({ session: null, index: 0, answers: [], outcomes: {} });
  });

  it("remembers the furthest part reached when the student steps back", () => {
    const store = play();
    store.next();
    store.next();
    store.back();
    expect(store.getState()).toMatchObject({ index: 1, reached: 2 });
  });

  it("gives each play-through its own id and can reopen one as it was left", () => {
    const first = play();
    first.goTo(caseIndex);
    first.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.02));
    const saved = first.getState();
    expect(saved.runId).toContain(session.session_id);

    const later = new PlayerStore();
    later.restore(saved);
    expect(later.getState()).toBe(saved);
    expect(currentPart(later.getState())?.id).toBe(theCase.id);
    expect(caseIsOpen(later.getState())).toBe(false);
  });

  const questionIndex = session.parts.indexOf(theQuestion);

  it("records a wrong pick, then the right one, in the shape sent to the backend", () => {
    const store = play();
    store.goTo(questionIndex);
    expect(questionIsOpen(store.getState()) && quizIsOpen(store.getState())).toBe(true);

    expect(store.pick(1)).toBe(true);
    expect(store.getState().outcomes[theQuestion.id]).toMatchObject({ attempts: 1, correct: false, picks: [1], statement: theQuestion.options[1].feedback });
    expect(store.pick(1)).toBe(false); // already picked
    expect(store.pick(9)).toBe(false); // no such option

    expect(store.pick(0)).toBe(true);
    expect(store.getState().outcomes[theQuestion.id]).toMatchObject({ attempts: 2, correct: true, picks: [1, 0] });
    expect(questionIsOpen(store.getState())).toBe(false);
    expect(store.pick(2)).toBe(false); // answered: no more picks
    expect(store.getState().answers).toEqual([
      { part_id: theQuestion.id, attempt: 1, choice: 1, correct: false, seconds: 1 },
      { part_id: theQuestion.id, attempt: 2, choice: 0, correct: true, seconds: 2 },
    ]);
  });

  it("shows a question's answer on request, with the right option's feedback", () => {
    const store = play();
    store.goTo(questionIndex);
    store.pick(2);
    store.reveal();
    expect(store.getState().outcomes[theQuestion.id]).toMatchObject({ correct: false, revealed: true, picks: [2], statement: theQuestion.options[0].feedback });
    expect(quizIsOpen(store.getState())).toBe(false);
  });

  it("ignores picks unless a question is on screen, and clicks while one is", () => {
    const store = play();
    expect(store.pick(0)).toBe(false);
    store.goTo(questionIndex);
    expect(store.answer(LAD, clickOn(LAD, `${LAD}.0`, 0.02))).toBe(false);
  });

  it("hides names while a case is open or a question asks about what is highlighted, and not after", () => {
    const store = play();
    expect(namesHidden(store.getState())).toBe(false);
    store.goTo(caseIndex);
    expect(namesHidden(store.getState())).toBe(true);
    store.goTo(questionIndex);
    expect(namesHidden(store.getState())).toBe(true);
    store.pick(0);
    expect(namesHidden(store.getState())).toBe(false);

    const plain = new PlayerStore(() => 0);
    const words = { ...theQuestion, id: "plain", highlight: [] };
    plain.start({ ...session, parts: [words], plan: [{ part_id: "plain", title: words.title, kind: "multiple_choice" }] });
    expect(questionIsOpen(plain.getState()) && !namesHidden(plain.getState())).toBe(true);
  });

  it("shows a question's answer after two wrong picks, so the options can't all be guessed through", () => {
    const store = play();
    store.goTo(questionIndex);
    store.pick(1);
    expect(questionIsOpen(store.getState())).toBe(true);
    store.pick(2);
    expect(store.getState().outcomes[theQuestion.id]).toMatchObject({ correct: false, revealed: true, picks: [1, 2], statement: theQuestion.options[0].feedback });
    expect(quizIsOpen(store.getState())).toBe(false);
    expect(store.pick(0)).toBe(false);
    expect(store.getState().answers.map((answer) => answer.correct)).toEqual([false, false]);
  });

  it("shows the answer as soon as a wrong pick leaves only one option", () => {
    expect([outOfPicks(1, 4), outOfPicks(2, 4), outOfPicks(1, 2), outOfPicks(1, 3)]).toEqual([false, true, true, false]);
  });
});

describe("the summary's results", () => {
  const caseIndex = session.parts.indexOf(theCase);
  const questionIndex = session.parts.indexOf(theQuestion);

  it("lists each case and question in order, with how it went", () => {
    const right = { attempts: 1, correct: true, revealed: false, statement: null, lastClick: null };
    expect(quizResults(session, {}).map((quiz) => [quiz.part.id, quiz.index, quiz.result])).toEqual([
      [theCase.id, caseIndex, "skipped"],
      [theQuestion.id, questionIndex, "skipped"],
    ]);
    const results = quizResults(session, { [theCase.id]: right, [theQuestion.id]: { ...right, attempts: 2, picks: [1, 0] } });
    expect(results.map((quiz) => quiz.result)).toEqual(["first", "later"]);
    const shown = quizResults(session, { [theQuestion.id]: { ...right, correct: false, revealed: true } });
    expect(shown[1].result).toBe("shown");
  });

  it("asks a follow-up on the shaky topics, or on what was missed when there are none", () => {
    expect(followUpRequest(session, {})).toBe("Go over these again with me: Placing a blockage from what it cuts off");
    const noShaky = { ...session, summary: { ...session.summary!, shaky: [] } };
    const right = { attempts: 1, correct: true, revealed: false, statement: null, lastClick: null };
    expect(followUpRequest(noShaky, { [theCase.id]: right })).toBe(`Go over these again with me: ${theQuestion.title}`);
    expect(followUpRequest(noShaky, { [theCase.id]: right, [theQuestion.id]: right })).toBeNull();
  });
});
