from __future__ import annotations

from pathlib import Path
from typing import Callable

from llmwiki.tasks import audio, flashcards, report, slides, video
from llmwiki.tasks._types import NoteLike

TaskFn = Callable[[NoteLike], dict[str, Path]]

TASK_REGISTRY: dict[str, TaskFn] = {
    "audio": audio.run,
    "report": report.run,
    "slides": slides.run,
    "video": video.run,
    "flashcards": flashcards.run,
}

__all__ = ["TASK_REGISTRY", "TaskFn", "NoteLike"]
