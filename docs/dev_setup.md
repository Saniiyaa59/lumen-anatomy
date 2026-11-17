# Developer setup

Works on macOS and Windows. The only difference is how you activate the Python virtual environment.

## Prerequisites

- Node.js 22+ (npm 10+)
- Python 3.11+ (developed on 3.13). On macOS: `brew install python@3.13 node`
- Git

## First-time setup

From the repo root:

```bash
cp .env.example .env        # then fill in values as phases need them
```

Backend:

```bash
cd backend
python3 -m venv .venv       # Windows: python -m venv .venv
```

Activate the virtual environment (every new terminal):

| Shell | Command (from `backend/`) |
| --- | --- |
| macOS / Linux | `source .venv/bin/activate` |
| Windows, Git Bash | `source .venv/Scripts/activate` |
| Windows, PowerShell | `.venv\Scripts\Activate.ps1` |

Then install:

```bash
python -m pip install -r requirements-dev.txt
```

Run this again after pulling a change to `requirements.txt`. The geometry packages (`numpy`, `rtree`, `trimesh`) were added on 2026-11-14; without them the backend still starts, but the tests that ask what can be seen fail. `pypdf` was added on 2026-11-17; without it uploaded notes can't be searched (the session still works from the facts Claude reads at the start), and one test is skipped.

Frontend:

```bash
cd frontend
npm install
```

## The session agent

Study sessions come from the hand-written sample unless the agent is switched on. The sample is free and needs no key.

To have Claude build sessions, set these in the repo-root `.env` and restart the backend:

```bash
ANTHROPIC_API_KEY=...      # never commit this
SESSION_SOURCE=agent
```

Every session then costs API credit, including ones started by accident while testing the app, so set `SESSION_SOURCE=sample` again when you are done. `LLM_MODEL` and `LLM_EFFORT` are optional (see `.env.example`).

To run one real session without the app and see what it built and what it used:

```bash
cd backend
python -m scripts.try_agent "Prepare me on the blood supply of the heart" --wrong
```

The tests never call Claude: they replay scripted replies (`backend/tests/test_agent.py`).

## Running

Two terminals.

Backend on http://localhost:8000 (from `backend/`, with the venv active):

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Frontend on http://localhost:5173 (from `frontend/`):

```bash
npm run dev
```

The page shows the 3D heart, which you can rotate, zoom and click, and a "Backend: connected" badge when both servers are up. In dev builds the scene controller is available in the browser console as `window.lumen` and the selection as `window.lumenSelection`. For example, `lumen.setVisibility({ layers: ['chambers'] }, false)` hides the chambers so the valves can be clicked.

## Tests and checks

```bash
cd backend && python -m pytest          # venv active
cd frontend && npm test
cd frontend && npm run typecheck
cd frontend && npm run build
```

Frontend behavior is checked manually with `docs/test_checklist.md`.

## Configuration

All settings live in the repo-root `.env` (see `.env.example`). The backend reads it through `backend/app/config.py`; Vite reads the same file (`envDir: '..'`) but only exposes `VITE_*` variables to the browser, so API keys never reach frontend code.

## Claude Code preview (optional)

`.claude/launch.json` is gitignored because the venv path differs per OS. To start both servers from the Claude desktop app, create it locally with a `backend` entry whose `runtimeExecutable` is `backend/.venv/bin/python` (macOS) or `backend/.venv/Scripts/python.exe` (Windows), `runtimeArgs` `["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", "8000"]`, and a `frontend` entry running `npm --prefix frontend run dev` on port 5173.
