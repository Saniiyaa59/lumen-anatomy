# Frontend handoff

How the browser connects to the backend, and what to build so the two sides fit together without rework. The design behind it is in the README's "System design" section and the plan (Sections 8, 10.1 and 10.3).

## What's ready on the backend

| What | Where | Notes |
| --- | --- | --- |
| Structure registry | `assets/structures.json` | 21 structures. Each lists the GLB meshes it covers, e.g. `aortic_valve` → 3 leaflet meshes. |
| Action contract | `backend/app/actions.py` | Every scene action the agent can send, with its fields. |
| Request and response | `backend/app/schemas.py` | The bodies of `POST /api/command`. |
| Stub endpoint | `POST /api/command` | Checks the request and returns a sample response. Real behavior arrives with the agent; the format won't change. |
| Sample responses | `assets/fixtures/*.json` | `here_to_there`, `compare_valves`, `clarification`. Use them for mock mode and for testing the executor. |
| API docs | http://localhost:8000/docs | Generated from the models while the backend runs. Lists every field. |

The stub picks a sample from the request: no selection → `clarification`; `toolbar_command: "compare"` → `compare_valves`; anything else → `here_to_there`.

## Rules for both sides

- **Structure IDs are shared.** Change one only if we both agree, because the agent, retrieval, quiz and the browser all use them.
- **Show `display_name`, never the ID.** Students see "Left ventricle", not `left_ventricle`.
- **Clicks map mesh → structure.** Build a `meshName → structureId` map from `mesh_names` in `structures.json`. Clicking any of a structure's meshes selects the whole structure.
- **Fields you own in `structures.json`:** `views`, each structure's `best_view`, `cross_sections`, and the animation control points on `paths`. After editing, run the check from `backend/` (venv active):

  ```bash
  python -m scripts.validate_glb
  python -m pytest
  ```

## Suggested build order

1. **Load the registry and map clicks.** Import `structures.json`. Vite may refuse files outside `frontend/` until you add `server: { fs: { allow: ['..'] } }` to `vite.config.ts`. Log a warning for any GLB mesh missing from the map.
2. **Selection state.** Keep the selected IDs **in click order** (Shift-click order matters: the first chip is "here", the second is "there"). Record every selection click as `{ t, structure_id }` with `t = performance.now() / 1000`. These become `selection` and `click_events` in the request.
3. **One controller method per action.** On `SceneController`, add methods named and shaped like the actions in `actions.py`:

   | Action `type` | Controller method |
   | --- | --- |
   | `highlight` | `highlight(structureIds, color, exclusive)` |
   | `clear_highlights` | `clearHighlights()` |
   | `isolate` | `isolate(structureIds)` |
   | `label` / `clear_labels` | `label(structureId, text)` / `clearLabels()` |
   | `set_view` | `setView(view)` |
   | `focus` | `focus(structureId)` |
   | `set_visibility` | `setVisibility({ structureIds, layers }, visible)` |
   | `fade_others` | `fadeOthers(structureIds)` |
   | `animate_path` | `animatePath(path, from, to)` |
   | `cross_section` / `clear_cross_section` | `crossSection(section, position)` / `clearCrossSection()` |
   | `add_note` | `addNote(structureId, text, author)` |
   | `set_selection` | `setSelection(structureIds)` |
   | `reset_view` | `resetView()` |

   `color` is one of `primary`, `secondary`, `correct`, `wrong`. `exclusive: true` clears other highlights first.
4. **TypeScript types.** Mirror `schemas.py` and `actions.py` in `frontend/src/types.ts`, with `Action` as a union keyed on `type`. Field names stay snake_case to match the JSON. Note that `animate_path` uses `from` and `to`.
5. **Action executor.** `executeActions(actions)`: take one undo snapshot, then run each action in order through a `switch` on `type`. Log and skip unknown types instead of throwing, so one bad action doesn't stop the rest. One Undo should revert a whole response.
6. **API call with mock mode.** Add `sendCommand(request)` to `api.ts`. With `VITE_USE_MOCK=true`, return a file from `assets/fixtures/` instead of calling the backend, picked the same way as the stub. Then the UI can be built and demoed with no backend running.
7. **Show the response.** `answer` with citation links, chips that show which word matched which structure (`resolved_refs`), and `clarification` as a prompt to click.

## Formats at a glance

Request (`POST /api/command`):

```json
{
  "session_id": "abc123",
  "input_type": "text",
  "text": "How does blood get from here to there?",
  "audio": null,
  "click_events": [{"t": 41.2, "structure_id": "right_atrium"}, {"t": 42.0, "structure_id": "aorta"}],
  "selection": ["right_atrium", "aorta"],
  "toolbar_command": null,
  "scene_state": {"view": "anterior", "visible_layers": ["chambers", "valves", "great_vessels"], "highlighted": [], "cross_section": null},
  "mode": "explore"
}
```

- `text` can be omitted when a toolbar button was pressed. `audio` is a base64 recording, only for `input_type: "voice"`.
- Layers are `chambers`, `valves`, `great_vessels` and `coronary_vessels`.
- Unknown structure IDs in `selection` or `click_events` get a 422 response.

Response: see `assets/fixtures/here_to_there.json`. One difference from the plan: `resolved_refs` is a **list** of `{word, start, structure_ids}` instead of a word → ID map, so "compare this and this" can resolve each "this" separately. `start` is the word's character position in the text, for linking it to a chip.
