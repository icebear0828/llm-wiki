from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.config import Config

CONFIG_FILENAME = "r2.toml"
log = logging.getLogger(__name__)


class R2VerifyError(Exception):
    """Raised when an uploaded object's size does not match the local file."""


class R2UploadError(Exception):
    """Sanitized wrapper for boto/httpx upload failures."""


@dataclass
class R2Config:
    enabled: bool = False
    endpoint: str = ""
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    custom_domain: str = ""

    @classmethod
    def load(cls, vault_root: Path) -> "R2Config":
        toml_path = Path(vault_root) / CONFIG_FILENAME
        if not toml_path.is_file():
            return cls()
            
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
            
        r2 = data.get("r2", {})
        if not isinstance(r2, dict):
            r2 = {}
            
        return cls(
            enabled=bool(r2.get("enabled", False)),
            endpoint=str(r2.get("endpoint", "")).strip(),
            access_key=str(r2.get("access_key", "")).strip(),
            secret_key=str(r2.get("secret_key", "")).strip(),
            bucket=str(r2.get("bucket", "")).strip(),
            custom_domain=str(r2.get("custom_domain", "")).strip(),
        )


def upload_asset(cfg: R2Config, local_path: Path, vault_root: Path) -> str | None:
    """Uploads a local asset to R2 and returns its public URL.
    Returns None if R2 is disabled or not properly configured.
    Raises R2VerifyError if head_object size verification fails.
    Raises R2UploadError for sanitized boto/client failures.
    """
    if not cfg.enabled or not cfg.bucket:
        return None

    try:
        rel = local_path.resolve().relative_to(vault_root.resolve())
    except ValueError:
        rel = local_path.name

    key = str(rel).replace("\\", "/")

    client = boto3.client(
        "s3",
        endpoint_url=cfg.endpoint,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        config=Config(
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )

    try:
        client.upload_file(str(local_path), cfg.bucket, key)
    except Exception as exc:
        err_type = type(exc).__name__
        log.error(
            "R2 upload_file failed: bucket=%s key=%s err=%s",
            cfg.bucket,
            key,
            err_type,
        )
        raise R2UploadError(
            f"upload failed bucket={cfg.bucket} key={key} type={err_type}"
        ) from None

    try:
        head = client.head_object(Bucket=cfg.bucket, Key=key)
    except Exception as exc:
        err_type = type(exc).__name__
        log.error(
            "R2 head_object failed: bucket=%s key=%s err=%s",
            cfg.bucket,
            key,
            err_type,
        )
        raise R2UploadError(
            f"head_object failed bucket={cfg.bucket} key={key} type={err_type}"
        ) from None

    try:
        local_size = local_path.stat().st_size
    except OSError as exc:
        err_type = type(exc).__name__
        log.error(
            "R2 local stat failed: bucket=%s key=%s err=%s",
            cfg.bucket,
            key,
            err_type,
        )
        raise R2UploadError(
            f"local stat failed bucket={cfg.bucket} key={key} type={err_type}"
        ) from None

    remote_size = int(head.get("ContentLength", -1))
    if remote_size != local_size:
        log.error(
            "R2 upload verification failed: bucket=%s key=%s local=%s remote=%s",
            cfg.bucket,
            key,
            local_size,
            remote_size,
        )
        raise R2VerifyError(
            f"size mismatch bucket={cfg.bucket} key={key} "
            f"expected={local_size} actual={remote_size}"
        )

    domain = cfg.custom_domain.rstrip("/")
    if not domain:
        domain = f"{cfg.endpoint.rstrip('/')}/{cfg.bucket}"

    return f"{domain}/{key}"
