from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import httpx

from .config import ImagenConfig


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
        self.cfg = cfg

    def generate(self, prompt: str, *, n: int = 1, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
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

            payload = cast(dict[str, object], resp.json())
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
                    raw = base64.b64decode(str(item["b64_json"]))
                    target.write_bytes(raw)
                elif "url" in item and item["url"]:
                    img_url = str(item["url"])
                    try:
                        img_resp = client.get(img_url)
                    except httpx.TimeoutException as exc:
                        raise ImagenTimeout(f"timeout downloading {img_url}: {exc}") from exc
                    except httpx.ConnectError as exc:
                        raise ImagenUnreachable(
                            f"cannot reach image url {img_url}: {exc}"
                        ) from exc
                    except httpx.HTTPError as exc:
                        raise ImagenUnreachable(
                            f"http error downloading {img_url}: {exc}"
                        ) from exc
                    if img_resp.status_code >= 400:
                        raise ImagenError(img_resp.status_code, img_resp.text)
                    target.write_bytes(img_resp.content)
                else:
                    raise ImagenError(200, "data item has neither url nor b64_json")
                saved.append(target)

        return saved
