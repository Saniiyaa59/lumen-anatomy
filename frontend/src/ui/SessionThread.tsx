import "../session/session.css";
import { Fragment, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import sampleSession from "../../../assets/fixtures/sessions/coronary_arteries.json";
import { getTutorSource, type Working } from "../api.ts";
import { selectionStore } from "../selection/store.ts";
import { atlasTitle, parseSession, type ClickCase, type DamageSlider, type MultipleChoice, type Part, type Source, type Statement } from "../session/format.ts";
import { inTarget } from "../session/grade.ts";
import { liveSessions } from "../session/live.ts";
import { currentPart, playerStore, questionIsOpen, quizIsOpen, usePlayer, type Asking, type CaseOutcome, type PlayerState, type SessionMessage } from "../session/player.ts";

const KIND_NAMES: Record<Part["kind"], string> = {
  demonstration: "Demonstration",
  pulse: "Follow the flow",
  damage_slider: "Try it",
  click_case: "Case",
  multiple_choice: "Question",
};

/** Parts the student answers, whose result shows in the thread and the summary. */
const isQuiz = (part: Part): part is ClickCase | MultipleChoice => part.kind === "click_case" || part.kind === "multiple_choice";

const mm = (metres: number) => `${Math.round(metres * 1000)} mm`;

/** What the suggestion on the start screen asks for. */
const SUGGESTION = "Prepare me on the blood supply of the heart";

/** Select what the tutor's answer points to, unless the student already has something selected. */
function selectIfNothing(pointTo: string[]): void {
  if (pointTo.length > 0 && selectionStore.getState().selected.length === 0) selectionStore.set(pointTo);
}

/** Ask the backend for a session on what the student typed, with their notes if they attached any. Empty: just explore. */
function startSession(request: string, notes: File | null): void {
  selectionStore.clear();
  void liveSessions.start(request, notes).then(selectIfNothing);
}

/** Play the sample held in the app itself, with no backend. The way out when the backend can't be reached. */
function startBuiltInSample(): void {
  selectionStore.clear();
  playerStore.start(parseSession(sampleSession));
}

/** Where a fact came from, shown under it. */
function SourceTag({ source }: { source: Source }) {
  switch (source.type) {
    case "notes":
      return (
        <span className="source">
          Your notes: {source.file}, page {source.page}
        </span>
      );
    case "atlas":
      return source.url ? (
        <a className="source" href={source.url} target="_blank" rel="noreferrer" title={`Atlas entry: ${source.article}`}>
          Atlas: {atlasTitle(source)}
        </a>
      ) : (
        <span className="source">Atlas: {atlasTitle(source)}</span>
      );
    case "web":
      return (
        <a className="source" href={source.url} target="_blank" rel="noreferrer">
          Web: {source.title}
        </a>
      );
    case "model":
      return <span className="source">Measured on the model</span>;
  }
}

function StatementView({ statement, className = "statement" }: { statement: Statement; className?: string }) {
  return (
    <div className={className}>
      <p>{statement.text}</p>
      <SourceTag source={statement.source} />
    </div>
  );
}

function SliderControls({ part, at }: { part: DamageSlider; at: number }) {
  const zone = part.zones.find((candidate) => inTarget({ regions: candidate.regions, structures: [] }, { structureId: "", piece: part.track.piece, at }));
  return (
    <div className="thread-task">
      <label className="thread-slider">
        <span>
          Blockage <strong>{mm(at)}</strong> from the start of the artery
        </span>
        <input
          type="range"
          min={part.track.from}
          max={part.track.to}
          step={0.0005}
          value={at}
          onChange={(event) => playerStore.setDamage(Number(event.target.value))}
        />
      </label>
      <p className="thread-hint">Drag the slider, or click the artery, to move the blockage. Grey shows what it cuts off.</p>
      {zone && <StatementView statement={zone.statement} className="statement statement-live" />}
    </div>
  );
}

function caseResult(outcome: CaseOutcome | undefined): string {
  if (outcome?.correct) return `Correct on try ${outcome.attempts}`;
  if (outcome?.revealed) return `Answer shown after ${outcome.attempts} ${outcome.attempts === 1 ? "try" : "tries"}`;
  return "Not answered";
}

function CaseControls({ part, outcome }: { part: ClickCase; outcome: CaseOutcome | undefined }) {
  const done = outcome?.correct || outcome?.revealed;
  const verdict = outcome?.correct ? "correct" : outcome?.revealed ? "revealed" : outcome?.statement ? "wrong" : null;
  // Feedback can land below the fold; bring it into view each time it changes.
  const feedback = useRef<HTMLDivElement>(null);
  useEffect(() => {
    feedback.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [outcome?.attempts, verdict]);
  return (
    <div className="thread-task">
      <p className="thread-story">{part.story}</p>
      <p className="thread-question">{part.question}</p>
      {!done && <p className="thread-hint">Click the place on the model. Names are hidden for this case.</p>}
      {verdict && outcome?.statement && (
        <div className="thread-feedback" data-verdict={verdict} role="status" ref={feedback}>
          <strong>{verdict === "correct" ? "Correct" : verdict === "revealed" ? "The answer" : "Not quite"}</strong>
          <StatementView statement={outcome.statement} />
          {done && <p className="thread-hint">The correct stretch is shown in green.</p>}
        </div>
      )}
      {!done && (outcome?.attempts ?? 0) > 0 && (
        <button type="button" className="thread-link" onClick={() => playerStore.reveal()}>
          Show me the answer
        </button>
      )}
    </div>
  );
}

/** How one option looks: not picked yet, picked and wrong, or the right one once it is known. */
function optionState(index: number, part: MultipleChoice, outcome: CaseOutcome | undefined): "open" | "wrong" | "correct" {
  const done = outcome?.correct || outcome?.revealed;
  if (done && part.options[index].correct) return "correct";
  return outcome?.picks?.includes(index) ? "wrong" : "open";
}

function ChoiceControls({ part, outcome }: { part: MultipleChoice; outcome: CaseOutcome | undefined }) {
  const done = outcome?.correct || outcome?.revealed;
  const right = part.options.find((option) => option.correct)!;
  const lastPick = outcome?.picks?.at(-1);
  // The feedback on the latest wrong pick, which still matters once the answer is shown.
  const missed = lastPick !== undefined && !part.options[lastPick].correct ? part.options[lastPick] : null;
  const feedback = useRef<HTMLDivElement>(null);
  useEffect(() => {
    feedback.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [outcome?.attempts, outcome?.revealed]);
  return (
    <div className="thread-task">
      {part.story && <p className="thread-story">{part.story}</p>}
      <p className="thread-question">{part.question}</p>
      <div className="thread-options" role="group" aria-label="Answers">
        {part.options.map((option, index) => {
          const look = optionState(index, part, outcome);
          return (
            <button
              type="button"
              key={index}
              className="thread-option"
              data-state={look}
              disabled={done || look !== "open"}
              aria-keyshortcuts={String(index + 1)}
              onClick={() => playerStore.pick(index)}
            >
              <span className="thread-option-key" aria-hidden="true">
                {index + 1}
              </span>
              {option.text}
            </button>
          );
        })}
      </div>
      {!done && (
        <p className="thread-hint">
          Press 1 to {part.options.length}, or click an answer.{part.highlight.length > 0 && " Names are hidden on the model until you answer."}
        </p>
      )}
      <div ref={feedback}>
        {missed && !outcome?.correct && (
          <div className="thread-feedback" data-verdict="wrong" role="status">
            <strong>Not quite</strong>
            <StatementView statement={missed.feedback} />
          </div>
        )}
        {done && (
          <div className="thread-feedback" data-verdict={outcome?.correct ? "correct" : "revealed"} role="status">
            <strong>{outcome?.correct ? "Correct" : `The answer: ${right.text}`}</strong>
            <StatementView statement={right.feedback} />
          </div>
        )}
      </div>
      {!done && (outcome?.attempts ?? 0) > 0 && (
        <button type="button" className="thread-link" onClick={() => playerStore.reveal()}>
          Show me the answer
        </button>
      )}
    </div>
  );
}

/** One part of the session, as a card in the thread. Only the part on screen is open. */
function PartCard({ part, step, state }: { part: Part; step: number; state: PlayerState }) {
  const active = step === state.index;
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    if (active) card.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);

  if (!active) {
    return (
      <button type="button" className="thread-card thread-card-closed" onClick={() => playerStore.goTo(step)}>
        <span className="thread-step">{step + 1}</span>
        <span className="thread-card-title">{part.title}</span>
        {isQuiz(part) && <span className="thread-card-note">{caseResult(state.outcomes[part.id])}</span>}
      </button>
    );
  }
  return (
    <article className="thread-card thread-card-open" ref={card} aria-current="step">
      <p className="thread-kind">
        {step + 1}. {KIND_NAMES[part.kind]}
      </p>
      <h3>{part.title}</h3>
      {/* The slider comes before the reading, so it is in reach without scrolling. */}
      {part.kind === "damage_slider" && <SliderControls part={part} at={state.damage[part.id] ?? part.start_at} />}
      {part.statements.map((statement, i) => (
        <StatementView statement={statement} key={i} />
      ))}
      {part.kind === "click_case" && <CaseControls part={part} outcome={state.outcomes[part.id]} />}
      {part.kind === "multiple_choice" && <ChoiceControls part={part} outcome={state.outcomes[part.id]} />}
    </article>
  );
}

function SummaryCard({ state }: { state: PlayerState }) {
  const session = state.session!;
  const summary = session.summary!;
  const cases = session.parts.filter(isQuiz);
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    card.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);
  return (
    <article className="thread-card thread-card-open" ref={card}>
      <p className="thread-kind">Summary</p>
      {cases.length > 0 && (
        <>
          <h4>Your answers</h4>
          <ul className="thread-list">
            {cases.map((part) => (
              <li key={part.id}>
                {part.title}: {caseResult(state.outcomes[part.id]).toLowerCase()}
              </li>
            ))}
          </ul>
        </>
      )}
      <h4>Solid</h4>
      <ul className="thread-list">
        {summary.solid.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <h4>Worth another look</h4>
      <ul className="thread-list">
        {summary.shaky.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <h4>Sources used</h4>
      <ul className="thread-list thread-sources">
        {summary.sources.map((source, index) => (
          <li key={index}>
            <SourceTag source={source} />
          </li>
        ))}
      </ul>
    </article>
  );
}

/**
 * Send what the student typed mid-session, with what they have selected. What the answer
 * points to is selected only if they had nothing selected; otherwise their selection stays
 * and the answer offers "Show on model".
 */
function sendChat(text: string): void {
  void liveSessions.chat(text, selectionStore.getState().selected).then(selectIfNothing);
}

/**
 * The box at the bottom of the thread: say what you need, and attach your notes as a PDF.
 * With `onReply` it sends what is typed there instead (an answer to the tutor, or a
 * message mid-session), and takes no file. `inSession` without `onReply` means a
 * session that can't be talked to, such as the built-in sample.
 */
function Composer({ inSession, busy, onReply }: { inSession: boolean; busy: boolean; onReply?: (text: string) => void }) {
  const [text, setText] = useState("");
  const [notes, setNotes] = useState<File | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const blocked = (inSession && !onReply) || busy;
  const label = inSession
    ? onReply
      ? "Ask the tutor, or ask to go another way"
      : "The built-in sample can't answer questions"
    : onReply
      ? "Answer the tutor"
      : "What do you need to be ready for?";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const request = text.trim();
    if (blocked || request === "") return;
    if (onReply) {
      onReply(request);
      setText("");
      return;
    }
    startSession(request, notes);
    setText("");
    setNotes(null);
  };
  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    setNotes(event.target.files?.[0] ?? null);
    // Clear the picker so choosing the same file again still counts as a change.
    event.target.value = "";
  };

  return (
    <form className="composer" onSubmit={submit}>
      {notes && (
        <p className="composer-file">
          <span>{notes.name}</span>
          <button type="button" aria-label={`Remove ${notes.name}`} title="Remove" onClick={() => setNotes(null)}>
            ×
          </button>
        </p>
      )}
      <div className="composer-row">
        <input type="file" accept="application/pdf,.pdf" hidden ref={picker} onChange={pick} />
        <button
          type="button"
          className="composer-icon"
          disabled={blocked || onReply !== undefined}
          title="Attach your notes as a PDF"
          aria-label="Attach your notes as a PDF"
          onClick={() => picker.current?.click()}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.9-8.9a3.7 3.7 0 0 1 5.2 5.2l-8.8 8.8a1.8 1.8 0 0 1-2.6-2.6l8.1-8.1" />
          </svg>
        </button>
        <input type="text" value={text} disabled={blocked} onChange={(event) => setText(event.target.value)} placeholder={label} aria-label={label} />
        <button type="submit" className="composer-send" disabled={blocked || text.trim() === ""} aria-label={onReply ? "Send" : "Start the session"}>
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </button>
      </div>
    </form>
  );
}

/** Shown before any session: what the tutor does and how to begin. */
function StartScreen({ state }: { state: PlayerState }) {
  // Whether the backend builds sessions with Claude or hands out its sample; unknown until it answers.
  const [source, setSource] = useState<"sample" | "agent" | null>(null);
  useEffect(() => {
    let cancelled = false;
    getTutorSource().then(
      (found) => !cancelled && setSource(found),
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, []);
  return (
    <div className="thread-start">
      <h2>What do you need to be ready for?</h2>
      <p>Tell the tutor a topic. It builds a study session on the model: it shows, asks you to click where, and explains from your notes and the atlas.</p>
      <button type="button" className="thread-suggestion" disabled={state.pending} onClick={() => startSession(SUGGESTION, null)}>
        Blood supply of the heart
      </button>
      <button type="button" className="thread-suggestion" disabled={state.pending} onClick={() => startSession("", null)}>
        Just explore the model
      </button>
      {state.pending && (
        <p className="thread-status" role="status">
          {source === "agent" ? "The tutor is reading and planning. This can take a minute…" : "Starting your session…"}
        </p>
      )}
      {state.pending && <WorkingNow state={state} />}
      {state.error && (
        <div className="thread-error" role="alert">
          <p>The session couldn't start. {state.error}</p>
          <button type="button" className="thread-link" onClick={startBuiltInSample}>
            Play the built-in sample instead
          </button>
        </div>
      )}
      {source === "agent" ? (
        <p className="thread-hint">Sessions are built by Claude for what you ask. Starting one takes about a minute and uses API credit.</p>
      ) : (
        <p className="thread-hint">
          The tutor is switched off. Whatever you ask, the backend replies with one hand-written sample session on the coronary arteries, and it doesn't read
          your notes.
        </p>
      )}
    </div>
  );
}

/** Something said mid-session: the student's words as a bubble, the tutor's answer as a card with its sources. */
function MessageView({ message }: { message: SessionMessage }) {
  if (message.from === "student") return <p className="thread-bubble">{message.text}</p>;
  return (
    <article className="thread-card thread-card-open">
      <p className="thread-kind">Tutor</p>
      {message.text && <p>{message.text}</p>}
      {message.statements.map((statement, i) => (
        <StatementView statement={statement} key={i} />
      ))}
      {message.pointTo && message.pointTo.length > 0 && (
        <button type="button" className="thread-link" onClick={() => selectionStore.set(message.pointTo!)}>
          Show on model
        </button>
      )}
    </article>
  );
}

/** Before the plan: the tutor's questions and the student's answers, with the open question's answers as buttons. */
function Conversation({ asking, state }: { asking: Asking; state: PlayerState }) {
  const reply = (text: string) => void liveSessions.reply(text).then(selectIfNothing);
  return (
    <aside className="thread" aria-label="Study session">
      <header className="thread-header">
        <h2>{asking.request}</h2>
        <p>Before planning</p>
      </header>
      <div className="thread-scroll">
        <p className="thread-bubble">{asking.request}</p>
        {asking.chat.map((line, index) =>
          line.from === "student" ? (
            <p className="thread-bubble" key={index}>
              {line.text}
            </p>
          ) : (
            <article className="thread-card thread-card-open" key={index}>
              <p className="thread-kind">Tutor</p>
              <p>{line.text}</p>
            </article>
          ),
        )}
        {!state.pending &&
          asking.question.options.map((option) => (
            <button type="button" className="thread-suggestion" key={option} onClick={() => reply(option)}>
              {option}
            </button>
          ))}
        {state.pending && (
          <p className="thread-status" role="status">
            The tutor is thinking about your answer. This can take a minute…
          </p>
        )}
        {state.pending && <WorkingNow state={state} />}
        {state.error && (
          <div className="thread-error" role="alert">
            <p>{state.error}</p>
          </div>
        )}
      </div>
      <Composer inSession={false} busy={state.pending} onReply={reply} />
    </aside>
  );
}

/**
 * The session as a conversation beside the 3D view: the student's request, the
 * tutor's plan, then each part as a card, with the way forward and an input
 * box at the bottom.
 */
/**
 * The piece of work the student is waiting on, of those the tutor has under way:
 * a decision about their answers or the next part when they asked for it, otherwise
 * whatever began first. Parts further ahead are being built at the same time.
 */
function waitedOn(state: PlayerState): Working | null {
  const { working, session, index } = state;
  if (working.length === 0) return null;
  const current = session?.parts[index]?.id;
  // The part being fetched is the first one not yet received.
  const next = session?.plan[session.parts.length]?.part_id;
  return (
    working.find((item) => item.stage === `decide after ${current}`) ??
    working.find((item) => item.stage === `part ${next}`) ??
    working.find((item) => !item.stage.startsWith("part ")) ??
    working[0]
  );
}

/** What the tutor is doing, under the line that says it is busy. */
function WorkingNow({ state }: { state: PlayerState }) {
  const item = waitedOn(state);
  if (!item) return null;
  return (
    <p className="thread-working" aria-live="polite">
      <span className="thread-working-doing">{item.doing}</span>
      {item.detail && <span className="thread-working-detail">{item.detail}</span>}
      <span className="thread-working-time">{Math.round(item.seconds)} s</span>
    </p>
  );
}

/** Whether a key press is meant for a text box, a slider or another control rather than for the session. */
function typing(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
}

/**
 * Keys for the session: 1 to 5 pick an answer to the question on screen, and
 * Enter moves on once nothing is waiting for an answer. Ignored while typing.
 */
function useSessionKeys(state: PlayerState): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
      const part = currentPart(state);
      if (part?.kind === "multiple_choice" && questionIsOpen(state) && /^[1-9]$/.test(event.key)) {
        if (playerStore.pick(Number(event.key) - 1)) event.preventDefault();
        return;
      }
      // Enter on a focused button already presses it; otherwise it means Next.
      if (event.key === "Enter" && !(event.target instanceof HTMLButtonElement) && state.session && !state.pending && !quizIsOpen(state)) {
        event.preventDefault();
        void liveSessions.advance();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [state]);
}

export default function SessionThread() {
  const state = usePlayer();
  const { session, index } = state;
  const waiting = quizIsOpen(state);
  useSessionKeys(state);

  if (!session && state.asking) return <Conversation asking={state.asking} state={state} />;
  if (!session) {
    return (
      <aside className="thread" aria-label="Study session">
        <div className="thread-scroll">
          <StartScreen state={state} />
        </div>
        <Composer inSession={false} busy={state.pending} />
      </aside>
    );
  }

  const total = session.plan.length;
  const atSummary = index >= total;
  const reachedSummary = state.reached >= total && session.summary !== null;
  const shown = session.parts.slice(0, Math.min(state.reached, session.parts.length - 1) + 1);
  const next = () => void liveSessions.advance();
  // No plan: the student is exploring, asking about what they select. A plan may arrive later.
  const exploring = total === 0;
  const early = state.messages.filter((message) => message.after === -1);

  return (
    <aside className="thread" aria-label="Study session">
      <header className="thread-header">
        <h2>{session.request}</h2>
        <p>
          {exploring
            ? "Exploring · select structures and ask about them"
            : `${atSummary ? "Summary" : `Part ${Math.min(index + 1, total)} of ${total}`} · ${state.live ? "from the backend" : "built-in sample"}`}
        </p>
      </header>

      <div className="thread-scroll">
        {/* What was said before any part: the request itself is among it, so it isn't shown twice. */}
        {early.length === 0 && !exploring && <p className="thread-bubble">{session.request}</p>}
        {exploring && early.length === 0 && (
          <article className="thread-card thread-card-open">
            <p className="thread-kind">Explore</p>
            <p>
              Click a structure on the model, Shift- or ⌘-click to add more, and ask about them below. Ask to be quizzed or taken through a topic whenever you
              like.
            </p>
          </article>
        )}
        {early.map((message, i) => (
          <MessageView message={message} key={i} />
        ))}

        {!exploring && (
          <article className="thread-card thread-card-open">
            <p className="thread-kind">Plan</p>
            <ol className="thread-plan">
              {session.plan.map((item, step) => (
                <li key={item.part_id} data-done={step < index} aria-current={step === index ? "step" : undefined}>
                  {item.title}
                </li>
              ))}
            </ol>
            <details className="thread-scope">
              <summary>What the model can and can't show</summary>
              <h4>On the model</h4>
              <ul className="thread-list">
                {session.scope.can_show.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <h4>In words only</h4>
              <ul className="thread-list">
                {session.scope.words_only.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          </article>
        )}

        {shown.map((part, step) => (
          <Fragment key={part.id}>
            <PartCard part={part} step={step} state={state} />
            {state.messages
              .filter((message) => message.after >= 0 && Math.min(message.after, shown.length - 1) === step)
              .map((message, i) => (
                <MessageView message={message} key={i} />
              ))}
          </Fragment>
        ))}
        {reachedSummary &&
          (atSummary ? (
            <SummaryCard state={state} />
          ) : (
            <button type="button" className="thread-card thread-card-closed" onClick={() => playerStore.goTo(total)}>
              <span className="thread-card-title">Summary</span>
            </button>
          ))}
        {state.pending && (
          <p className="thread-status" role="status">
            {state.messages.at(-1)?.from === "student"
              ? "The tutor is answering…"
              : session.parts.length === 0
                ? "Preparing the first part…"
                : "Preparing what comes next…"}
          </p>
        )}
        {state.pending && <WorkingNow state={state} />}
        {state.error && (
          <div className="thread-error" role="alert">
            <p>{state.error}</p>
          </div>
        )}
      </div>

      {exploring ? (
        <nav className="thread-nav" aria-label="Leave">
          <button type="button" onClick={() => playerStore.close()}>
            Finish
          </button>
        </nav>
      ) : (
        <nav className="thread-nav" aria-label="Move through the session">
          <button type="button" disabled={index === 0 || state.pending} onClick={() => playerStore.back()}>
            Back
          </button>
          {atSummary ? (
            <button type="button" className="thread-primary" onClick={() => playerStore.close()}>
              Finish
            </button>
          ) : (
            <button type="button" className={waiting ? undefined : "thread-primary"} disabled={state.pending} onClick={next}>
              {state.pending ? "Loading…" : state.error ? "Try again" : waiting ? "Skip" : index === total - 1 ? "See the summary" : "Next"}
            </button>
          )}
        </nav>
      )}
      <Composer inSession busy={state.pending} onReply={state.live ? sendChat : undefined} />
    </aside>
  );
}
