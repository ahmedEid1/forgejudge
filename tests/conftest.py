"""Shared pytest fixtures and path setup for the ForgeJudge test suite."""

import sys
from pathlib import Path

# Ensure the repo root is importable when tests run from any cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
