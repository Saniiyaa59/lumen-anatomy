# User stories

**Status: draft 2 (Nov 14), for the team to review.** It replaces the feature list in the implementation plan as the description of what we're building. Items marked *decided* were settled in the Nov 10–14 design discussion; items marked *proposed* still need a yes from both of us.

## The product in one paragraph

A student says what they need to be ready for, and can upload their lecture notes. An agent builds a study session on a 3D anatomy model and runs it: it demonstrates on the model, poses "what if" cases, has the student answer by clicking the exact place, and changes its plan as it sees how the student does. Every fact it shows names its source.

## Decisions so far

| Topic | Decision | Status |
| --- | --- | --- |
| Headline | "Prepare me on X": the agent creates and runs a whole study session | Decided |
| Sources | The student's uploaded notes or slides first, then our textbook, then web search if those fall short | Decided |
| Reasoning over recall | Sessions centre on "what if" cases, not on naming structures or reciting blood flow | Decided |
| Clicking | Answers are clicked on the model and graded by exact place, which typing can't test | Decided |
| Animations | The agent arranges prepared building blocks. Writing new animations itself (write, render, look, fix) is the second step | Decided |
| "Show me X" | Plain code, no agent | Decided |
| Screenshots to a vision model | Not for identifying structures (we have exact data). Used in step 2 so the agent can judge how its own animation looks | Decided |
| Voice, pinned notes, lesson authoring by outside agents | Not now | Proposed |
| First topic | The radial nerve and the humerus | Proposed |
| Web search | Limited to an approved list of sites; can be switched off | Proposed |

## The headline story: "Prepare me on X"

> As a student with an exam coming, I tell the tutor what I need to be ready for, optionally upload my lecture notes, and get a study session on the 3D model that adjusts to how I'm doing.

1. **Ask.** The student types "prepare me on radial nerve injuries" and uploads the lecture's slides as a PDF.
2. **Scope.** The agent reads the slides, works out which structures and ideas they cover, and checks what the model and the text hold for each. It tells the student what it can show on the model and what it can only explain in words.
3. **Plan.** It shows a short plan, for example: the nerve's course, what is lost at each level of injury, three cases, one harder "what if". The student can change it.
4. **Build.** It prepares each part while the student works on the one before: what to show, where the camera goes, the question, and the answer key as an exact region on the model.
5. **Check.** Before a part is shown: is every claim backed by a passage? Does the question have exactly one correct region? Is the thing being shown visible?
6. **Run.** The student steps through the parts (see below), answers by clicking, and can interrupt with a question at any time.
7. **Replan.** The agent reads the answers. A student who keeps choosing the wrong segment gets a demonstration or an easier case; one who is doing well skips the review and gets a harder case.
8. **Close.** A summary of what was solid and what was shaky, with the sources used.

### Parts a session is made of

| Part | What the student sees | Step |
| --- | --- | --- |
| Demonstration | The model turns, hides what's in the way, highlights and labels, with a line or two of explanation and its source | 1 |
| Travelling pulse | A pulse runs along a nerve or vessel to show its course and branches | 1 |
| Damage slider | The student drags a damage point along a nerve or vessel; what is lost below it greys out | 1 |
| Click-where case | A short patient story; the student clicks where the problem is; graded by exact segment | 1 |
| Slice | A cut plane moves through the region | Later |
| Needle or probe | The student picks a spot and angle; the model reports what the path crosses | Later |
| Bone break | The bone parts at a clicked spot and the pieces shift | Later |
| Agent-written animation | The agent writes a new animation, renders it, looks at it and fixes it. Prepared ahead of the session, never live | 2 |

### Rules for sources

1. Every fact shows where it came from: the student's notes (with page), the textbook, or the web (with link).
2. If the notes and the textbook disagree, the notes win, and the agent says so. The exam follows the lecturer.
3. Web search is limited to approved sites, and what it returns is treated as information, never as instructions.
4. The agent may explain from any labelled source, but it only grades a click against facts it has checked against the model.

### What is the agent, and what is plain code

| The agent decides | Plain code does |
| --- | --- |
| What the notes cover and what matters in them | Reading files, searching the text |
| What to look up about the anatomy, and what to do when the text and the model disagree | Measuring the model: position along a nerve, nearest landmark, what's nearby, what's downstream |
| How to demonstrate each point, and how to fix a shot that doesn't work | Running the building blocks; checking visibility |
| What cases to write, and rewriting ones that fail its checks | Grading a click against the answer region |
| What a wrong answer means and what to do next | Recording attempts; a cap on session length |

**The check that keeps us honest:** compare the agent with a fixed template that uses the same building blocks filled in by rules. If the agent's sessions are no better, we say so.

## Supporting stories

### Explore the model — built

> As a student, I rotate and zoom the model, see what each part is called, and hide parts to see inside.

Built for the heart: hover, selection, labels, the structures panel, recentering.

### Point and ask, at any time — step 1

> As a student, I click a structure or a spot and ask about it in my own words, including in the middle of a session.

The system fills in "this" from the click, answers in a few sentences with a source, and shows the answer on the model. Inside a session, the agent then returns to the plan. Pointing here is a convenience: a student who knows the term could type it.

### "Show me X" — step 1, plain code

> As a student, I ask to see a structure and the model arranges itself so I can.

## How sessions adapt to different anatomy

The building blocks belong to kinds of structure, so any structure of that kind can use them.

| Kind | Blocks | Data in the model file |
| --- | --- | --- |
| Anything | Camera, highlight, hide, label, pull apart, slice | The shape |
| Tube-like (nerves, arteries, veins, ducts, airways) | Travelling pulse, colour a stretch, damage slider, "everything downstream" | 951 centre lines, with branching |
| Bones | Named spots, what attaches where, a break | 1,221 landmark lines, about 455 attachment areas |
| Muscles | Where each end attaches; an arrow for the direction of pull | Attachment areas |
| Layered regions | Needle path, "what's under here" | Checked on the upper arm only |

To show this works beyond one topic, prepare three different topics with the same automatic pipeline: a nerve with its bone, an artery tree, and one layered region.

## What we can't show

- **Soft tissue changing shape.** The model has no rigs or stored shape changes. No contracting muscles, opening valves or bending nerves. A beating heart or a "wrist drop" would be a stylised stand-in or a caption.
- **Topics that are about motion** (the cardiac cycle, breathing, joint movement) get static views and text.
- **Regions we haven't exported.** Preparing a region is automatic but happens ahead of time.
- **Clinical precision.** The model is one idealised body, right to about a centimetre where we measured. It teaches principles and must say it is not a clinical tool.

## Build order

**Step 1 — first working version**
- One topic end to end: the radial nerve and the humerus.
- Upload notes as PDF; textbook search; sources labelled.
- The session loop: scope, plan, build, check, run, replan, close.
- Four parts: demonstration, travelling pulse, damage slider, click-where case.
- Point and ask; "show me X".

**Step 2**
- A second and third topic through the same pipeline.
- Agent-written animations with the look-and-fix loop.
- Web search fallback.

**Later, if time allows:** slice, needle, bone break, uploading a picture to find it on the model.

**Not now:** voice, pinned notes, lesson authoring by outside agents.

## What step 1 needs built

| Piece | Side |
| --- | --- |
| Arm scene: export the humerus, its nerves and arteries, centre lines, landmarks and attachment areas | Frontend (export script, viewer) |
| Keep the exact click point; colour and grade a segment of a structure | Frontend |
| A player for session parts: demonstration, pulse, slider, click-where | Frontend |
| Session screen: plan, current part, feedback, summary, upload | Frontend |
| Structure list for the arm; facts table (branch levels, what is lost at each) with a human review | Backend, both to review |
| Measuring tools: position along a structure, nearest landmark, nearby, downstream | To decide |
| Reading uploaded PDFs; text search; answers with sources | Backend |
| The session agent: scope, plan, build, check, replan | Backend |
| Request and response format for sessions and click points | Agreed by both |

## Evaluation

- **Agent against a fixed template:** same building blocks, sessions built by rules. Compare with simulated students who have planted misconceptions, and with a few real students.
- **Name right, place wrong:** the same cases answered by typing and by clicking; count how often the name is right and the place is wrong.
- **Content checks:** share of generated cases with exactly one correct region; share of claims backed by their cited passage; a sample reviewed by our med-school contact.
- **Generality:** the three topics above, with no per-topic hand work.

## Open decisions

1. **Step 1 scope.** Is the list above the right first version?
2. **Student.** Undergraduate anatomy students or medical students? The case types come from medical school exams.
3. **Textbook.** OpenStax (vetted, coarse), the text built into the model file (from Wikipedia; fine-grained and matched to the model's names, not vetted), or both with the source labelled.
4. **The heart.** The viewer and structure list we built are for the heart. Keep it as a second topic (the coronary arteries suit "blocked here"), or set it aside?
5. **Dates.** The presentation window opens Nov 30. The old target of a working system by Nov 18 was for the old scope. What is the new one?
6. **Who builds what.** The session agent is the largest piece and sits on the backend.
