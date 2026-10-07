---
name: Replit artifact route precedence
description: Replit's path-based preview routing can send nested application requests to a more-specific service instead of the root web service.
---

When a web artifact routes an app through `/`, check for other artifacts that claim specific paths such as `/api`. Those more-specific routes can intercept requests that the root app expects to handle. Move unused template routes to a non-conflicting prefix.

**Why:** an unused API template owned `/api`, so MedFlow's `/api/desk/*` requests returned 502 even while its HTML pages loaded.

**How to apply:** inspect registered artifact service paths before diagnosing frontend API failures; verify both page routes and their API calls through the Replit preview domain.
