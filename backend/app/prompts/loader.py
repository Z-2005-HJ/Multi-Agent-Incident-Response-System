from __future__ import annotations

from functools import lru_cache
from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    return path.read_text(encoding="utf-8").strip()


def prompt_version(name: str) -> str:
    path = PROMPT_DIR / name
    stat = path.stat()
    return f"{path.stem}:{int(stat.st_mtime)}"

