---
name: Replit Python dependency installs
description: The base Nix Python may not support project package installation; use a managed runtime instead.
---

When Python package installation fails because the base Nix Python is immutable or lacks pip, install a Replit-managed Python runtime and then install the project requirements with the package manager.

**Why:** the preinstalled Python 3.13 could not install packages, while the managed Python 3.12 runtime worked.

**How to apply:** check the active Python before installing dependencies; if it is the immutable base runtime, use an available managed Python module first.
