import tomllib
from dataclasses import dataclass
from pathlib import Path

import boto3

CONFIG_FILENAME = "r2.toml"


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
    )
    
    client.upload_file(str(local_path), cfg.bucket, key)

    domain = cfg.custom_domain.rstrip("/")
    if not domain:
        domain = f"{cfg.endpoint.rstrip('/')}/{cfg.bucket}"

    return f"{domain}/{key}"
