# Session format

**Status: proposal (2026-11-14), version `lumen.session/0.1`. Not yet agreed by both of us.** It is shared between the browser and the backend, so neither side should change it alone.

A study session is a back-and-forth. The browser sends the student's request and, later, their clicks. The backend sends a plan, then one part at a time, then a summary. This page describes that data. It does not describe how the backend stores a session or what it gives the agent.

- Types and the check: `frontend/src/session/format.ts`
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
| `atlas` | `article`, `url` (or `null`) | The article's name, linked |
| `web` | `title`, `url` | The page's title, linked |
| `model` | none | "Measured on the model" |

`article` is a `key` in `assets/text/z_anatomy_articles.jsonl`, and `url` is that article's `source_url`.

**View** names what to look at, not where the camera is. `look_at` is a list of structure ids to frame. `side` is `anterior`, `posterior`, `left`, `right`, `superior`, `inferior`, or `null` to let the viewer pick a side from which they can be seen. The agent cannot know camera coordinates; the viewer can work them out.

## Parts

Every part has these fields:

| Field | Meaning |
| --- | --- |
| `id` | Unique within the session |
| `kind` | `demonstration`, `pulse`, `damage_slider` or `click_case` |
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

For a `click_case`:

- `answer` is a Target plus `tolerance`: how far past the end of a region a click still counts, in metres.
- `feedback.correct` and `feedback.wrong` are Statements.
- `feedback.near_misses` is a list of Targets, each with its own `statement`, for wrong places that deserve a specific explanation. A near miss may not overlap the answer.

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

**For each part:** one part, in the shape above. The plan may be sent again if it changed.

**At the end:** `summary`, with `solid` and `shaky` (lists of short sentences) and `sources` (every source used).

A **recorded session** is all of this in one file: the start fields, plus `parts` (the list of parts) and `summary`. The sample is one. The player can run a recorded session with no backend.

## What the browser sends

**At the start:** the student's request as text, and optionally their notes as a PDF.

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
- that plan items point to real parts of the same kind, and part ids are unique.

It does **not** check that an article exists (the articles file is not loaded in the browser), that a case has only one defensible answer, that the anatomy is right, or that the thing a part talks about can be seen in its view. Those are for the backend and the agent's own checks.

## Proposed requests

These are suggestions for the backend side, to be settled together.

| Request | Body | Reply |
| --- | --- | --- |
| `POST /api/sessions` | The request text and the notes file | The start fields |
| `POST /api/sessions/{id}/next` | Nothing | One part and the current plan, or a flag that the session is finished |
| `POST /api/sessions/{id}/answers` | An answer, as above | The plan, if it changed |
| `POST /api/sessions/{id}/finish` | Nothing | The summary |

## About the sample

`assets/fixtures/sessions/coronary_arteries.json` was written by hand to exercise the format: one part of each kind on the coronary arteries. Its statements cite real atlas articles, and its distances were measured on the model (the first septal branch leaves the anterior interventricular artery at 46.5 mm). Its views and `hide` lists were chosen by testing in the viewer which side shows each artery. It has **not** been reviewed by anyone with medical training and is not teaching material.

## Open questions

- **Whether a part's subject can be seen.** Playing the sample showed that this cannot be assumed: from the front, the first 46 mm of the anterior interventricular artery is behind the left atrium and the right ventricle, so the case's answer could not be clicked. Only the viewer can test this, by casting rays from the camera. The agent's check step will need to ask the viewer, or the backend will need its own copy of the shapes.

- **Asking a question mid-session** ("point and ask") has no request yet.
- **Notes sources** need the backend to say how a page is identified when the upload is slides rather than pages.
- **Painting in a demonstration.** A demonstration can highlight whole structures only. Marking a stretch of a vessel in one would need a `marks` field.
- **Whether the correct region should reach the browser at all.** Sending it lets the browser grade instantly, and also lets a curious student find it in the page. For a study tool that seems acceptable.
