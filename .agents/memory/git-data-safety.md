---
name: Git data safety
description: Keep clinic database records and call media out of inspection and Git pushes.
---

Do not inspect clinic database records or publish database contents. Check outgoing commits before pushing; avoid publishing tracked database snapshots or call-media files.

**Why:** The user explicitly asked that clinic database contents not be inspected or pushed.

**How to apply:** Before any Git push, inspect the commits and paths that would be sent. If database or media content would be included or deleted remotely, do not push without clarification.

For GitHub writes through the Replit connector, large Git Trees API requests containing raw file contents can receive a Cloudflare HTML 403 even when smaller writes succeed. Creating blobs through `POST /git/blobs` with base64 content, then assembling the tree from blob SHAs, succeeded for a code-only transfer.

**Why:** The connector's raw-content tree requests were blocked by an intermediary, while base64 blob uploads worked.

**How to apply:** For an approved code transfer, preserve the exact manifest, verify the base and branch state before creating the commit/ref, and use blob SHAs for the final tree if raw tree uploads are blocked.
