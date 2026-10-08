---
name: Replit Python dependency installs
description: The base Nix Python may not support project package installation; use a managed runtime instead.
---

When Python package installation fails because the base Nix Python is immutable or lacks pip, install a Replit-managed Python runtime and then install the project requirements with the package manager.

**Why:** the preinstalled Python 3.13 could not install packages, while the managed Python 3.12 runtime worked.

**How to apply:** check the active Python before installing dependencies; if it is the immutable base runtime, use an available managed Python module first.

## Replit package installer side effects
After `installLanguagePackages`, inspect the dependency file before keeping its changes. The installer can append requested packages even when equivalent, constrained entries already exist, creating duplicate requirements.

**Why:** a package install added duplicate Python dependency lines to an existing requirements file; removing those duplicates kept the declared version bounds intact.

**How to apply:** preserve the project's existing constraints, remove only duplicate additions, and leave the installed runtime package available for the active workflow.

## Isolated Python subprocesses
When launching Python child processes with a scrubbed environment, preserve the parent interpreter's import paths in the child's `PYTHONPATH` without forwarding the rest of the environment. Do not restrict paths to directories named `site-packages` or `dist-packages`.

**Why:** Managed interpreters and launchers expose dependencies through `sys.path`, not necessarily through inherited `PYTHONPATH` or conventionally named package directories.

**How to apply:** Combine inherited `PYTHONPATH` entries with resolved string entries from the parent's `sys.path`, deduplicate them, and keep the credential and application-variable allowlist intact.
