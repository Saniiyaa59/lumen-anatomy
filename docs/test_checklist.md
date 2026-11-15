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
- [ ] Each valve leaflet is its own structure: clicking one selects that leaflet only
- [ ] After the chambers are hidden in the structures panel, the valves and papillary muscles can be hovered and clicked
- [ ] The thin coronary arteries can be clicked after zooming in
- [ ] `lumenSelection.getState()` in the console lists `selected` in click order and one `clickLog` entry per selected structure; a click in the 3D view also has `place.point`

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

- [ ] The Structures list (opened from the top-left button) shows the atlas groups (Heart first), each with its structures under it and a color dot matching the 3D model; a branch is indented under the vessel it comes off
- [ ] A structure's eye button hides it in the 3D view and dims its row; clicking again shows it
- [ ] A group's eye button hides every structure listed in the group; clicking again shows them all
- [ ] With only some of a group hidden, the group's eye is dimmed and one click shows the whole group
- [ ] Hidden structures can't be hovered or clicked in the 3D view, and structures behind them can
- [ ] "Show all" brings everything back, and is greyed out when nothing is hidden
- [ ] A group's name collapses and expands its list
- [ ] × closes the list; the "Structures" button reopens it with the same items hidden
- [ ] `lumen.setVisibility({ structureIds: ['aortic_arch'] }, false)` in the console also updates the panel's eye for the aortic arch
- [ ] `lumen.setVisibility({ groups: ['cardiac_veins'] }, false)` hides every cardiac vein

## Layout

- [ ] Three areas: a rail on the left (New session, History), the 3D view in the middle, and the session column on the right
- [ ] With no session open, the right column asks "What do you need to be ready for?", with a suggestion and an input box at the bottom
- [ ] The rail's top button collapses it to a thin strip and opens it again; the choice survives a reload
- [ ] "Structures" (top left of the 3D view) opens a compact list over the model and closes it again; its × also closes it
- [ ] Dragging the border between the 3D view and the session column resizes both; the model redraws as you drag and is never squashed
- [ ] The session column stops at about 320 px narrow and at 60% of the window wide
- [ ] Double-clicking the border returns it to the default width; with the border focused, the left and right arrow keys move it
- [ ] The width survives a reload
- [ ] After the border is dragged during a session part, the camera re-aims so the part's artery is still in view

## History

- [ ] Starting a session adds it to History with its request and the time
- [ ] "New session" returns to the start screen and resets the heart; the session stays in History
- [ ] Clicking a History entry reopens it on the part where it was left, with the slider position and case answers as they were
- [ ] After a reload the History is still listed and its entries still reopen
- [ ] Hovering an entry shows a ×, which removes it; removing the open session closes it

## Sessions through the backend

Run with the backend started.

- [ ] Typing a request and pressing Enter starts a session: what you typed appears as the message and as the title, and the line under the title ends "from the backend"
- [ ] The paperclip opens a file picker for PDFs; the chosen file's name appears above the input with a × to remove it
- [ ] "Next" briefly reads "Loading…" while a part is fetched, then the part opens; going Back and Next again does not fetch a part twice
- [ ] After answering the case, `GET /api/sessions/{id}` (see the API docs page) lists each click with its attempt number and whether it was correct, and the notes' file name
- [ ] "See the summary" fetches the summary; the backend then reports the session as finished
- [ ] With the backend stopped, starting a session shows "The session couldn't start" with the reason and "Play the built-in sample instead", which plays the same session marked "built-in sample"
- [ ] Stopping the backend mid-session, then pressing Next, shows the reason and turns the button into "Try again"; the parts already received stay usable
- [ ] Reopening a backend session from History after the backend restarted shows what was already received; Next explains that the session is no longer on the server

## Sessions built by the agent

These spend API credit. Set `SESSION_SOURCE=agent` and a key in `.env`, restart the backend, and set it back to `sample` afterwards.

- [ ] The start screen says sessions are built by Claude and take about a minute
- [ ] Starting a session shows "The tutor is reading and planning", then a plan of three or four parts ending in a case
- [ ] "What the model can and can't show" lists things specific to the request
- [ ] Each part opens with what it is about in view; nothing it talks about is hidden behind another structure
- [ ] Every statement has a source; opening an atlas link shows an article that says what the statement says
- [ ] With notes attached, some statements read "Your notes: <file>, page N", and that page says so
- [ ] A case's story does not name the answer, and only one place fits it
- [ ] Answering a case wrongly once, then pressing Next, sometimes adds a part to the plan that addresses the mistake
- [ ] The summary's "worth another look" reflects what was actually answered wrongly
- [ ] `GET /api/sessions/{id}` shows `source: agent`, the number of requests to Claude, the tokens used, and any parts given up on

## Sample session

- [ ] Starting a session (by the suggestion or by typing) shows the request as a message, then a Plan card, then part 1 as an open card
- [ ] Part 1 looks down on the heart with the great vessels hidden, and the right coronary artery is tinted
- [ ] Every statement has a source under it; atlas sources are links that open the article
- [ ] "Next" and "Back" move between parts; earlier parts stay in the thread as one-line cards, and clicking one reopens it
- [ ] The input box is greyed out during a session and says asking mid-session isn't built yet
- [ ] Part 2: a pale pulse runs from the top of the heart down both the anterior interventricular and the circumflex artery, pauses, and repeats
- [ ] Part 3: dragging the slider moves a pale mark along the artery and greys everything beyond it, branches included; clicking the artery moves the mark there
- [ ] Part 3: the boxed text under the slider changes when the mark crosses 47 mm
- [ ] Part 4: labels and the hover name disappear while the case is waiting for a click
- [ ] Part 4: clicking far down the artery gives "Not quite" with a reason, marks the click in red, and offers "Show me the answer"; the click does not select anything
- [ ] Part 4: clicking the artery near its start gives "Correct", paints the right stretch green, and the labels come back
- [ ] Part 4: "Show me the answer" paints the right stretch green without counting as correct
- [ ] The summary lists the case as "correct on try N" (or "answer shown"), then what was solid, what to look at again, and the sources
- [ ] Whatever a part hides shows as a crossed-out eye in the Structures panel, and clicking that eye brings the structure back
- [ ] Reaching the summary resets the heart: everything is shown, nothing is painted or tinted, and the camera glides back to the starting front view
- [ ] "Finish" or "New session" returns to the start screen and leaves the heart reset in the same way, whichever part was open
- [ ] During parts 1 to 3, clicking a structure still selects it as usual

## Position on a vessel

- [ ] With no session open, clicking a coronary artery shows a box (bottom left) with its name, the distance from where it begins, which piece (main trunk or a branch) and the distance along that piece
- [ ] Clicking further along the same artery gives a larger distance; clicking a side branch names a branch, not the main trunk
- [ ] "Click was … from the centre line" is about the vessel's radius (under 2 mm on a coronary artery)
- [ ] Clicking a chamber shows the box with the point only and says it is not a vessel
- [ ] The box is not shown while a session is open
