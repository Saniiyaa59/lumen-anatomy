import { describe, expect, it, vi } from "vitest";
import sample from "../../../assets/fixtures/sessions/coronary_arteries.json";
import type { ClickPlace } from "../selection/store.ts";
import { checkPart, checkSession, checkStart, checkSummary, parseSession } from "./format.ts";
import { LiveSessions, type SessionApi } from "./live.ts";
import { caseIsOpen, currentPart, nextNeeds, PlayerStore } from "./player.ts";

const recorded = parseSession(sample);
const LAD = "anterior_interventricular_artery";
const TOTAL = recorded.parts.length;

const { parts: _parts, summary: _summary, ...startFields } = sample;

function clickOn(pieceId: string, along: number): ClickPlace {
  return { point: [0, 0, 0], vessel: { structureId: LAD, pieceId, along, fromStart: along, offset: 0.001 } };
}

/** A backend that hands out the sample part by part, as the real stub does. */
function fakeBackend(overrides: Partial<SessionApi> = {}) {
  let sent = 0;
  const api = {
    startSession: vi.fn<SessionApi["startSession"]>(async (request) => ({ ...structuredClone(startFields), session_id: "s1", request })),
    nextPart: vi.fn<SessionApi["nextPart"]>(async () =>
      sent < TOTAL ? { part: structuredClone(sample.parts[sent++]), plan: sample.plan, done: false } : { part: null, plan: sample.plan, done: true },
    ),
    sendAnswer: vi.fn<SessionApi["sendAnswer"]>(async () => ({ plan: sample.plan })),
    finishSession: vi.fn<SessionApi["finishSession"]>(async () => structuredClone(sample.summary)),
  };
  if (overrides.startSession) api.startSession.mockImplementation(overrides.startSession);
  if (overrides.nextPart) api.nextPart.mockImplementation(overrides.nextPart);
  const player = new PlayerStore();
  return { api, player, live: new LiveSessions(player, api) };
}

/** Let promise callbacks that were just queued run. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("checks for a session that is still arriving", () => {
  it("accepts the backend's first reply, which has a plan but no parts", () => {
    expect(checkStart(startFields)).toEqual([]);
    expect(checkStart({ ...startFields, format: "lumen.session/9" })).toEqual(['session.format: must be "lumen.session/0.1"']);
    expect(checkStart(null)[0]).toContain("session.format");
  });

  it("checks one part against the loaded model", () => {
    expect(checkPart(sample.parts[0])).toEqual([]);
    expect(checkPart({ ...sample.parts[0], hide: ["spleen"] })).toEqual(['part.hide[0]: "spleen" is not a structure or a group in this region']);
  });

  it("checks a summary", () => {
    expect(checkSummary(sample.summary)).toEqual([]);
    expect(checkSummary({ solid: [], shaky: [] })).toEqual(["summary.sources: must be a list"]);
  });

  it("lets a partial session lack later parts and its summary, but a recorded one may not", () => {
    const arriving = { ...startFields, parts: sample.parts.slice(0, 2), summary: null };
    expect(checkSession(arriving, { partial: true })).toEqual([]);
    expect(checkSession(arriving).length).toBeGreaterThan(0);
  });
});

describe("LiveSessions", () => {
  it("starts a session, shows the plan and loads the first part", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me on coronary dominance", null);
    const state = player.getState();
    expect(api.startSession).toHaveBeenCalledWith("Prepare me on coronary dominance", null);
    expect(state).toMatchObject({ live: true, pending: false, error: null, index: 0 });
    expect(state.session?.request).toBe("Prepare me on coronary dominance");
    expect(state.session?.plan).toHaveLength(TOTAL);
    expect(state.session?.parts.map((part) => part.id)).toEqual(["origins"]);
    expect(currentPart(state)?.id).toBe("origins");
  });

  it("is pending while the backend is being waited on", async () => {
    const { player, live } = fakeBackend();
    const starting = live.start("Prepare me", null);
    expect(player.getState().pending).toBe(true);
    await starting;
    expect(player.getState().pending).toBe(false);
  });

  it("fetches each part only when the student reaches it", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    expect(api.nextPart).toHaveBeenCalledTimes(1);
    expect(nextNeeds(player.getState())).toBe("part");

    await live.advance();
    expect(api.nextPart).toHaveBeenCalledTimes(2);
    expect(currentPart(player.getState())?.id).toBe("left-divides");
  });

  it("does not fetch again for a part it already holds", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    await live.advance();
    player.back();
    expect(nextNeeds(player.getState())).toBeNull();
    await live.advance();
    expect(api.nextPart).toHaveBeenCalledTimes(2);
    expect(player.getState().index).toBe(1);
  });

  it("fetches the summary after the last part, then shows it", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    for (let step = 1; step < TOTAL; step++) await live.advance();
    expect(player.getState().index).toBe(TOTAL - 1);
    expect(nextNeeds(player.getState())).toBe("summary");
    expect(api.finishSession).not.toHaveBeenCalled();

    await live.advance();
    expect(api.finishSession).toHaveBeenCalledWith("s1");
    expect(player.getState().index).toBe(TOTAL);
    expect(player.getState().session?.summary).toEqual(sample.summary);
  });

  it("sends each answer to the backend once, as it is given", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    for (let step = 1; step < TOTAL; step++) await live.advance();
    expect(caseIsOpen(player.getState())).toBe(true);

    player.answer(LAD, clickOn(`${LAD}.0`, 0.08));
    player.answer(LAD, clickOn(`${LAD}.0`, 0.02));
    player.back();
    expect(api.sendAnswer).toHaveBeenCalledTimes(2);
    expect(api.sendAnswer.mock.calls.map(([id, answer]) => [id, answer.attempt, answer.correct])).toEqual([
      ["s1", 1, false],
      ["s1", 2, true],
    ]);
  });

  it("says what went wrong when the backend can't be reached, and starts nothing", async () => {
    const { player, live } = fakeBackend({
      startSession: vi.fn(async () => {
        throw new Error("The backend can't be reached. Check that it is running.");
      }),
    });
    await live.start("Prepare me", null);
    expect(player.getState()).toMatchObject({ session: null, pending: false, error: "The backend can't be reached. Check that it is running." });
  });

  it("refuses a part that doesn't fit the model, and lets the student try again", async () => {
    let first = true;
    const { api, player, live } = fakeBackend({
      nextPart: vi.fn(async () => {
        const part = structuredClone(sample.parts[first ? 1 : 0]);
        if (first) part.hide = ["spleen"];
        first = false;
        return { part, plan: sample.plan, done: false };
      }),
    });
    await live.start("Prepare me", null);
    expect(player.getState().error).toContain("spleen");
    expect(player.getState().session?.parts).toEqual([]);

    await live.advance();
    expect(api.nextPart).toHaveBeenCalledTimes(2);
    expect(player.getState()).toMatchObject({ error: null, index: 0 });
    expect(currentPart(player.getState())?.id).toBe("origins");
  });

  it("stays on the part and reports it when the next part can't be fetched", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    api.nextPart.mockRejectedValueOnce(new Error("No such session."));
    await live.advance();
    expect(player.getState()).toMatchObject({ index: 0, pending: false, error: "No such session." });

    await live.advance();
    expect(player.getState()).toMatchObject({ index: 1, error: null });
  });

  it("reports an answer that couldn't be sent, without losing it", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    for (let step = 1; step < TOTAL; step++) await live.advance();
    api.sendAnswer.mockRejectedValueOnce(new Error("The backend can't be reached."));
    player.answer(LAD, clickOn(`${LAD}.0`, 0.02));
    await settle();
    expect(player.getState().error).toContain("Your answer couldn't be sent");
    expect(player.getState().answers).toHaveLength(1);
  });

  it("drops a reply that arrives after the student has moved to another session", async () => {
    let release: (value: unknown) => void = () => undefined;
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    api.nextPart.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)));
    const slow = live.advance();
    player.start(recorded);
    release({ part: structuredClone(sample.parts[1]), plan: sample.plan, done: false });
    await slow;
    expect(player.getState()).toMatchObject({ live: false, index: 0, error: null });
    expect(player.getState().session?.parts).toHaveLength(TOTAL);
  });

  it("just steps on for a recorded session, with no backend calls", async () => {
    const { api, player, live } = fakeBackend();
    player.start(recorded);
    await live.advance();
    expect(player.getState().index).toBe(1);
    expect(api.nextPart).not.toHaveBeenCalled();
  });

  it("does not resend answers given before a session was reopened from the history", async () => {
    const first = fakeBackend();
    await first.live.start("Prepare me", null);
    for (let step = 1; step < TOTAL; step++) await first.live.advance();
    first.player.answer(LAD, clickOn(`${LAD}.0`, 0.08));
    const saved = first.player.getState();

    const afterReload = fakeBackend();
    afterReload.player.restore(saved);
    afterReload.player.answer(LAD, clickOn(`${LAD}.0`, 0.02));
    expect(afterReload.api.sendAnswer).toHaveBeenCalledTimes(1);
    expect(afterReload.api.sendAnswer.mock.calls[0][1].attempt).toBe(2);
  });
});
