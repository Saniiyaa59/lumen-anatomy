import { describe, expect, it, vi } from "vitest";
import sample from "../../../assets/fixtures/sessions/coronary_arteries.json";
import { parseSession } from "./format.ts";
import { HistoryStore, type KeyValueStorage } from "./history.ts";
import { currentPart, PlayerStore } from "./player.ts";

const session = parseSession(sample);
const KEY = "lumen.history.v1";

/** Browser storage held in a plain object. */
function fakeStorage(initial: Record<string, string> = {}): KeyValueStorage & { data: Record<string, string> } {
  const data = { ...initial };
  return { data, getItem: (key) => data[key] ?? null, setItem: (key, value) => void (data[key] = value) };
}

/** Start a session at a given clock time, so each run gets its own id and order. */
function startAt(player: PlayerStore, time: number) {
  vi.spyOn(Date, "now").mockReturnValue(time);
  player.start(session);
  vi.restoreAllMocks();
  return player.getState().runId!;
}

describe("HistoryStore", () => {
  it("starts empty", () => {
    expect(new HistoryStore(new PlayerStore(), fakeStorage()).getEntries()).toEqual([]);
  });

  it("lists a session as soon as it starts, titled by the request", () => {
    const player = new PlayerStore();
    const history = new HistoryStore(player, fakeStorage());
    const runId = startAt(player, 1000);
    expect(history.getEntries()).toMatchObject([{ runId, request: session.request, startedAt: 1000 }]);
  });

  it("keeps one entry per play-through and updates it as the student goes on", () => {
    const player = new PlayerStore();
    const history = new HistoryStore(player, fakeStorage());
    startAt(player, 1000);
    player.next();
    player.next();
    expect(history.getEntries()).toHaveLength(1);
    expect(history.getEntries()[0].state.index).toBe(2);
  });

  it("lists the newest session first", () => {
    const player = new PlayerStore();
    const history = new HistoryStore(player, fakeStorage());
    const first = startAt(player, 1000);
    const second = startAt(player, 2000);
    expect(history.getEntries().map((entry) => entry.runId)).toEqual([second, first]);
  });

  it("keeps a session in the list after it is closed, and reopens it where it was left", () => {
    const player = new PlayerStore();
    const history = new HistoryStore(player, fakeStorage());
    const runId = startAt(player, 1000);
    player.goTo(2);
    player.setDamage(0.03);
    player.close();
    expect(player.getState().session).toBeNull();
    expect(history.getEntries()).toHaveLength(1);

    history.open(runId);
    expect(currentPart(player.getState())?.kind).toBe("damage_slider");
    expect(player.damageAt()).toBe(0.03);
  });

  it("survives a reload: a new store reads what the last one saved", () => {
    const storage = fakeStorage();
    const player = new PlayerStore();
    new HistoryStore(player, storage);
    const runId = startAt(player, 1000);
    player.next();

    const afterReload = new PlayerStore();
    const history = new HistoryStore(afterReload, storage);
    expect(history.getEntries().map((entry) => entry.runId)).toEqual([runId]);
    history.open(runId);
    expect(afterReload.getState().index).toBe(1);
  });

  it("removes an entry, closing it first if it is on screen", () => {
    const player = new PlayerStore();
    const history = new HistoryStore(player, fakeStorage());
    const runId = startAt(player, 1000);
    history.remove(runId);
    expect(history.getEntries()).toEqual([]);
    expect(player.getState().session).toBeNull();
  });

  it("drops saved entries that are damaged or no longer fit the session format", () => {
    const storage = fakeStorage();
    const player = new PlayerStore();
    new HistoryStore(player, storage);
    startAt(player, 1000);
    const good = JSON.parse(storage.data[KEY])[0];
    const outdated = structuredClone(good);
    outdated.runId = outdated.state.runId = "old";
    outdated.state.session.format = "lumen.session/0.0";
    storage.data[KEY] = JSON.stringify([good, outdated, { runId: 7 }, null]);
    expect(new HistoryStore(new PlayerStore(), storage).getEntries().map((entry) => entry.runId)).toEqual([good.runId]);

    storage.data[KEY] = "not json";
    expect(new HistoryStore(new PlayerStore(), storage).getEntries()).toEqual([]);
  });

  it("still works when the browser refuses to store anything", () => {
    const blocked: KeyValueStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("storage is full");
      },
    };
    const player = new PlayerStore();
    const history = new HistoryStore(player, blocked);
    startAt(player, 1000);
    expect(history.getEntries()).toHaveLength(1);
  });

  it("tells subscribers when the list changes", () => {
    const player = new PlayerStore();
    const history = new HistoryStore(player, fakeStorage());
    const listener = vi.fn();
    history.subscribe(listener);
    startAt(player, 1000);
    expect(listener).toHaveBeenCalled();
  });
});
