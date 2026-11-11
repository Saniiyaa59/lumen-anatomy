# Frontend manual test checklist

Run through the section for each finished phase before merging.

## Phase 0 — setup

- [ ] `npm run dev` starts on http://localhost:5173 without errors
- [ ] Drag rotates the camera; scroll zooms; right-drag pans
- [ ] Resizing the window keeps the model undistorted
- [ ] With the backend running, the badge reads "Backend: connected"
- [ ] With the backend stopped, the badge reads "Backend: unreachable" after reload
- [ ] `window.lumen` is defined in the browser console
- [ ] The medical-advice disclaimer is visible at the bottom

## Heart model and selection

- [ ] The heart loads in the anterior view, with red and blue vessels, and the browser console shows no warnings about missing meshes or structures
- [ ] Hovering a structure makes it slightly bigger, shows its name next to the cursor and turns the cursor into a pointer; moving off it undoes all three
- [ ] The hovered structure keeps its own color, and it grows and shrinks smoothly, not in a jump
- [ ] Hovering a thin vessel (e.g. a coronary artery) makes it visibly thicker
- [ ] Hovering a chamber doesn't hide the coronary vessels lying on it, and they can still be hovered and clicked
- [ ] No hover feedback appears while dragging to rotate
- [ ] Clicking a structure turns it gold and shows one chip with its name
- [ ] Clicking a different structure replaces the selection
- [ ] Shift-clicking adds structures; the chips are numbered in click order
- [ ] Shift-clicking a selected structure removes it
- [ ] A chip's × removes only that structure
- [ ] Esc clears the selection; so does a plain click on empty space
- [ ] Dragging to rotate never changes the selection
- [ ] A structure made of several parts lights up as a whole (e.g. all three aortic valve leaflets)
- [ ] After the chambers are hidden in the structures panel, the valves and papillary muscles can be hovered and clicked
- [ ] The thin coronary arteries can be clicked after zooming in
- [ ] `lumenSelection.getState()` in the console lists `selected` in click order and one `clickLog` entry per selected structure

## Recenter

- [ ] After rotating, zooming and panning (right-drag), "Recenter" (top right) glides the camera back to the starting front view, centered, at the starting zoom
- [ ] From behind the heart, the camera swings around it rather than passing through it
- [ ] Dragging during the glide stops it and gives control back straight away
- [ ] Recenter doesn't change the selection or which structures are hidden

## Labels

- [ ] On load, each structure that can be seen has a faint name label beside the heart, joined to it by a thin line ending in a dot on the structure
- [ ] Structures that can't be seen (e.g. the valves inside the chambers) have no label
- [ ] Rotating and zooming move the labels with the heart, without stutter; labels never overlap each other
- [ ] Labels appear for structures that come into view and disappear for ones that turn away
- [ ] The "Labels" switch (top right) hides every label and line; switching it back on shows them again
- [ ] Hovering a structure, or selecting it, makes its label and line bright
- [ ] Hovering a label makes its structure bigger, as hovering the structure does
- [ ] Clicking a label selects its structure; Shift-click adds it to the selection
- [ ] After the chambers are hidden in the structures panel, the valves and papillary muscles get labels

## Structures panel

- [ ] The panel on the right lists the four layers, each with its structures nested under it and a color dot matching the 3D model
- [ ] A structure's eye button hides it in the 3D view and dims its row; clicking again shows it
- [ ] A layer's eye button hides every structure in the layer; clicking again shows them all
- [ ] With only some of a layer hidden, the layer's eye is dimmed and one click shows the whole layer
- [ ] Hidden structures can't be hovered or clicked in the 3D view, and structures behind them can
- [ ] "Show all" brings everything back, and is greyed out when nothing is hidden
- [ ] A layer's name collapses and expands its list
- [ ] × closes the panel and the 3D view widens to fill the space; the "Structures" button (top right) reopens it with the same items hidden
- [ ] `lumen.setVisibility({ structureIds: ['aorta'] }, false)` in the console also updates the panel's eye for the aorta
