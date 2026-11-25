# Session format

**Status: proposal (2026-11-14), version `lumen.session/0.1`. Not yet agreed by both of us.** It is shared between the browser and the backend, so neither side should change it alone.

A study session is a back-and-forth. The browser sends the student's request and, later, their clicks. The backend sends a plan, then one part at a time, then a summary. This page describes that data. It does not describe how the backend stores a session or what it gives the agent.

- Types and the check on the frontend: `frontend/src/session/format.ts`
- Models on the backend: `backend/app/session_schemas.py`
- A complete example: `assets/fixtures/sessions/coronary_arteries.json`

## Rules that apply everywhere

- **JSON, with snake_case field names**, as in `/api/command`.
- **Ids come from the atlas export.** Structure ids are those in `assets/regions/heart/structures.json`. Piece ids are those in `centerlines.json`, such as `anterior_interventricular_artery.0`.
- **Distances are in metres along one centre-line piece**, measured from the start of that piece.
- **Every piece of text the student reads carries a source**, except a case's patient story, which is invented.
- **The browser grades clicks.** It already holds the centre lines, so feedback is immediate. The backend is told the result.

## Building blocks

| Name | Fields | Meaning |
| --- | --- | --- |
| Statement | `text`, `source` | One or two sentences and where they came from |
| Place | `piece`, `at` | A point on a vessel |
| Region | `piece`, `from`, `to` | A stretch of one piece, with `from` less than `to` |
| Target | `regions`, `structures` | Where a click counts: stretches of vessel and/or whole structures |
| View | `look_at`, `side` | What the camera should show |

**Source** is one of:

| `type` | Other fields | Shown to the student as |
| --- | --- | --- |
| `notes` | `file`, `page` | "Your notes, page 12" |
| `atlas` | `article`, `url` (or `null`) | The title of the page `url` links to, linked; the article's name when there is no link |
| `web` | `title`, `url` | The page's title, linked |
| `model` | none | "Measured on the model" |

`article` is a `key` in `assets/text/z_anatomy_articles.jsonl`, and `url` is that article's `source_url`. Several articles hold a whole page under one structure's name ("Left ventricle" is the page *Ventricle (heart)*, about both ventricles), so the browser names a source by its page, and the summary lists each page once.

**View** names what to look at, not where the camera is. `look_at` is a list of structure ids to frame. `side` is `anterior`, `posterior`, `left`, `right`, `superior`, `inferior`, or `null` to let the viewer pick a side from which they can be seen. The agent cannot know camera coordinates; the viewer can work them out.

## Parts

Every part has these fields:

| Field | Meaning |
| --- | --- |
| `id` | Unique within the session |
| `kind` | `demonstration`, `pulse`, `damage_slider`, `click_case` or `multiple_choice` |
| `title` | Shown above the part |
| `view` | A View |
| `hide` | What is hidden for this part, such as what is in the way. Each entry is a structure id, or a group id to hide everything in that group (`cardiac_veins`) |
| `statements` | Statements shown in order; may be empty except for a demonstration |

Each kind adds its own:

| Kind | Extra fields | What happens |
| --- | --- | --- |
| `demonstration` | `highlight`: structure ids | The model turns, hides and highlights |
| `pulse` | `from`: Place; `to`: Place or `null` | A pulse runs from `from` to `to`. With `null` it spreads into every branch beyond `from` |
| `damage_slider` | `track`: Region; `start_at`: distance; `zones`: list of `{regions, statement}` | The student drags a damage point along `track`. Everything beyond it greys out. A zone's statement shows while the point is inside that zone |
| `click_case` | `story`, `question`, `answer`, `feedback` | The student reads the story and clicks where the problem is |
| `multiple_choice` | `highlight`: structure ids (may be empty); `story`: text or `null`; `question`; `options`: 2 to 5 of `{text, correct, feedback}` | The student picks one answer and reads its feedback |

For a `click_case`:

- `answer` is a Target plus `tolerance`: how far past the end of a region a click still counts, in metres.
- `feedback.correct` and `feedback.wrong` are Statements.
- `feedback.near_misses` is a list of Targets, each with its own `statement`, for wrong places that deserve a specific explanation. A near miss may not overlap the answer.

For a `multiple_choice`:

- Exactly one option has `correct: true`, and no two options have the same text.
- `feedback` is a Statement: why that answer is right or wrong. It is shown once the student picks it.
- After two wrong picks, or once a wrong pick leaves only one option, the browser shows the answer. The backend counts the same way, so it can decide what comes next straight away.
- With `highlight`, the question is about what is marked ("Which artery is highlighted?"). This is how the student is asked to name a structure, so the viewer hides names on the model, labels and hover alike, until they have answered, as it does during a case. Without `highlight` the question is about something the model can't show, and the view is only a backdrop; its `side` may be `null`.
- `story`, like a case's, is an invented patient and has no source.

"Beyond" always means away from the trunk: the rest of the piece, and every branch that leaves after that point. In an artery this is what a blockage cuts off.

## What the backend sends

**At the start**

| Field | Meaning |
| --- | --- |
| `format` | `"lumen.session/0.1"` |
| `session_id` | Used in every later request |
| `region` | The region the session is on, `"heart"` |
| `request` | What the student asked, as understood |
| `scope` | `can_show` and `words_only`: lists of short sentences on what the model can show and what can only be explained |
| `plan` | List of `{part_id, title, kind}`, in order |

**An empty plan means exploring.** When the student's first message is a question rather than a request to be taught or tested ("how does blood flow in the aorta?"), the tutor answers it: the start fields come with `plan: []` and `answer: {statements, point_to}`. The student goes on asking with `/chat`, and the tutor fills the plan only if they ask for a session. An empty `request` opens the model to explore straight away, with no call to Claude and no `answer`; its `request` is then "Explore the heart". `answer` is left out when there is none. A recorded session always has a plan.

**Or, instead, a question.** When the tutor can't tell what to cover (for example "help me with my exam" and no notes), its first reply is a question in place of `scope` and `plan`: `format`, `session_id`, `region`, `request` and `question`, which is `{text, options}`. `options` holds up to four answers the student can pick with one click; they can also type their own. The student answers with `/reply`, and the reply to that is the start fields above or another question. The tutor asks at most two questions before it must plan. The sample never asks.

**During the session**, the student can say something at any time (`/chat`). The tutor answers with sourced statements, may point to structures, and may replace the parts not yet sent with new ones, for example when the student asks for another topic.

**For each part:** one part, in the shape above. The plan may be sent again if it changed.

**At the end:** `summary`, with `solid` and `shaky` (lists of short phrases, each naming a topic; a topic is in one list only, and `shaky` is empty when nothing went wrong) and `sources` (every source used). The browser offers a new session on the `shaky` topics.

A **recorded session** is all of this in one file: the start fields, plus `parts` (the list of parts) and `summary`. The sample is one. The player can run a recorded session with no backend, which is what "Play the built-in sample instead" does when the backend can't be reached.

## What the browser sends

**At the start:** the student's request as text, and optionally their notes as a PDF.

**After each pick on a multiple-choice question:** `part_id`, `attempt`, `choice` (which option, counted from 0 in the order the part lists them), `correct` (the browser's grading) and `seconds`.

**After each click on a case:**

| Field | Meaning |
| --- | --- |
| `part_id` | Which case |
| `attempt` | 1 for the first try |
| `structure_id` | What was clicked |
| `point` | The exact point, `[x, y, z]` in the model's frame |
| `piece`, `at` | Where on the vessel; both `null` if the click was not on a vessel |
| `correct` | The browser's grading |
| `seconds` | Time from the case appearing to the click |

## How a click is graded

A click is correct if either holds:

- its `piece` matches a region of the answer and its `at` lies between `from - tolerance` and `to + tolerance`;
- its structure is in the answer's `structures`.

If it is not correct, the first near miss that contains it supplies the feedback; otherwise `feedback.wrong` does.

## What the check catches

`checkSession` in `format.ts` returns every problem it finds, each with the path to the field. It checks:

- the shape of every field;
- that every structure id, group id and piece id exists on the loaded model;
- that every distance lies on its piece, and every region runs forwards;
- that a pulse's end lies beyond its start;
- that a slider starts on its track;
- that a case has an answer, and no near miss overlaps it;
- that a multiple-choice question has two to five options, all different, exactly one of them right;
- that plan items point to real parts of the same kind, and part ids are unique.

It does **not** check that an article exists (the articles file is not loaded in the browser), that a case has only one defensible answer, that the anatomy is right, or that the thing a part talks about can be seen in its view. Those are for the backend and the agent's own checks.

## Requests

Built on the backend in `backend/app/sessions.py`. A session's parts come from one of two places, set by `SESSION_SOURCE` in `.env`: `sample` (the default) hands out the hand-written sample part by part, and `agent` has the session agent build them with Claude. The requests and replies are the same either way. All bodies are JSON.

| Request | Body | Reply |
| --- | --- | --- |
| `POST /api/sessions` | `request` (what the student asked for), `notes`: `null`, or `{filename, data}` with the PDF base64-encoded, and optionally `progress_key`: any string the browser makes up, to ask about progress before the session has an id | The start fields |
| `POST /api/sessions/{id}/reply` | `text`: the student's answer to the tutor's question | The start fields, or another question. A 409 if the tutor isn't waiting for an answer |
| `POST /api/sessions/{id}/chat` | `text`; `selected`: structure ids selected on the model; `part_id`: the part on screen, or `null` | `{statements, point_to, plan, plan_changed}`: the tutor's answer as sourced Statements, structure ids for the browser to select, and the current plan. A 409 before the plan, or from the sample |
| `POST /api/sessions/{id}/next` | None | `{part, plan, done}`: the next part and the current plan, or `part: null` with `done: true` when there are no more |
| `POST /api/sessions/{id}/answers` | An answer, as above: a click or a pick | `{plan}`: the current plan, which the agent may have changed |
| `POST /api/sessions/{id}/finish` | None | The summary |
| `GET /api/sessions/{id}` | None | What the backend holds: the request, where its parts come from, the notes' file name and size, how many parts were sent, every answer, any parts the agent gave up on, how many requests and tokens the session has used, and `timings`: for each recent request to Claude, its task, how long Claude took, how long the backend's own work on the reply took, and what came of it (lookups, a hand-in accepted or rejected). For checking, not for the student |
| `GET /api/sessions/progress/{key}` | None | `{working}`: what the tutor is doing now, each `{stage, doing, detail, seconds}`, e.g. doing "Building “Name the artery”" and detail "Reading the atlas page on Ventricle (heart)". `key` is a session id, or the `progress_key` of a start still running. Empty when nothing is under way or the key is unknown. The browser asks every second while it waits |
| `GET /api/tutor` | None | `{source}`: `sample` or `agent`, so the app can tell the student what to expect |

- `next` gets a 409 while the tutor is waiting for an answer to its question.
- An unknown session id gets a 404. Sessions are saved to `data/lumen.db` after every request that changes them, so they survive a restart and can be carried on another day. One left untouched for 30 days (`SESSION_DAYS`) is deleted. A session saved in a format this backend can no longer read gets a 410.
- Parts being built ahead of the student are not saved; after a restart the next part is built when it is asked for, so that one takes longer. The PDF of notes is not kept either: only the facts read from it, and the text of each page so the agent can search and quote them later.
- `finish` keeps the summary: asking again returns it without calling Claude.
- When the agent or the Claude API fails, the reply is a 502 with the reason in words. The browser shows it and offers to try again.
- Notes must be a PDF of at most 20 MB; anything else gets a 422 or a 413.
- An answer must be for a case or question the session has already been sent, and a pick must name one of the question's options, or it gets a 422. After a case or question with a wrong answer, the agent may add one part before the rest: never after a part it added itself, never after the plan's last part (the summary comes next), and at most two in a session. It decides as soon as the right answer arrives, and builds that part straight away, so it is ready when the student asks for the next part; if the answer was shown or skipped instead, it decides when `next` is called.
- The backend's models (`backend/app/session_schemas.py`) check shape. `backend/app/session_check.py` checks that every id, piece and distance exists on the model, as the browser does, and also that each atlas source names a real article with its own link, which the browser cannot do. The agent runs it on every part it builds, before the part can be sent.

The notes travel as base64 inside JSON, not as a file upload, so the backend needs no extra package and the body is already in the form the Claude API takes a PDF in.

## About the sample

`assets/fixtures/sessions/coronary_arteries.json` was written by hand to exercise the format: one part of each kind on the coronary arteries. Its statements cite real atlas articles, and its distances were measured on the model (the first septal branch leaves the anterior interventricular artery at 46.5 mm). Its views and `hide` lists were chosen by testing in the viewer which side shows each artery. It has **not** been reviewed by anyone with medical training and is not teaching material.

## Open questions

- **Whether a part's subject can be seen** is not guaranteed by the format. Playing the sample showed it: from the front, the first 46 mm of the anterior interventricular artery is behind the left atrium and the right ventricle, so the case's answer could not be clicked. The backend now sees to it before a part is sent: `choose_view` in `backend/app/measure.py` casts sight lines through the shapes from where the viewer's camera would stand, and picks the side and what to hide so enough of the subject shows (90% of a case's answer, 60% of a slider's track, half a pulse's route, 30% of what a demonstration highlights). Every part the agent sends has a `side`. It answers for the part's opening view, not for every angle the student could turn to.

- **Talking mid-session** goes through `/chat`. The tutor answers with statements checked like a part's, and when the student asks to go another way it replaces every part not yet given. Its answer can select structures but can't yet move the camera, hide things or run a pulse.
- **Notes sources** need the backend to say how a page is identified when the upload is slides rather than pages.
- **Painting in a demonstration.** A demonstration can highlight whole structures only. Marking a stretch of a vessel in one would need a `marks` field.
- **Whether the correct region should reach the browser at all.** Sending it lets the browser grade instantly, and also lets a curious student find it in the page. For a study tool that seems acceptable.
