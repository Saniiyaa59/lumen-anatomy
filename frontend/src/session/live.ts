import * as backend from "../api.ts";
import {
  checkChatReply,
  checkPart,
  checkQuestion,
  checkStart,
  checkSummary,
  isTutorQuestion,
  type ChatReply,
  type Part,
  type PlanItem,
  type SessionStart,
  type Summary,
  type TutorQuestion,
} from "./format.ts";
import { currentPart, nextNeeds, playerStore, type ChatLine, type PlayerStore } from "./player.ts";

/** The backend calls a live session makes; lets tests pass a stand-in. */
export type SessionApi = Pick<typeof backend, "startSession" | "replyToTutor" | "chat" | "nextPart" | "sendAnswer" | "finishSession">;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

/** Refuse a reply that does not fit the format or the loaded model, saying what is wrong with it. */
function mustFit(problems: string[], what: string): void {
  if (problems.length > 0) throw new Error(`The backend sent ${what} that doesn't fit the format: ${problems[0]}`);
}

function toBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    // The result is "data:application/pdf;base64,<data>".
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(new Error("The notes file couldn't be read."));
    reader.readAsDataURL(file);
  });
}

/**
 * Runs a session against the backend: starts it, fetches each part when the
 * student reaches it and the summary at the end, and sends back their answers.
 *
 * The player still holds all the state; this only decides when to ask the
 * backend and feeds what comes back into the player. A recorded session never
 * needs the backend, so for one of those `advance` simply steps on.
 */
export class LiveSessions {
  private readonly player: PlayerStore;
  private readonly api: SessionApi;
  /** How many answers of each play-through have been sent, by run id. */
  private readonly sent = new Map<string, number>();

  constructor(player: PlayerStore, api: SessionApi = backend) {
    this.player = player;
    this.api = api;
    player.subscribe(this.sendNewAnswers);
  }

  /** Start a session from what the student asked for and, optionally, their notes as a PDF. */
  async start(request: string, notes: (Blob & { name: string }) | null): Promise<void> {
    this.player.close();
    this.player.setPending(true);
    try {
      const upload = notes ? { filename: notes.name, data: await toBase64(notes) } : null;
      const reply = await this.api.startSession(request, upload);
      await this.open(reply, []);
    } catch (error) {
      this.player.setError(messageOf(error));
    } finally {
      this.player.setPending(false);
    }
  }

  /** Answer the tutor's question. It replies with a plan, and the first part is fetched, or with one more question. */
  async reply(text: string): Promise<void> {
    const { asking, pending } = this.player.getState();
    if (!asking || pending) return;
    this.player.setError(null);
    this.player.setAsking({ ...asking, chat: [...asking.chat, { from: "student", text }] });
    this.player.setPending(true);
    try {
      const reply = await this.api.replyToTutor(asking.session_id, text);
      await this.open(reply, [...asking.chat, { from: "student", text }]);
    } catch (error) {
      // The backend forgets a reply that failed, so take it back off the screen too.
      this.player.setAsking(asking);
      this.player.setError(messageOf(error));
    } finally {
      this.player.setPending(false);
    }
  }

  /**
   * Say something to the tutor mid-session. The answer appears in the thread, and the plan
   * changes if the tutor changed it. Returns the structures the answer points to, for
   * the caller to select, or an empty list if it failed.
   */
  async chat(text: string, selected: readonly string[]): Promise<string[]> {
    const state = this.player.getState();
    const { session, live, runId, pending } = state;
    if (!session || !live || pending) return [];
    const before = state.messages;
    const after = state.index;
    this.player.setError(null);
    this.player.setMessages([...before, { from: "student", text, statements: [], after }]);
    this.player.setPending(true);
    try {
      const reply = await this.api.chat(session.session_id, { text, selected, part_id: currentPart(state)?.id ?? null });
      if (!this.isCurrent(runId)) return [];
      mustFit(checkChatReply(reply), "an answer");
      const { statements, point_to, plan } = reply as ChatReply;
      this.player.setPlan(plan);
      const said = this.player.getState().messages;
      this.player.setMessages([...said, { from: "tutor", text: "", statements, after }]);
      return point_to;
    } catch (error) {
      if (this.isCurrent(runId)) {
        // The backend keeps nothing from a failed message, so take it back off the screen too.
        this.player.setMessages(before);
        this.player.setError(messageOf(error));
      }
      return [];
    } finally {
      if (this.isCurrent(runId)) this.player.setPending(false);
    }
  }

  /** Act on the reply that opens a session: show the tutor's question, or begin the session and fetch its first part. */
  private async open(reply: unknown, chat: ChatLine[]): Promise<void> {
    if (isTutorQuestion(reply)) {
      mustFit(checkQuestion(reply), "a question");
      const { session_id, request, question } = reply as TutorQuestion;
      this.player.setAsking({ session_id, request, question, chat: [...chat, { from: "tutor", text: question.text }] });
      return;
    }
    mustFit(checkStart(reply), "a session");
    this.player.start({ ...(reply as SessionStart), parts: [], summary: null }, true);
    const { runId } = this.player.getState();
    this.player.setPending(true);
    await this.fetchPart(runId);
  }

  /** Move on from the part on screen, fetching the next part or the summary first if it isn't here yet. */
  async advance(): Promise<void> {
    const state = this.player.getState();
    if (!state.session || state.pending) return;
    const needs = state.live ? nextNeeds(state) : null;
    // A live session that failed to load its first part has nothing to step on from.
    const stuckAtStart = state.live && state.session.parts.length === 0;
    if (needs === null && !stuckAtStart) {
      this.player.next();
      return;
    }
    const { runId } = state;
    this.player.setError(null);
    this.player.setPending(true);
    try {
      if (stuckAtStart || needs === "part") {
        await this.fetchPart(runId);
      } else {
        const summary = await this.api.finishSession(state.session.session_id);
        mustFit(checkSummary(summary), "a summary");
        if (this.isCurrent(runId)) this.player.setSummary(summary as Summary);
      }
      if (this.isCurrent(runId) && !stuckAtStart) this.player.next();
    } catch (error) {
      if (this.isCurrent(runId)) this.player.setError(messageOf(error));
    } finally {
      if (this.isCurrent(runId)) this.player.setPending(false);
    }
  }

  /** True while the play-through a request was made for is still the one on screen. */
  private isCurrent(runId: string | null): boolean {
    return this.player.getState().runId === runId;
  }

  private async fetchPart(runId: string | null): Promise<void> {
    const sessionId = this.player.getState().session?.session_id;
    if (!sessionId) return;
    const reply = (await this.api.nextPart(sessionId)) as { part?: unknown; plan?: unknown } | null;
    // The student may have opened another session while this was on its way.
    if (!this.isCurrent(runId)) return;
    if (reply?.part == null) throw new Error("The backend has no more parts for this session.");
    mustFit(checkPart(reply.part), "a part");
    if (Array.isArray(reply.plan)) this.player.setPlan(reply.plan as PlanItem[]);
    this.player.addPart(reply.part as Part);
  }

  /** Send each new answer of a live session to the backend, once. */
  private readonly sendNewAnswers = () => {
    const { session, live, runId, answers } = this.player.getState();
    if (!session || !live || !runId) return;
    // A new play-through is first seen with no answers. One first seen with some
    // was reopened from the history, and those were sent before.
    const already = this.sent.get(runId) ?? answers.length;
    this.sent.set(runId, answers.length);
    for (const answer of answers.slice(already)) {
      this.api.sendAnswer(session.session_id, answer).catch((error: unknown) => {
        if (this.isCurrent(runId)) this.player.setError(`Your answer couldn't be sent: ${messageOf(error)}`);
      });
    }
  };
}

export const liveSessions = new LiveSessions(playerStore);
