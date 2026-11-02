# Lumen — Implementation Plan (v2)

**Lumen: an agentic 3D anatomy tutor.** Students explore a 3D heart, click one or several structures, and talk or type about them ("Why is this wall so thick?", "How does blood get from here to there?"). An AI agent resolves what "this" and "there" mean, then acts directly in the 3D scene — highlighting, isolating, labeling, moving the camera, slicing, animating blood flow, walking through processes step by step — with answers grounded in an open anatomy textbook. It also runs click-based quizzes that remember mistakes, and both the student and the agent can pin notes to structures.

- Repo: `lumen-anatomy`
- Course: CS598 Agentic AI (BU, Fall 2026), Application track, team of 2
- Version 2 adds: multi-select with selection chips, reference resolution ("this / here / there"), a reusable command toolbar, `isolate` and `animate_path`, push-to-talk voice, anchored notes, the click vs no-click evaluation, related work (DirectGPT and others), and the handout's deliverable rules.

---

## 0. Instructions for Claude Code

- Build in the **phases below, in order**. Each phase ends in a working, testable state. Don't start a phase until the previous one runs.
- Small commits, one feature each, with clear messages.
- When something isn't specified (a library version, a file name), pick the simplest standard option and record it in `docs/decisions.md`.
- **Ask before** adding a major dependency, changing the action protocol (Section 10.2), or changing the structure-ID scheme (Section 7.2).
- Never commit API keys. Use `.env` (gitignored) and `.env.example`.
- Write `pytest` tests for backend logic (registry, reference resolution, actions, retrieval, quiz, memory, notes). Frontend: a manual checklist per phase in `docs/test_checklist.md`.
- **Do not write or edit `README.md`.** The course requires the README to be written by the team, not by AI. Put developer setup notes in `docs/dev_setup.md` instead. Code comments and docstrings are fine.
- Mouse + keyboard and typed commands come first; push-to-talk voice is Phase 6. **Hand gestures are a stretch goal** — don't build them unless everything else works.

---

## 1. Goals, delta, and deadlines

### 1.1 What makes Lumen more than a chatbot

The course requires a clear delta over asking a general-purpose agent directly. Lumen's delta:

1. **Multi-reference commands:** "from here to there", "compare this and this", "hide everything except these" — references resolved to clicked structures.
2. **The agent acts in the 3D scene** through tools (highlight, isolate, label, camera, layers, cross-section, path animation), not just text.
3. **Multi-step plans:** one command becomes a sequence of scene actions (guided walkthroughs), not a single reply.
4. **Selection-aware retrieval:** textbook search filtered to the referenced structures, with checkable citations.
5. **Spatial quiz with memory:** "Click the mitral valve," graded by the click; later quizzes target past mistakes.
6. **Anatomy as a shared, annotated artifact:** student and agent pin notes to structures.
7. **External agent access (MCP):** Claude/Codex can author lessons that play in Lumen.

### 1.2 Temporary limitation or lasting problem? (the handout asks this)

Mostly lasting. General agents will keep improving at anatomy facts and image recognition, so part of the identification advantage may shrink. But they still won't control this 3D model, resolve "this" and "there" to structures on screen, ground answers in a chosen textbook with checkable citations, or track a student's weak spots in space. Those needs come from the interface and the learning workflow — and the structured tool layer is also what lets future, more capable agents use Lumen (via MCP) instead of guessing at pixels.

### 1.3 Deadlines and deliverables (from the handout)

| Item | Requirement |
| --- | --- |
| Team registration | Sun, Nov 1, 2026, 23:59:59 ET (done) |
| Working system | Target Nov 18 |
| Team presentation | Final two weeks of class (Nov 30–Dec 10 window; date announced later). ~8 min + 5 min Q&A, all members on stage. **A live demo is expected**; a recorded video only if live isn't practical. |
| Final ZIP | Sun, Dec 13, 2026, 23:59 ET, submitted by one member through the Slack course agent. Source code + experimental results or demo evidence, every member's name and UID. |
| Report / README | No formal report. README optional, **must be written by the team, not AI-generated**, covering what an AI reader couldn't infer from the code. |
| Grading | Presentation 10, ZIP 10, reviewing other teams 5 (individual), up to 5 bonus from audience ratings. Presentation scored on the strongest of novelty, importance, accomplishment, clarity. |

---

## 2. Related work and positioning

Put this in `docs/related_work.md`. **Verify each claim before using it in slides.**

- **DirectGPT** (Masson et al., CHI 2024, Module 3c): direct manipulation — selecting objects to scope a prompt, referring to objects by clicking, a toolbar of reusable prompts, undo — made people faster with fewer, shorter prompts than ChatGPT for editing text, code and vector images. Lumen applies these principles to a 3D anatomy model; unlike DirectGPT's single prompt per action, Lumen turns clicks + language into a multi-step agent plan with cited answers.
- **"Put-That-There"** (Bolt, 1980): combined speech with pointing; "this" and "there" are blanks filled by pointing.
- **AssistVR** (Chen, Grubert & Kristensson, 2024): LLM-assisted speech + pointing beat a baseline for selecting multiple 3D objects in VR, especially objects hard to describe in words — like small anatomy structures.
- **Existing anatomy apps and AI atlases:** click/touch 3D atlases (Complete Anatomy, Visible Body, Human Body Atlas, etc.); some AI atlases (teammate notes: OpenHuman Atlas, Anatria-3D — **verify what they do**) reportedly let you select one structure and ask, or have an assistant move the camera. There is also a **ChatGPT app, "Explore human anatomy in 3D" — check what it can do** and position against it explicitly.

**Positioning statement:** Lumen's delta is commands that refer to several clicked structures, multi-step agent actions in response, a spatial quiz with memory, anchored notes, external-agent access, and measured evidence that clicking + language beats language alone.

---

## 3. Scope

**MVP (must have, target Nov 18)**

- One organ: the heart, ~15–18 labeled structures
- Mouse: drag to rotate, scroll to zoom, hover highlight, click to select, Shift-click to add, selection chips with ×
- Layer buttons; undo; reset view
- Typed command box (always available, also the live-demo fallback)
- Reference resolution for "this / these / here / there / that" from the selection
- Reusable command toolbar: Explain, Compare, Show path, Isolate, Quiz me on these
- Agent with scene tools: highlight, isolate, label, camera views/focus, layers/visibility, path animation
- Selection-aware RAG over OpenStax *Anatomy and Physiology 2e* with citations
- Guided walkthroughs (multi-step plans with Next/Back)
- Click quiz with session memory
- Push-to-talk voice (hold Space) with word timestamps and click timing

**High-value additions (after MVP, by ~Nov 25)**

- Cross-sections (named cuts, capping)
- Anchored notes (student and agent)
- MCP server with lesson authoring
- Full evaluation harness

**Stretch (only if time allows)**

1. Deployment
2. Wake word as an alternative to push-to-talk
3. Voice disambiguation ("the mitral or the aortic valve?")
4. LLM-based reference resolution compared with rule-based
5. Hand-gesture mode (MediaPipe) feeding the same selection events
6. Second organ (lungs, connected via pulmonary circulation)

**Non-goals:** training or fine-tuning; multiple agents (one agent with tools); patient data; medical advice.

---

## 4. Architecture

```
┌─────────────────────────── Browser (frontend) ───────────────────────────┐
│ Three.js viewer ── ray-cast picking ── selection state + chips            │
│   ▲                                    │   (click events with timestamps)  │
│   │ executes actions                   ▼                                    │
│ Action executor ◄── actions[] ── Command box / toolbar / push-to-talk ─────┼─► POST /api/command
│ Walkthrough player · Quiz UI · Notes layer                                 │
└──────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────── Backend (FastAPI) ────────────────────────────┐
│ Speech-to-text (Whisper, word timestamps)  [voice commands only]           │
│ Reference resolution (rule-based; LLM fallback for ambiguity)              │
│ Agent loop (one LLM with tool calling)                                     │
│   ├─ scene tools  → validated and collected into actions[]                 │
│   ├─ retrieve()   → FAISS index, chunks tagged by structure                │
│   ├─ quiz + memory + notes tools → SQLite                                  │
│   └─ registry tools → structures.json                                      │
│ MCP server (same tools, for external agents)                               │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key design decisions**

- **Scene tools don't run on the backend.** When the LLM calls a scene tool, the backend validates arguments, records an action, and returns "ok" to the LLM. The response carries `actions[]`, which the frontend executes in order.
- **Mouse interactions never wait on the LLM.** Rotation, zoom, hover, selection are all local.
- **Reference resolution happens before the agent**, so the agent receives concrete structure IDs; ambiguity produces a clarification question rather than a guess.

---

## 5. Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Vite + TypeScript, Three.js (`GLTFLoader`, `OrbitControls`, `Raycaster`, `CSS2DRenderer`) |
| UI | Plain TypeScript + minimal CSS (or light React if preferred) |
| Voice capture | `MediaRecorder` push-to-talk; optional Silero VAD |
| Backend | Python 3.11+, FastAPI, Pydantic |
| Speech-to-text | Whisper with word-level timestamps (e.g. `faster-whisper` locally, or a hosted Whisper API) |
| LLM | Anthropic Claude via the official SDK with tool use; model ID from env; provider adapter in `llm.py` |
| Embeddings | `sentence-transformers` (e.g. `BAAI/bge-small-en-v1.5`), local |
| Vector index | FAISS (flat) |
| Storage | SQLite |
| MCP | Official MCP Python SDK |
| Tests / eval | `pytest`; Playwright for screenshot-baseline rendering |

---

## 6. Repo structure

```
lumen-anatomy/
├── README.md                 # written by the team only — Claude Code must not edit
├── .env.example
├── docs/
│   ├── dev_setup.md          # how to run things (Claude Code may write this)
│   ├── decisions.md
│   ├── asset_prep.md
│   ├── related_work.md
│   ├── attribution.md
│   └── test_checklist.md
├── assets/
│   ├── models/heart.glb
│   └── structures.json       # single source of truth
├── data/
│   ├── raw/openstax/
│   ├── tag_overrides.json
│   ├── chunks.jsonl
│   ├── index/
│   └── lumen.db
├── frontend/src/
│   ├── main.ts
│   ├── viewer/               # scene, camera, picking, highlight, labels, clipping, paths, notes layer
│   ├── selection/            # selection state, chips, timestamped click log
│   ├── actions/              # action executor (one handler per action type)
│   ├── ui/                   # command box, toolbar, walkthrough player, quiz, notes panel
│   ├── voice/                # push-to-talk recorder
│   └── api.ts
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── agent.py
│   │   ├── llm.py
│   │   ├── prompts.py
│   │   ├── resolution.py     # reference resolution
│   │   ├── speech.py         # Whisper wrapper
│   │   ├── actions.py        # action schemas + validation
│   │   ├── registry.py
│   │   ├── db.py
│   │   └── tools/            # scene.py, retrieval.py, quiz.py, memory.py, notes.py, walkthrough.py
│   ├── scripts/              # validate_glb.py, build_chunks.py, build_index.py
│   ├── mcp_server.py
│   └── tests/
└── eval/
    ├── datasets/
    ├── run_resolution_eval.py
    ├── run_command_eval.py
    ├── run_click_vs_noclick_eval.py
    ├── run_retrieval_eval.py
    ├── run_answer_eval.py
    ├── run_screenshot_baseline.py
    ├── run_walkthrough_eval.py
    ├── pilot_protocol.md
    └── results/
```

---

## 7. Phase 0–1 — Setup, heart model, registry

### 7.1 Phase 0: setup

- Repo skeleton, `.gitignore`, `.env.example`, `docs/dev_setup.md`.
- Frontend: Vite + TypeScript rendering a cube with OrbitControls.
- Backend: FastAPI with `GET /api/health`, CORS for the dev server.

**Done when:** both servers start and the page renders.

### 7.2 Phase 1: model and registry

**Asset prep** (manual, documented in `docs/asset_prep.md`): Z-Anatomy Blender atlas (based on BodyParts3D; CC BY-SA 4.0 — verify license at download). Isolate heart structures, keep each as a separate named object, decimate to keep `heart.glb` under ~10 MB, export glTF binary.

**Target structures:** right atrium, left atrium, right ventricle, left ventricle, interventricular septum, tricuspid valve, mitral valve, pulmonary valve, aortic valve, aorta, pulmonary trunk, superior vena cava, inferior vena cava, pulmonary veins, right coronary artery, left coronary artery, myocardium; pericardium optional. Adjust to what the model contains.

**`assets/structures.json`:**

```json
{
  "organ": "heart",
  "structures": [
    {
      "id": "left_ventricle",
      "display_name": "Left ventricle",
      "mesh_names": ["Left_ventricle"],
      "aliases": ["LV", "left ventricle"],
      "group": "chamber",
      "layer": "chambers",
      "size_class": "large",
      "best_view": "anterior_left",
      "neighbors": ["mitral_valve", "aortic_valve", "interventricular_septum"],
      "short_description": "Pumps oxygen-rich blood into the aorta."
    }
  ],
  "views": {
    "anterior": {"position": [0, 0, 3], "target": [0, 0, 0]}
  },
  "cross_sections": {
    "four_chamber": {"normal": [0, 0, 1], "default_position": 0.5},
    "short_axis": {"normal": [0, 1, 0], "default_position": 0.4}
  },
  "paths": {
    "blood_flow": {
      "sequence": ["superior_vena_cava", "right_atrium", "tricuspid_valve", "right_ventricle",
                   "pulmonary_valve", "pulmonary_trunk", "pulmonary_veins", "left_atrium",
                   "mitral_valve", "left_ventricle", "aortic_valve", "aorta"],
      "control_points": "authored per structure in Phase 5"
    }
  }
}
```

`size_class` (small/medium/large) is used to break down evaluation results by structure size.

**`backend/scripts/validate_glb.py`:** lists GLB mesh names; reports registry entries without meshes and meshes without registry entries.

**Frontend:** load, center and scale the GLB; build `meshName → structureId`.

**Week-1 risk checks:** (1) `validate_glb.py` reports zero missing structures; (2) apply one clipping plane and inspect the cut (hollow meshes → plan capping).

---

## 8. Phase 2 — Viewer, selection, and toolbar shell (no AI yet)

All functions live on a scene controller (`viewer/controller.ts`) so the action executor can call them later.

- **Picking:** ray-cast on click → structure ID.
- **Hover highlight** (light tint) and **selection highlight** (stronger tint/outline).
- **Selection model:** click = select one (replace); Shift-click = add/remove; Esc = clear. **Selection chips** above the command box ("Left ventricle ×"), in selection order.
- **Click log:** every selection click recorded as `{t, structure_id}` with a high-resolution timestamp, kept for the current command.
- **Labels:** `CSS2DRenderer` labels anchored at a structure's center.
- **Camera:** smooth tween to named views; `focus(structure)` frames a structure.
- **Visibility:** show/hide/fade per structure and per layer; `isolate(structures)` hides everything else.
- **Layer buttons** and a **toolbar shell** (Explain, Compare, Show path, Isolate, Quiz me on these); buttons are disabled when the selection doesn't fit (e.g. Compare needs ≥2).
- **Undo / reset:** stack of scene snapshots (camera, highlights, visibility, clipping, labels, selection).

**Done when:** all of the above work by mouse and via the controller from the console; Isolate works without AI.

---

## 9. Phase 3 — Knowledge base (RAG)

**Source:** OpenStax *Anatomy and Physiology 2e*, heart chapter ("The Cardiovascular System: The Heart"), CC BY 4.0; keep the URL of every chunk.

- `build_chunks.py`: HTML → clean text by section; ~150–300-word chunks; tag each chunk with structure IDs by matching `display_name` + `aliases` (word boundaries), plus manual overrides from `data/tag_overrides.json`.
- `chunks.jsonl` record: `{"chunk_id", "section", "text", "structure_ids", "source_url"}`.
- `build_index.py`: embed with sentence-transformers, build FAISS index.
- `retrieve(query, structure_ids=None, k=4, mode="filtered" | "text_only")`: filtered mode restricts to chunks tagged with any referenced structure (optionally neighbors), ranks by similarity, falls back to unfiltered if <2 results.

**Done when:** tests show filtered retrieval returns left-ventricle passages for "why is this wall so thick?" with `["left_ventricle"]`.

---

## 10. Phase 4 — Reference resolution and the agent (typed commands)

### 10.1 Endpoint

`POST /api/command`

```json
{
  "session_id": "abc123",
  "input_type": "text",
  "text": "How does blood get from here to there?",
  "audio": null,
  "click_events": [{"t": 41.2, "structure_id": "right_atrium"},
                   {"t": 42.0, "structure_id": "aorta"}],
  "selection": ["right_atrium", "aorta"],
  "toolbar_command": null,
  "scene_state": {"view": "anterior", "visible_layers": ["chambers", "valves", "vessels"],
                  "highlighted": [], "cross_section": null},
  "mode": "explore"
}
```

Response:

```json
{
  "transcript": null,
  "resolved_refs": {"here": "right_atrium", "there": "aorta"},
  "clarification": null,
  "answer": "Blood leaves the right atrium through the tricuspid valve ...",
  "citations": [{"chunk_id": "19.1-p05", "section": "19.1 Heart Anatomy", "source_url": "..."}],
  "actions": [{"type": "animate_path", "path": "blood_flow", "from": "right_atrium", "to": "aorta"}],
  "walkthrough": null
}
```

### 10.2 Reference resolution (`resolution.py`)

Deictic words: `this, that, these, those, here, there`, plus "this one / that one".

**Typed commands (rule-based):**

1. Find deictic words in order.
2. If the count of singular deictics ≤ selection size, assign selected structures **in selection order** ("here" → 1st chip, "there" → 2nd).
3. "these / those" → the whole selection.
4. No selection and a deictic word → `clarification: "Click the structure you mean."`
5. Mismatch (e.g. "this and this" with one selection) → clarification.

**Voice commands (Phase 6):** match each deictic word to clicks by **order first, time second** — the nearest click within a window (e.g. −1.5 s to +1.0 s of the word); fall back to the selection; clarify if still ambiguous.

**LLM fallback (stretch, also an eval condition):** pass transcript + click events to the LLM to resolve references; compare with rules.

Unit-test every rule with fixtures.

### 10.3 Action protocol (`actions.py`, Pydantic-validated)

| Action | Fields |
| --- | --- |
| `highlight` | `structure_ids[]`, `color` ("primary" \| "secondary" \| "correct" \| "wrong"), `exclusive` |
| `clear_highlights` | — |
| `isolate` | `structure_ids[]` |
| `label` | `structure_id`, `text` (≤ 40 chars) |
| `clear_labels` | — |
| `set_view` | `view` (registry name) |
| `focus` | `structure_id` |
| `set_visibility` | `structure_ids[]` or `layers[]`, `visible` |
| `fade_others` | `structure_ids[]` |
| `animate_path` | `path` (registry), `from`, `to` |
| `cross_section` | `section` (registry name), `position` (0–1) |
| `clear_cross_section` | — |
| `add_note` | `structure_id`, `text`, `author` ("agent") |
| `set_selection` | `structure_ids[]` |
| `reset_view` | — |

Unknown structure IDs, views, sections or paths are rejected and returned to the LLM as tool errors so it can correct itself.

### 10.4 Tools available to the LLM

- **Scene tools** (become actions): all of 10.3.
- **Backend tools:** `retrieve(query, structure_ids?)`, `lookup_structure(name)` (fuzzy alias match), `list_structures(group?)`, `get_path(path, from, to)`, `create_walkthrough(title, steps[])`, quiz/memory/notes tools (Phase 5, 7).

### 10.5 Toolbar commands

Each button sends a structured request on the current selection, e.g. `toolbar_command: "compare"` with two selected structures. The backend turns it into a templated instruction ("Compare these structures: {names}") and runs the same agent loop. This keeps toolbar and free-form commands consistent and shows the DirectGPT "reusable command" principle.

### 10.6 Agent loop (`agent.py`)

1. Resolve references (10.2); if `clarification`, return it immediately.
2. Build messages: system prompt + last ~6 turns + current command with resolved structure IDs, selection, and scene state.
3. Call the LLM with tools; loop while it requests tools (max ~8 iterations).
4. Run backend tools; validate and record scene tools.
5. Return `{resolved_refs, answer, citations, actions, walkthrough}`.

### 10.7 System prompt (draft, `prompts.py`)

```
You are Lumen, an anatomy tutor that teaches by acting in a 3D heart model.

- References like "this", "here" and "there" have already been resolved to structure IDs;
  use those IDs. Never guess a structure the student didn't name or select.
- Ground every factual claim in passages from `retrieve` and cite them as [chunk_id].
  If retrieval finds nothing relevant, say the topic isn't covered in your sources.
- Show what you explain: highlight or isolate the structures you discuss, move the camera so
  they're visible, and label them. Use a cross-section when the inside matters.
- For a path or process ("from here to there", blood flow, valve sequence), animate the path
  or create a walkthrough of 3-8 steps, each with scene actions and 1-2 sentences of narration.
- For comparisons, show both structures (highlight in two colors) and contrast them briefly.
- Use only IDs, views, sections and paths that exist in the registry tools.
- Keep answers to 2-4 sentences outside walkthroughs.
- Teach anatomy only. Don't give medical advice or interpret personal symptoms; suggest
  asking a healthcare professional.
```

**Done when:** Shift-clicking the right atrium and aorta and typing "How does blood get from here to there?" animates the path and returns a cited answer; "What's the difference between this and this?" with two valves highlights both in two colors and compares them; "Hide everything except these" isolates the selection; "Where is the mitral valve?" with nothing selected finds and shows it.

---

## 11. Phase 5 — Walkthroughs, path animation, quiz and memory

### 11.1 Walkthroughs

```json
{
  "walkthrough_id": "wt_blood_flow_01",
  "title": "Blood flow through the heart",
  "created_by": "lumen",
  "steps": [
    {
      "narration": "Oxygen-poor blood enters the right atrium from the superior and inferior vena cava.",
      "actions": [
        {"type": "set_view", "view": "anterior"},
        {"type": "highlight", "structure_ids": ["superior_vena_cava", "inferior_vena_cava", "right_atrium"], "exclusive": true}
      ],
      "citations": ["19.1-p05"]
    }
  ]
}
```

Player: step counter, Next/Back, narration, executes each step's actions; Back restores the previous step's snapshot. Walkthroughs are stored in SQLite and replayable.

### 11.2 Path animation

- Author control points for the `blood_flow` path (a point at each structure's center, plus intermediate points so the curve stays inside chambers/vessels).
- `animate_path(path, from, to)` animates particles or a glowing tube along the sub-sequence between `from` and `to`, highlighting each structure as the flow passes it.
- Unknown order (e.g. `from` after `to`) → tool error explaining valid directions.

### 11.3 Quiz and memory

```sql
CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE views (session_id TEXT, structure_id TEXT, viewed_at TEXT);
CREATE TABLE quiz_attempts (session_id TEXT, structure_id TEXT, question_type TEXT,
                            answer_given TEXT, correct INTEGER, attempted_at TEXT);
CREATE TABLE walkthroughs (walkthrough_id TEXT PRIMARY KEY, title TEXT, json TEXT,
                           created_by TEXT, created_at TEXT);
CREATE TABLE notes (note_id TEXT PRIMARY KEY, session_id TEXT, structure_id TEXT,
                    point TEXT, text TEXT, author TEXT, created_at TEXT);
```

Tools:

- `quiz_next(session_id, scope_structure_ids?)` — prioritizes past mistakes, then unviewed structures, then random; "Quiz me on these" passes the selection as scope. Question types: `click_structure`, `name_structure`.
- `check_answer(session_id, question, answer)` — compares the clicked structure ID or matches the typed name against display name + aliases; records the attempt.
- `get_progress(session_id)` — viewed structures, accuracy per structure, weakest structures.

Quiz UI: question banner; clicks become answers; correct structure flashes green, a wrong pick red; summary at the end.

**Done when:** "How does blood flow through the heart?" plays a 5–8 step walkthrough; a 10-question quiz runs; the next quiz starts with missed structures; "Quiz me on these" stays within the selection.

---

## 12. Phase 6 — Push-to-talk voice

- **Frontend:** hold Space to record (`MediaRecorder`); the click log captures clicks made while recording, with timestamps relative to recording start. Show a "Listening…" indicator. Typed input always remains available.
- **Backend:** `speech.py` transcribes with **word-level timestamps**; `resolution.py` uses the voice rules (order first, time second, fallback to selection).
- Response includes `transcript` and `resolved_refs`; the frontend shows the transcript with resolved words linked to chips (e.g. "here" → Right atrium).

**Done when:** holding Space, saying "How does blood get from here to there?" while clicking the right atrium and then the aorta produces the same result as the typed version; latency (end of speech → first action) is logged.

---

## 13. Phase 7 — Cross-sections, anchored notes, MCP

### 13.1 Cross-sections

- Clipping planes by named section and position; stencil-buffer capping if cuts look hollow.
- Agent uses named sections only; walkthrough steps can move `position` between steps (tweened).

### 13.2 Anchored notes

- **Student notes:** right-click a structure (or a "Note" button with one structure selected) → type a note → saved with `structure_id` and the exact surface point from the ray-cast hit.
- **Agent notes:** `add_note(structure_id, text)` tool, limited to repeated quiz mistakes (e.g. after 2+ misses on the same structure) — the system prompt says so.
- **Display:** a small pin at the anchor point; the note shows on hover/click; pins behind the model are dimmed; a side panel lists all notes (filter: mine / Lumen's). Student and agent notes use different colors/icons.
- **Context:** the agent can read the student's notes for the referenced structures (`get_notes(structure_ids)`), e.g. "You noted earlier that…".

### 13.3 MCP server (`backend/mcp_server.py`)

Expose: `list_structures`, `lookup_structure`, `retrieve`, `create_lesson(title, steps[])` (saved as a walkthrough with `created_by="external_agent"`, returns a `/?lesson=<id>` link), `list_lessons`, `get_lesson`, `get_progress`. Frontend "Lessons" menu opens saved walkthroughs.

**Demo:** in Claude Desktop/Code with the MCP server configured: "Make a 5-step lesson on the four heart valves for a first-year student" → the lesson plays in Lumen.

---

## 14. Phase 8 — Evaluation

Central claim (following DirectGPT and AssistVR): **clicking while speaking/typing beats language alone, especially for small, hard-to-name structures**, and Lumen's tool layer gives more accurate, grounded, visible answers than a general agent.

All scripts write results to `eval/results/` and print summary tables.

| Eval | Dataset | Method | Metric |
| --- | --- | --- | --- |
| Reference resolution | ~50 recorded commands with clicks, incl. multi-reference ("from here to there", "this and this") and mistimed clicks | Rule-based (and LLM fallback, stretch) | % references resolved correctly; % clarifications |
| Command understanding | ~100 typed/spoken commands, tagged single- vs multi-step and named vs deictic | Run agent | % correct tool calls by category; % invalid actions |
| **Click vs no-click** | Same tasks done by naming structures only vs clicking + referring | Scripted runs (system) + pilot (people) | Task success, turns, time; by structure `size_class` |
| Selection-aware retrieval | ~50 structure-tied questions with gold chunk IDs | Filtered vs text-only | Recall@4, precision@4 |
| Answer accuracy | Same questions with reference answers | No RAG vs RAG; LLM-as-judge + manual sample | % correct, % unsupported claims |
| Citation support | All RAG answers | Judge each cited chunk vs its sentence | % supported |
| **Screenshot baseline** | ~40 structures rendered with a marker (Playwright) | General vision model given screenshot vs Lumen given the clicked ID | Identification + answer accuracy by size |
| Walkthrough / path correctness | ~15 process questions with expected structure sequences | Compare highlighted sequence per step | Sequence match; % invalid actions |
| Cross-section choice | ~20 questions with expected section | Check chosen section | % correct |
| Latency | All runs | Mouse interaction response; speech-to-first-action | ms; median/p90 s |

**User pilot (3–5 people)** — `eval/pilot_protocol.md`:

- Structure-finding and comparison tasks in two conditions: **Lumen with clicking + voice** vs **Lumen voice-only** (must name structures). Order swapped between participants.
- Optional: learning comparison (one organ section with Lumen vs a standard 3D viewer, then a 10-question quiz).
- After each condition: System Usability Scale + short interview. Report per participant; no significance claims. Check with the instructor whether approval is needed.

---

## 15. Testing checklist

- Backend unit tests: registry, alias lookup, resolution rules (typed + voice fixtures), action validation, retrieval filtering, path sub-sequences, quiz selection, memory, notes, walkthrough validation.
- Agent integration test with a mocked LLM returning scripted tool calls.
- Frontend manual checklist: picking on small structures, Shift-click order and chips, undo across agent actions, transparency, label positions, capping, note pins after rotation, push-to-talk click timing.

---

## 16. Configuration and deployment (later)

`.env.example`:

```
ANTHROPIC_API_KEY=
LLM_MODEL=
WHISPER_MODEL=small
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
DB_PATH=data/lumen.db
FRONTEND_ORIGIN=http://localhost:5173
```

Deployment (stretch, after local works): frontend on AWS Amplify (or S3 + CloudFront / Vercel); backend as one FastAPI container on App Runner with the FAISS index baked in; LLM via Anthropic API or Bedrock; Whisper in the container or a hosted API; SQLite → DynamoDB if needed. HTTPS required (browsers only allow the microphone on secure sites). Keys in env vars / Secrets Manager; billing alert and spend cap. Only audio (while Space is held) and selection events leave the browser.

---

## 17. Licensing and attribution (`docs/attribution.md`)

- 3D models: Z-Anatomy (CC BY-SA 4.0 — verify), derived from BodyParts3D; modified models shared under the same license.
- Text: OpenStax *Anatomy and Physiology 2e* (CC BY 4.0), linked per chunk.
- App footer attribution, and the disclaimer: "Lumen is an educational prototype. It does not give medical advice."

---

## 18. Presentation and ZIP

**Presentation (~8 min + 5 Q&A, live demo):**

- Lead with a multi-reference, multi-step command ("from here to there" → path animation + cited answer), then a comparison, a quiz, a note, and an MCP-authored lesson.
- Show the click vs no-click and screenshot-baseline results.
- Rehearse with the typed-command fallback; test the room's mic; keep a backup video.

**ZIP contents:** source code, `docs/`, `structures.json`, eval scripts + results, pilot protocol + anonymized results, demo video, every member's name and UID. README (optional) written by the team.

**Make clear in the README/slides (written by the team):**

- **What existed:** Three.js, Z-Anatomy models, OpenStax text, the LLM, Whisper, sentence-transformers, FAISS, the MCP SDK.
- **What we added:** selection + chips and reference resolution, the scene tool layer and action protocol, selection-aware retrieval, walkthroughs and path animation, cross-section teaching, the quiz with memory, anchored notes, MCP lesson authoring, and the evaluation.
- **Why one agent:** one agent with tools covers explanation, walkthroughs, quizzes and notes.
- **Why RAG:** grounding in a vetted source; selection filtering measurably improves retrieval.

---

## 19. Milestones

| Dates | Goal |
| --- | --- |
| Oct 26–30 | Week-1 tech test (done): model export, picking, clipping check |
| Nov 2–11 | Phase 2: viewer, selection + chips, click log, toolbar shell, undo |
| Nov 2–13 | Phases 3–4: RAG, reference resolution, agent + action protocol (typed) |
| Nov 13–18 | Phase 5–6: walkthroughs, path animation, quiz + memory, push-to-talk; **working system by Nov 18** |
| Nov 19–25 | Phase 7: cross-sections, anchored notes, MCP |
| Nov 19–27 | Phase 8: evaluations + pilot |
| Nov 24–29 | Slides, live-demo rehearsal, backup video |
| Nov 30–Dec 10 | Presentation (date TBA) |
| Dec 13 | Final ZIP via the Slack course agent |

## 20. Open questions

- [x] Final name: Lumen. (Teammate's doc still says Atlas.)
- [ ] Who owns the browser and backend workstreams?
- [ ] Which LLM, and who pays for it?
- [ ] Does the pilot need instructor approval?
- [ ] Presentation date in the Nov 30–Dec 10 window
- [ ] Verify related-work claims (OpenHuman Atlas, Anatria-3D, the ChatGPT 3D anatomy app)