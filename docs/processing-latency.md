# Consultation processing and sign-in fixes

Translation and SOAP now use the configured provider chat model (for example
`OPENROUTER_LLM_MODEL`), as medicine analysis already did. Explicit allowlisted
model overrides still work. Previously these two tasks could choose the first
alphabetically sorted allowlisted model instead of the configured preference.

Chat calls pass their timeout to OpenRouter, OpenAI and Groq transports. The
default is 45 seconds; explicit task limits, such as relevance's 35 seconds,
still apply. Fallback attempts share the remaining request budget rather than
each getting a fresh timeout. Collected processing stages share a 90-second
chat budget, including medicine analysis, lookup, uncertain-name comparison,
translation, optional repair and relevance. Nested collectors cannot extend it.
Groq's hidden SDK retries are disabled; the gateway owns fallback attempts.
These are transport timeouts and budget checks, not a hard cancellation of every
socket operation or a guaranteed end-to-end latency. Speech recognition retains
its existing audio transport settings.

Full chronological medicine context remains mandatory. Exact catalogue names
skip a second reranking request only after complete context analysis; uncertain
spellings still receive full-context LLM comparison and doctor confirmation.
An exact-name result preserves spelling and leaves usage uncertain, rather than
asserting a prescription. Translation sends the entire original conversation,
speaker relationships and medicine manifest once instead of duplicating the
conversation in two formats. Repair keeps that original context and manifest.
Dose, stopping/avoid instructions, identity checks and approval gates remain.

English is saved before relevance classification and can be expanded during
processing. The checkpoint stays `TRANSLATING` until classification finishes;
the preview does not enable editing, SOAP generation or approval early. Retry
keeps the saved transcript and raw speech recognition text.

Real provider start/finish events now persist with task, model, fallback status
and measured attempt duration. The main process card shows compact substeps
even when the inspector is collapsed. Its stage clock advances while waiting;
saved-event replay does not invent elapsed time. No clinical text, credentials
or provider error bodies are added to provider receipts.

The workspace no longer contains the old embedded sign-in form. A current
MedFlow loading screen appears while session authentication resolves; the
workspace is revealed after its initial rendering. Expired sessions redirect
to the dedicated sign-in page. Server/network failures retain the loading
screen with a retry action rather than flashing an obsolete login screen.

Validation uses synthetic/offline tests: `tests.test_processing_latency`, the
medicine context/matching/preservation/placeholder suites, process observability,
guided consultation, SOAP quality, visit continuity, clinical documents and
consultation WebSockets. `tests/test_login_processing_browser.cjs` exercises the
actual sign-in navigation, a held session check, substep display and preview,
replay, retry and expired-session redirect. The existing medicine recovery
browser test verifies repair and review gates. Live Replit/provider timings
still need measurement; synthetic tests do not establish a speed percentage.
