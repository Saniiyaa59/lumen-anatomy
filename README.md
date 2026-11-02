# Lumen

> **Placeholder draft**

Lumen is an agentic 3D anatomy tutor. Students explore a 3D heart, click one or several structures, and type or speak about them: "Why is this wall so thick?" or "How does blood get from here to there?" An AI agent resolves what "this" and "there" refer to, then acts directly in the 3D scene, with answers grounded in an open anatomy textbook.

Built for CS598 Agentic AI (BU, Fall 2026), Application track.

## Status

Early development. This repo currently contains only the implementation plan, so everything below describes the intended design rather than working software.

## Planned features

- **3D heart viewer:** about 15–18 labeled structures, with rotate, zoom, hover highlight, layers, undo and reset.
- **Multi-select with chips:** click to select, Shift-click to add, with selection order preserved.
- **Reference resolution:** "this", "these", "here" and "there" map to the clicked structures. Ambiguous references produce a clarifying question instead of a guess.
- **Scene actions:** the agent can highlight, isolate, label, move the camera, change layers and animate blood flow.
- **Guided walkthroughs:** one command becomes a multi-step sequence with Next and Back.
- **Cited answers:** textbook search is filtered to the referenced structures, and answers cite the passages they rely on.
- **Reusable toolbar:** Explain, Compare, Show path, Isolate and Quiz me on these.
- **Click-based quizzes:** "Click the mitral valve" is graded by the click, and later quizzes target past mistakes.
- **Push-to-talk voice:** hold Space to speak while clicking, with word timestamps matched to click times.
- **Later additions:** cross-sections, notes pinned to structures by the student or the agent, and an MCP server that lets external agents author lessons.

## Architecture

The browser handles the 3D scene, and all mouse interaction stays local, so it never waits on the LLM. Commands go to `POST /api/command` on the backend, which:

1. Transcribes speech, for voice commands.
2. Resolves references to concrete structure IDs.
3. Runs one LLM agent with tools for scene actions, retrieval, quizzes, memory and notes.
4. Returns an answer, citations and an `actions[]` list for the browser to execute in order.

Scene tools don't run on the backend. Their arguments are validated against the structure registry (`assets/structures.json`) and recorded as actions, and invalid calls go back to the LLM as tool errors so it can correct itself.

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Vite, TypeScript, Three.js |
| Backend | Python 3.11+, FastAPI, Pydantic |
| LLM | Anthropic Claude with tool use |
| Speech-to-text | Whisper with word-level timestamps |
| Retrieval | `sentence-transformers` embeddings, FAISS |
| Storage | SQLite |
| External agents | MCP Python SDK |
| Testing | `pytest`, Playwright |

## Setup

Setup instructions will go in `docs/dev_setup.md` once there is something to run.

## Evaluation

The main question is whether clicking plus language beats language alone, especially for small, hard-to-name structures. Planned evaluations cover reference resolution, command understanding, filtered versus text-only retrieval, answer and citation accuracy, a screenshot baseline against a general vision model, and a small user pilot.

## Team

<!-- Add every member's name and UID. -->

## Attribution

- **3D models:** Z-Anatomy, derived from BodyParts3D (CC BY-SA 4.0, license to be verified at download).
- **Text:** OpenStax *Anatomy and Physiology 2e* (CC BY 4.0).

Lumen is an educational prototype. It does not give medical advice.
