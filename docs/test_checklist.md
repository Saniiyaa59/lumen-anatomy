# Frontend manual test checklist

Run through the section for each finished phase before merging.

## Phase 0 — setup

- [ ] `npm run dev` starts on http://localhost:5173 without errors
- [ ] The page shows a red placeholder cube on a dark background
- [ ] Drag rotates the camera; scroll zooms; right-drag pans
- [ ] Resizing the window keeps the cube undistorted
- [ ] With the backend running, the badge reads "Backend: connected"
- [ ] With the backend stopped, the badge reads "Backend: unreachable" after reload
- [ ] `window.lumen` is defined in the browser console
- [ ] The medical-advice disclaimer is visible at the bottom
