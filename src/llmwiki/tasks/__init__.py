from __future__ import annotations

from pathlib import Path
from typing import Callable

from llmwiki.tasks import (
    audio,
    flashcards,
    gen_image,
    report,
    slides,
    source_add,
    transcribe,
    video,
)
from llmwiki.tasks._types import NoteLike

TaskFn = Callable[..., dict[str, Path]]

TASK_REGISTRY: dict[str, TaskFn] = {
    "audio": audio.run,
    "report": report.run,
    "slides": slides.run,
    "video": video.run,
    "flashcards": flashcards.run,
    "transcribe": transcribe.run,
    "gen-image": gen_image.run,
    "source-add": source_add.run,
}

__all__ = ["TASK_REGISTRY", "TaskFn", "NoteLike"]
