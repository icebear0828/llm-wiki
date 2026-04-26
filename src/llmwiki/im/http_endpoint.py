from __future__ import annotations

import base64
import binascii
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from llmwiki.im.common import IncomingMessage, ingest
from llmwiki.im.config import ImConfig
from llmwiki.vault import Vault


class IngestRequest(BaseModel):
    kind: Literal["text", "url", "file_b64"]
    payload: str
    filename: str | None = None
    tags: list[str] = Field(default_factory=list)
    title: str | None = None
    source: str | None = None


def _check_auth(cfg: ImConfig, token: str | None) -> None:
    if cfg.http_token is None:
        return
    if token != cfg.http_token:
        raise HTTPException(status_code=401, detail="invalid or missing X-Llmwiki-Token")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def create_app(vault: Vault, cfg: ImConfig) -> FastAPI:
    app = FastAPI(title="llmwiki ingest")

    @app.exception_handler(HTTPException)
    async def _http_exc_handler(_request: object, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "error"
        return JSONResponse(status_code=exc.status_code, content={"error": message})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ingest")
    async def ingest_json(
        req: IngestRequest,
        x_llmwiki_token: str | None = Header(default=None, alias="X-Llmwiki-Token"),
    ) -> JSONResponse:
        _check_auth(cfg, x_llmwiki_token)

        source = req.source or "http"
        try:
            if req.kind == "text":
                if not req.payload:
                    return _error(400, "payload required for kind=text")
                msg = IncomingMessage(
                    kind="text",
                    text=req.payload,
                    source=source,
                    tags=list(req.tags),
                    title=req.title,
                )
                path = ingest(msg, vault, cfg)
            elif req.kind == "url":
                if not req.payload:
                    return _error(400, "payload required for kind=url")
                msg = IncomingMessage(
                    kind="url",
                    url=req.payload,
                    source=source,
                    tags=list(req.tags),
                    title=req.title,
                )
                path = ingest(msg, vault, cfg)
            elif req.kind == "file_b64":
                if not req.filename:
                    return _error(400, "filename required for kind=file_b64")
                if not req.payload:
                    return _error(400, "payload required for kind=file_b64")
                try:
                    raw_bytes = base64.b64decode(req.payload, validate=True)
                except (binascii.Error, ValueError) as e:
                    return _error(400, f"invalid base64: {e}")
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=f"-{req.filename}"
                ) as tmp:
                    tmp.write(raw_bytes)
                    tmp_path = Path(tmp.name)
                try:
                    real_src = tmp_path.with_name(req.filename)
                    tmp_path.replace(real_src)
                    msg = IncomingMessage(
                        kind="file",
                        file_path=real_src,
                        source=source,
                        tags=list(req.tags),
                        title=req.title,
                    )
                    path = ingest(msg, vault, cfg)
                finally:
                    for p in (tmp_path, tmp_path.with_name(req.filename)):
                        try:
                            p.unlink()
                        except FileNotFoundError:
                            pass
            else:
                return _error(400, f"unknown kind: {req.kind}")
        except HTTPException:
            raise
        except ValueError as e:
            return _error(400, str(e))
        except Exception as e:
            return _error(500, f"ingest failed: {e}")

        return JSONResponse(
            status_code=200,
            content={"path": str(path), "filename": path.name},
        )

    @app.post("/ingest/file")
    async def ingest_file(
        file: UploadFile = File(...),
        tags: str | None = Form(default=None),
        title: str | None = Form(default=None),
        source: str | None = Form(default=None),
        x_llmwiki_token: str | None = Header(default=None, alias="X-Llmwiki-Token"),
    ) -> JSONResponse:
        _check_auth(cfg, x_llmwiki_token)

        if not file.filename:
            return _error(400, "uploaded file missing filename")

        contents = await file.read()
        with tempfile.TemporaryDirectory() as td:
            tmp_dir = Path(td)
            real_src = tmp_dir / file.filename
            real_src.write_bytes(contents)
            tag_list: list[str] = []
            if tags:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            try:
                msg = IncomingMessage(
                    kind="file",
                    file_path=real_src,
                    source=source or "http",
                    tags=tag_list,
                    title=title,
                )
                path = ingest(msg, vault, cfg)
            except ValueError as e:
                return _error(400, str(e))
            except Exception as e:
                return _error(500, f"ingest failed: {e}")

        return JSONResponse(
            status_code=200,
            content={"path": str(path), "filename": path.name},
        )

    return app
