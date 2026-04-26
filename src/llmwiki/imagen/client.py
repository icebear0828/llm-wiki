from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import httpx

from .config import ImagenConfig

_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class ImagenError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"imagen returned {status}: {body[:300]}")
        self.status = status
        self.body = body


class ImagenUnreachable(ImagenError):
    def __init__(self, msg: str) -> None:
        super().__init__(0, msg)


class ImagenTimeout(ImagenError):
    def __init__(self, msg: str) -> None:
        super().__init__(0, msg)


class ImagenClient:
    def __init__(self, cfg: ImagenConfig) -> None:
        if not cfg.api_key:
            raise ValueError(
                "imagen api_key is empty (set in imagen.toml or LLMWIKI_IMAGEN_KEY env)"
            )
        if cfg.backend not in ("gemini", "openai"):
            raise ValueError(f"imagen backend must be 'gemini' or 'openai', got {cfg.backend!r}")
        self.cfg = cfg

    def generate(self, prompt: str, *, n: int = 1, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        if self.cfg.backend == "gemini":
            return self._generate_gemini(prompt, n=n, out_dir=out_dir)
        return self._generate_openai(prompt, n=n, out_dir=out_dir)

    def _generate_gemini(self, prompt: str, *, n: int, out_dir: Path) -> list[Path]:
        # Gemini /v1beta returns 1 image per request via responseModalities=["IMAGE"].
        # n>1 means we issue n separate requests (no native batch).
        url = (
            f"{self.cfg.base_url.rstrip('/')}/v1beta/models/"
            f"{self.cfg.model}:generateContent"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        headers = {
            "x-goog-api-key": self.cfg.api_key,
            "Content-Type": "application/json",
        }

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        saved: list[Path] = []
        with httpx.Client(timeout=self.cfg.timeout) as client:
            for i in range(n):
                resp = self._post(client, url, body, headers)
                payload = self._parse_json(resp)
                inline = self._extract_inline_data(payload)
                ext = _MIME_TO_EXT.get(inline["mime"], ".bin")
                target = out_dir / f"{timestamp}-{i}{ext}"
                target.write_bytes(base64.b64decode(inline["data"]))
                saved.append(target)
        return saved

    def _generate_openai(self, prompt: str, *, n: int, out_dir: Path) -> list[Path]:
        url = f"{self.cfg.base_url.rstrip('/')}/images/generations"
        body = {
            "model": self.cfg.model,
            "prompt": prompt,
            "n": n,
            "size": self.cfg.size,
        }
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.cfg.timeout) as client:
            resp = self._post(client, url, body, headers)
            payload = self._parse_json(resp)
            data = payload.get("data")
            if not isinstance(data, list) or not data:
                raise ImagenError(200, "no images returned")

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            saved: list[Path] = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ImagenError(200, f"unexpected data item type: {type(item).__name__}")
                target = out_dir / f"{timestamp}-{i}.png"
                if "b64_json" in item and item["b64_json"]:
                    target.write_bytes(base64.b64decode(str(item["b64_json"])))
                elif "url" in item and item["url"]:
                    img_resp = self._get(client, str(item["url"]))
                    target.write_bytes(img_resp.content)
                else:
                    raise ImagenError(200, "data item has neither url nor b64_json")
                saved.append(target)
        return saved

    def _post(
        self,
        client: httpx.Client,
        url: str,
        body: dict[str, object],
        headers: dict[str, str],
    ) -> httpx.Response:
        try:
            resp = client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ImagenTimeout(f"timeout posting to {url}: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ImagenUnreachable(f"cannot reach {url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ImagenUnreachable(f"http error posting to {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ImagenError(resp.status_code, resp.text)
        return resp

    def _get(self, client: httpx.Client, url: str) -> httpx.Response:
        try:
            resp = client.get(url)
        except httpx.TimeoutException as exc:
            raise ImagenTimeout(f"timeout downloading {url}: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ImagenUnreachable(f"cannot reach {url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ImagenUnreachable(f"http error downloading {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ImagenError(resp.status_code, resp.text)
        return resp

    def _parse_json(self, resp: httpx.Response) -> dict[str, object]:
        try:
            return cast(dict[str, object], resp.json())
        except ValueError as exc:
            raise ImagenError(resp.status_code, f"invalid JSON: {resp.text[:300]}") from exc

    def _extract_inline_data(self, payload: dict[str, object]) -> dict[str, str]:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ImagenError(200, f"no candidates in response: {str(payload)[:200]}")
        first = candidates[0]
        if not isinstance(first, dict):
            raise ImagenError(200, "candidate is not a dict")
        content = first.get("content")
        if not isinstance(content, dict):
            raise ImagenError(200, "candidate has no content")
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise ImagenError(200, "content has no parts")
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict):
                continue
            data = inline.get("data")
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            if isinstance(data, str) and isinstance(mime, str):
                return {"data": data, "mime": mime}
        raise ImagenError(200, "no inlineData in any part (response may be text-only)")
