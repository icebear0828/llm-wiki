from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from llmwiki.stt.config import SttConfig


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    segments: list[dict[str, object]]
    duration: float | None


class WhisperError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"whisper returned {status}: {body[:300]}")
        self.status = status
        self.body = body


class WhisperUnreachable(WhisperError):
    def __init__(self, msg: str) -> None:
        super().__init__(0, msg)


class WhisperTimeout(WhisperError):
    def __init__(self, msg: str) -> None:
        super().__init__(0, msg)


def _resolve_language(arg: str | None, default: str) -> str | None:
    candidate = arg if arg is not None else default
    if candidate is None:
        return None
    candidate = candidate.strip()
    if not candidate or candidate.lower() == "auto":
        return None
    return candidate


def _duration_from_segments(segments: list[dict[str, object]]) -> float | None:
    end_values: list[float] = []
    for seg in segments:
        end = seg.get("end")
        if isinstance(end, (int, float)):
            end_values.append(float(end))
    if not end_values:
        return None
    return max(end_values)


class WhisperClient:
    def __init__(self, cfg: SttConfig) -> None:
        self.cfg = cfg

    def transcribe(
        self,
        audio: Path,
        *,
        language: str | None = None,
        include_segments: bool = True,
    ) -> Transcript:
        url = self.cfg.whisper_base_url.rstrip("/") + "/transcribe"
        files = {
            "file": (audio.name, audio.read_bytes(), "application/octet-stream"),
        }
        data: dict[str, str] = {
            "include_segments": "true" if include_segments else "false",
        }
        lang = _resolve_language(language, self.cfg.default_language)
        if lang is not None:
            data["language"] = lang

        try:
            with httpx.Client(timeout=self.cfg.timeout) as client:
                response = client.post(url, files=files, data=data)
        except httpx.ConnectError as e:
            raise WhisperUnreachable(f"connect failed: {e}") from e
        except httpx.TimeoutException as e:
            raise WhisperTimeout(f"timeout after {self.cfg.timeout}s: {e}") from e

        body = response.text
        if response.status_code >= 400:
            raise WhisperError(response.status_code, body)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise WhisperError(response.status_code, f"invalid JSON: {body[:300]}") from e

        if not isinstance(payload, dict):
            raise WhisperError(response.status_code, f"invalid JSON: {body[:300]}")

        text = str(payload.get("text", ""))
        language_out = str(payload.get("language", ""))
        raw_segments = payload.get("segments")
        segments: list[dict[str, object]] = []
        if isinstance(raw_segments, list):
            for seg in raw_segments:
                if isinstance(seg, dict):
                    segments.append({str(k): v for k, v in seg.items()})
        duration = _duration_from_segments(segments) if segments else None
        return Transcript(
            text=text,
            language=language_out,
            segments=segments,
            duration=duration,
        )
