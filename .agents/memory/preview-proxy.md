---
name: Replit preview proxy diagnosis
description: Distinguish an app server failure from a Replit development-preview forwarding failure.
---

In an application-routed workspace, a healthy legacy workflow does not guarantee that the default preview has a backend. Check the registered artifacts for a service owning `/` before classifying a preview error as a platform outage.

**Why:** the FastAPI workflow had an open port and successful local health checks, but only the canvas service was registered with the application router. The default domain returned "Backend Not Configured" and the port-specific URL returned "repl unreachable". Registering a root service resolved the preview failure without changing the application.

**How to apply:** compare local health with the actual default preview domain, inspect `listArtifacts` and service paths, and ensure a root backend exists. For existing applications whose workflow must remain intact, a registered root routing adapter can forward to that server. Ensure the project Run group starts both services. Explicit `.replit` port mappings may be normalized away by the application-router configuration validator and are not a substitute for root registration.
