# Decisions

Choices made where the implementation plan left things open. Newest at the bottom.

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-03 | **React 19** for the UI (the plan allowed plain TS or light React). | Team preference; chips, toolbar, quiz banner and walkthrough player are UI-state heavy. |
| 2026-11-03 | **Plain Three.js inside React**, not React Three Fiber. The scene lives in an imperative `SceneController` class (`frontend/src/viewer/controller.ts`) mounted by a thin `<Viewer>` component. | The plan's action executor calls controller methods directly (`highlight`, `isolate`, `focus`…). Keeping Three.js out of React's render cycle makes that straightforward and avoids one more dependency. |
| 2026-11-03 | **Vite 8 + TypeScript 7**, created by hand rather than `npm create vite`. | Same layout as the official `react-ts` template, minus ESLint for now. |
| 2026-11-03 | **One `.env` at the repo root**, shared by backend (`pydantic-settings`) and frontend (`envDir: '..'`). | One place to configure; Vite only exposes `VITE_*` variables, so secrets stay server-side. |
| 2026-11-03 | **venv + pinned `requirements.txt` / `requirements-dev.txt`** for Python. | Works on every machine with no extra tools; `uv` can replace it later without code changes. |
| 2026-11-03 | **`httpx2`** for the FastAPI test client. | Starlette deprecates `httpx` in the test client. |
| 2026-11-03 | **Ports:** frontend 5173, backend 8000. | Tool defaults. |
| 2026-11-03 | **No Docker or Kubernetes for now.** Add a single backend Dockerfile only if we deploy. | Local-first project with a laptop live demo; containers add setup cost without benefit until deployment. |
