# MedFlow preview routing

This artifact registers the existing MedFlow application at `/` in the workspace
application router. It does not replace MedFlow's pages or database.

In development, start `Run MedFlow` on port 8000 and this artifact's managed
`web` workflow. Vite forwards every request to the existing FastAPI server,
including API requests, streamed responses, uploads, and WebSocket upgrades.
The scaffolded React pages are not served.
The project Run group starts both required workflows.

Production uses the existing `scripts/run_demo.py --published` entry point
directly, not the development proxy or scaffolded React build. Existing
published-mode validation and requirements remain in effect.
