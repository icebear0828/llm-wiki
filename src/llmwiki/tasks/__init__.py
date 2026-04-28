from __future__ import annotations

from pathlib import Path
from typing import Callable

from llmwiki.tasks import (
    arxiv,
    audio,
    chat,
    data_table,
    flashcards,
    gen_image,
    infographic,
    quiz,
    report,
    slides,
    source_add,
    transcribe,
    video,
    youtube,
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
    "quiz": quiz.run,
    "infographic": infographic.run,
    "data-table": data_table.run,
    "chat": chat.run,
    "arxiv": arxiv.run,
    "youtube": youtube.run,
}

__all__ = ["TASK_REGISTRY", "TaskFn", "NoteLike"]
