---
name: Workflow callback argument shape
description: Runtime argument shape for Replit workflow callbacks used through CodeExecution.
---

When calling `removeWorkflow` through CodeExecution, pass an object such as `{ name: "Run MedFlow" }`; the runtime rejects the string argument shown in the workflows skill example.

**Why:** the current callback wrapper validates one JSON object argument even though the skill documents a string parameter.

**How to apply:** use the object form for workflow removal, then confirm the resulting workflow list and configuration.
