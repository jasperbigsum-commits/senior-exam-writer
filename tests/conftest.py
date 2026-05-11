from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
PYTEST_TMP_ROOT = Path(tempfile.gettempdir()) / "senior-exam-writer-pytest" / "tmp"
PYTEST_CACHE_DIR = Path(tempfile.gettempdir()) / "senior-exam-writer-pytest" / "cache"
SCRIPTS_DIR = SKILL_ROOT / "scripts"

PYTEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
PYTEST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMP", str(PYTEST_TMP_ROOT))
os.environ.setdefault("TEMP", str(PYTEST_TMP_ROOT))

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def pytest_configure(config) -> None:
    config.option.basetemp = str(PYTEST_TMP_ROOT / f"run-{os.getpid()}")
    config.option.cache_dir = str(PYTEST_CACHE_DIR)
