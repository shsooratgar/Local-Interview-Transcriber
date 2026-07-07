# output/ — annotated results (NEVER uploaded)

Everything except this README is git-ignored. Layout:

- `reviews/`  — review page (`.review.html`), its data (`.review.json`/`.docx`),
                your keep/drop choices (`.choices.json`), playback audio (`.mp3`)
- `final/`    — corrected transcripts (`.corrected.docx`) — the deliverables
- `changes/`  — change-tracked copies (`.changes.docx`): removals struck through,
                additions green — the step between original and final
- `cache/`    — machine memory (transcriptions, re-listen clips); safe to ignore,
                delete a file's entries here to force a full re-listen
- `data_log.xlsx` — batch status sheet (one row per interview)
