---
name: Replit preview proxy diagnosis
description: Distinguish an app server failure from a Replit development-preview forwarding failure.
---

If the application answers locally on the workflow's port, binds to `0.0.0.0`, and the workflow reports that port open, but the development domain returns `replit-proxy-error: repl unreachable`, the application is healthy while the preview forwarding path is not.

**Why:** local health checks passed while requests through the Replit development domain still failed at the proxy.

**How to apply:** verify both local and preview-domain requests. Do not keep restarting or change app code based only on a proxy-generated error; when port and bind configuration are correct, report the forwarding failure as platform-side.
