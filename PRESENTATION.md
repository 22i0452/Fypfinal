# Optional presentation and website appearance

Open the monitor icon labelled **Display settings** in the page header. On sign-in it is in the upper-right corner.

- **Dark / Light** changes the whole website, including clinical dialogs, evidence, coding, voice controls and testing. Dark remains the default.
- **Page zoom** scales text, controls, diagrams and spacing from 80% to 160%. Reset returns to 100%. Layouts adapt to the space available after scaling.
- **Full screen** expands the website where the browser supports the Fullscreen API. Escape exits. Unsupported browsers omit that action; browser rejection is reported inside the settings panel.
- Theme and zoom persist in browser local storage across navigation and reloads. No patient information is stored by these settings.

## Returned-result playback

After saving a SOAP draft, use **Present SOAP** beside its existing actions. Playback reveals the attached conversation, S/O/A/P sections and recorded evidence checks over 13 seconds. Source highlights follow the attached IDs. Editing disables presentation until edits are saved or cancelled. Playback freezes the current note version; it does not generate another note.

**Present codes** appears beside returned current-version suggestions. It shows the saved SOAP source, ICD-10/CPT suggestions and their attached statement IDs. Old-version suggestions stay outside this presentation. Catalogue validity and clinical correctness remain unassessed.

After a saved receptionist voice/text intake or manual intake, use **Present handoff**. The 12-second sequence shows actual collected details, persistence, the booking receipt and the doctor destination. A missing appointment is explicitly shown as needing attention. A REQUESTED appointment remains pending confirmation. Active calls/capture and saves must finish before presentation can start.

**Replay** in the existing process inspector opens the same visual presenter using the saved capture events and original measured timings. Initial capture artifacts remain distinct from later saved SOAP edits.

Playback offers **Pause / Continue**, **Skip**, **Replay**, clickable stage selection and a smooth expand/restore control. Escape or Close returns to the existing workflow. Under reduced-motion preferences, the sequence opens at the completed view without timed motion; stages remain inspectable. Switching away from the browser tab pauses playback.

This is labelled **Result playback**. The moving lines and reveal progress represent presentation pacing, not a new model request or internal model reasoning. Records are already persisted where stated. No artificial delay is added to APIs, saving, speech playback or microphone turn handling. No extra keys, provider calls or installation steps are needed.

## Verification

`tests/test_presentation_browser.cjs` uses the real application with fictional providers and disposable clinic storage. It covers saved SOAP/source content, 13-second completion, pause/skip/replay, expansion, reduced motion, dirty-note blocking, coding and manual handoff. It checks that playback changes neither the saved note nor provider call counts. It exercises whole-page zoom at 80/100/130/160% and widths 1440/1280/390 across all five screen types, including modal bounds and settings persistence.

The existing hands-free browser journey also checks presentation of the actual returned voice-call booking receipt with unchanged STT/turn/TTS request counts. These are synthetic workflow and browser checks, not physical microphone accuracy or clinical validation.
