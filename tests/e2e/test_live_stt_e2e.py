from __future__ import annotations

import os
from pathlib import Path

import pytest

from llmwiki.stt.client import WhisperClient
from llmwiki.stt.config import SttConfig

pytestmark = [pytest.mark.e2e, pytest.mark.live]


def test_live_stt_transcribes_audio_three_times() -> None:
    base_url = os.environ.get("LLMWIKI_E2E_STT_BASE_URL")
    audio_raw = os.environ.get("LLMWIKI_E2E_STT_AUDIO")
    if not base_url or not audio_raw:
        pytest.skip("set LLMWIKI_E2E_STT_BASE_URL and LLMWIKI_E2E_STT_AUDIO")

    audio = Path(audio_raw)
    if not audio.is_file():
        pytest.skip(f"audio fixture not found: {audio}")

    client = WhisperClient(
        SttConfig(
            whisper_base_url=base_url,
            default_language=os.environ.get("LLMWIKI_E2E_STT_LANGUAGE", "auto"),
            timeout=float(os.environ.get("LLMWIKI_E2E_STT_TIMEOUT", "300")),
        )
    )

    texts: list[str] = []
    for _ in range(3):
        transcript = client.transcribe(audio)
        assert transcript.text.strip()
        texts.append(transcript.text.strip())
    assert len(texts) == 3
