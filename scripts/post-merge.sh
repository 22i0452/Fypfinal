#!/bin/bash
set -e
python -m pip install -r requirements-deploy.txt
# FastAPI creates only its own tables on startup. Do not run the unrelated
# Express/Drizzle template against the clinical demo database after pulling.
