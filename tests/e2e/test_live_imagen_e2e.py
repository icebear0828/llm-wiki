from __future__ import annotations

import os
from pathlib import Path

import pytest

from llmwiki.imagen.client import ImagenClient
from llmwiki.imagen.config import ImagenConfig

pytestmark = [pytest.mark.e2e, pytest.mark.live]


def test_live_imagen_generates_three_images(tmp_path: Path) -> None:
    if os.environ.get("LLMWIKI_E2E_IMAGEN") != "1":
        pytest.skip("set LLMWIKI_E2E_IMAGEN=1 to run live image generation")
    base_url = os.environ.get("LLMWIKI_E2E_IMAGEN_BASE_URL", "")
    api_key = os.environ.get("LLMWIKI_E2E_IMAGEN_KEY") or os.environ.get("LLMWIKI_IMAGEN_KEY", "")
    model = os.environ.get("LLMWIKI_E2E_IMAGEN_MODEL", "")
    if not base_url or not api_key or not model:
        pytest.skip("set LLMWIKI_E2E_IMAGEN_BASE_URL, KEY, and MODEL")

    client = ImagenClient(
        ImagenConfig(
            backend=os.environ.get("LLMWIKI_E2E_IMAGEN_BACKEND", "gemini"),
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=float(os.environ.get("LLMWIKI_E2E_IMAGEN_TIMEOUT", "300")),
        )
    )

    out_dir = tmp_path / "images"
    paths = []
    for i in range(3):
        generated = client.generate(
            f"small deterministic product e2e icon, run {i}",
            n=1,
            out_dir=out_dir,
        )
        assert len(generated) == 1
        assert generated[0].is_file()
        assert generated[0].stat().st_size > 0
        paths.extend(generated)
    assert len(paths) == 3
