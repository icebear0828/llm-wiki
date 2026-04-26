from __future__ import annotations

from pathlib import Path
from typing import Protocol


class NoteLike(Protocol):
    path: Path
    title: str
    source_url: str | None
    source_file: Path | None
