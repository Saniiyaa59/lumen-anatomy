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
    replyToTutor: vi.fn<SessionApi["replyToTutor"]>(async () => ({ ...structuredClone(startFields), session_id: "s1", request: "exam" })),
    chat: vi.fn<SessionApi["chat"]>(async () => ({
      statements: [structuredClone(sample.parts[0].statements[0])],
      point_to: [LAD],
      plan: sample.plan,
      plan_changed: false,
    })),
    nextPart: vi.fn<SessionApi["nextPart"]>(async () =>
      sent < TOTAL ? { part: structuredClone(sample.parts[sent++]), plan: sample.plan, done: false } : { part: null, plan: sample.plan, done: true },
    ),
    sendAnswer: vi.fn<SessionApi["sendAnswer"]>(async () => ({ plan: sample.plan })),
    finishSession: vi.fn<SessionApi["finishSession"]>(async () => structuredClone(sample.summary)),
  };
  if (overrides.startSession) api.startSession.mockImplementation(overrides.startSession);
  if (overrides.replyToTutor) api.replyToTutor.mockImplementation(overrides.replyToTutor);
  if (overrides.chat) api.chat.mockImplementation(overrides.chat);
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

describe("a tutor that asks before it plans", () => {
  const question = {
    format: "lumen.session/0.1",
    session_id: "s1",
    region: "heart",
    request: "teach me about the exam I have tmr",
    question: { text: "What does your exam cover?", options: ["Coronary arteries", "Valves"] },
  };

  it("shows the question, then plans from the answer and fetches the first part", async () => {
    const { api, player, live } = fakeBackend({ startSession: vi.fn(async () => structuredClone(question)) });
    await live.start(question.request, null);
    expect(player.getState()).toMatchObject({ session: null, pending: false, error: null });
    expect(player.getState().asking).toEqual({
      session_id: "s1",
      request: question.request,
      question: question.question,
      chat: [{ from: "tutor", text: "What does your exam cover?" }],
    });
    expect(api.nextPart).not.toHaveBeenCalled();

    await live.reply("Coronary arteries");
    expect(api.replyToTutor).toHaveBeenCalledWith("s1", "Coronary arteries");
    expect(player.getState().asking).toBeNull();
    expect(player.getState().session?.parts).toHaveLength(1);
  });

  it("can ask a second question, keeping what was said", async () => {
    const again = { ...structuredClone(question), question: { text: "Which part of the valves?", options: [] } };
    const { player, live } = fakeBackend({ startSession: vi.fn(async () => structuredClone(question)), replyToTutor: vi.fn(async () => again) });
    await live.start(question.request, null);
    await live.reply("Valves");
    expect(player.getState().asking?.chat).toEqual([
      { from: "tutor", text: "What does your exam cover?" },
      { from: "student", text: "Valves" },
      { from: "tutor", text: "Which part of the valves?" },
    ]);
  });

  it("takes a failed answer back off the screen and says why", async () => {
    const { player, live } = fakeBackend({
      startSession: vi.fn(async () => structuredClone(question)),
      replyToTutor: vi.fn(async () => {
        throw new Error("The tutor could not do that: overloaded");
      }),
    });
    await live.start(question.request, null);
    await live.reply("Valves");
    expect(player.getState().asking?.chat).toHaveLength(1);
    expect(player.getState()).toMatchObject({ pending: false, error: "The tutor could not do that: overloaded" });
  });

  it("refuses a question that doesn't fit the format", async () => {
    const { player, live } = fakeBackend({ startSession: vi.fn(async () => ({ ...structuredClone(question), question: { text: "" } })) });
    await live.start(question.request, null);
    expect(player.getState().asking).toBeNull();
    expect(player.getState().error).toContain("question.text");
  });
});

describe("talking to the tutor mid-session", () => {
  it("sends the message with the selection and the part on screen, and shows the answer after that part", async () => {
    const { api, player, live } = fakeBackend();
    await live.start("Prepare me", null);
    const pointTo = await live.chat("where does this run?", [LAD]);

    expect(api.chat).toHaveBeenCalledWith("s1", { text: "where does this run?", selected: [LAD], part_id: sample.parts[0].id });
    expect(pointTo).toEqual([LAD]);
    expect(player.getState().messages).toEqual([
      { from: "student", text: "where does this run?", statements: [], after: 0 },
      { from: "tutor", text: "", statements: [sample.parts[0].statements[0]], after: 0, pointTo: [LAD] },
    ]);
    expect(player.getState()).toMatchObject({ pending: false, error: null });
  });

  it("takes on a changed plan", async () => {
    const plan = sample.plan.slice(0, 2);
    const { player, live } = fakeBackend({
      chat: vi.fn(async () => ({ statements: [structuredClone(sample.parts[0].statements[0])], point_to: [], plan, plan_changed: true })),
    });
    await live.start("Prepare me", null);
    await live.chat("can we do less?", []);
    expect(player.getState().session?.plan).toEqual(plan);
  });

  it("takes a failed message back off the screen and says why", async () => {
    const { player, live } = fakeBackend({
      chat: vi.fn(async () => {
        throw new Error("The tutor could not do that: overloaded");
      }),
    });
    await live.start("Prepare me", null);
    expect(await live.chat("hello?", [])).toEqual([]);
    expect(player.getState()).toMatchObject({ messages: [], pending: false, error: "The tutor could not do that: overloaded" });
  });

  it("refuses an answer that points at something not on the model", async () => {
    const { player, live } = fakeBackend({
      chat: vi.fn(async () => ({ statements: [structuredClone(sample.parts[0].statements[0])], point_to: ["spleen"], plan: sample.plan, plan_changed: false })),
    });
    await live.start("Prepare me", null);
    await live.chat("what is this?", []);
    expect(player.getState().error).toContain("spleen");
    expect(player.getState().messages).toEqual([]);
  });
});

describe("exploring with no plan", () => {
  const explore = { ...structuredClone(startFields), session_id: "s1", request: "Explore the heart", plan: [] };
  const statement = sample.parts[0].statements[0];

  it("opens with no part to fetch, and chat messages come before any part", async () => {
    const { api, player, live } = fakeBackend({ startSession: vi.fn(async () => structuredClone(explore)), chat: vi.fn(async () => ({ statements: [structuredClone(statement)], point_to: [], plan: [], plan_changed: false })) });
    expect(await live.start("", null)).toEqual([]);
    expect(api.nextPart).not.toHaveBeenCalled();
    expect(player.getState().session?.plan).toEqual([]);
    await live.chat("what is this?", [LAD]);
    expect(player.getState().messages.map((m) => [m.from, m.after])).toEqual([
      ["student", -1],
      ["tutor", -1],
    ]);
  });

  it("shows the answer to an opening question with the question above it", async () => {
    const answered = { ...structuredClone(explore), request: "how does blood flow in the aorta?", answer: { statements: [structuredClone(statement)], point_to: [LAD] } };
    const { player, live } = fakeBackend({ startSession: vi.fn(async () => answered) });
    expect(await live.start("how does blood flow in the aorta?", null)).toEqual([LAD]);
    expect(player.getState().messages).toEqual([
      { from: "student", text: "how does blood flow in the aorta?", statements: [], after: -1 },
      { from: "tutor", text: "", statements: [statement], after: -1, pointTo: [LAD] },
    ]);
  });

  it("fetches the first part when the tutor plans a session from the chat", async () => {
    const { api, player, live } = fakeBackend({
      startSession: vi.fn(async () => structuredClone(explore)),
      chat: vi.fn(async () => ({ statements: [structuredClone(statement)], point_to: [], plan: sample.plan, plan_changed: true })),
    });
    await live.start("", null);
    await live.chat("quiz me on this", []);
    expect(api.nextPart).toHaveBeenCalledTimes(1);
    expect(player.getState().session?.parts).toHaveLength(1);
    expect(player.getState().pending).toBe(false);
  });

  it("keeps the questions asked before the plan when the session opens", async () => {
    const question = { format: "lumen.session/0.1", session_id: "s1", region: "heart", request: "exam", question: { text: "What does it cover?", options: [] } };
    const { player, live } = fakeBackend({ startSession: vi.fn(async () => question) });
    await live.start("exam", null);
    await live.reply("Coronary arteries");
    expect(player.getState().messages.map((m) => [m.from, m.text])).toEqual([
      ["student", "exam"],
      ["tutor", "What does it cover?"],
      ["student", "Coronary arteries"],
    ]);
  });
});
