---
name: Replit Python dependency installs
description: The base Nix Python may not support project package installation; use a managed runtime instead.
---

For workspace package development, use a Replit-managed Python runtime rather than trying to install into the immutable base Nix Python. For publishing, let Replit's package setup install dependencies from `requirements.txt`; do not add direct `python -m pip install` commands to `.replit` build hooks or artifact production builds.

**Why:** the base Python install is immutable, and a publish build failed with PEP 668 after explicit pip install commands duplicated Replit's automatic requirements installation.

**How to apply:** check how dependencies are installed in the active environment. Use managed Python/package tooling for development installs, and keep production build steps free of redundant `pip install` commands.

## Replit package installer side effects
After `installLanguagePackages`, inspect the dependency file before keeping its changes. The installer can append requested packages even when equivalent, constrained entries already exist, creating duplicate requirements.

**Why:** a package install added duplicate Python dependency lines to an existing requirements file; removing those duplicates kept the declared version bounds intact.

**How to apply:** preserve the project's existing constraints, remove only duplicate additions, and leave the installed runtime package available for the active workflow.

## Isolated Python subprocesses
When launching Python child processes with a scrubbed environment, preserve the parent interpreter's import paths in the child's `PYTHONPATH` without forwarding the rest of the environment. Do not restrict paths to directories named `site-packages` or `dist-packages`.

**Why:** Managed interpreters and launchers expose dependencies through `sys.path`, not necessarily through inherited `PYTHONPATH` or conventionally named package directories.

**How to apply:** Combine inherited `PYTHONPATH` entries with resolved string entries from the parent's `sys.path`, deduplicate them, and keep the credential and application-variable allowlist intact.
