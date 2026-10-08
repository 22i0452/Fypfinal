---
name: Git data safety
description: Keep clinic database records and call media out of inspection and Git pushes.
---

Do not inspect clinic database records or publish database contents. Check outgoing commits before pushing; avoid publishing tracked database snapshots or call-media files.

**Why:** The user explicitly asked that clinic database contents not be inspected or pushed.

**How to apply:** Before any Git push, inspect the commits and paths that would be sent. If database or media content would be included or deleted remotely, do not push without clarification.
