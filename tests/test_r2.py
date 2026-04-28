from pathlib import Path
from unittest.mock import MagicMock, patch

from llmwiki.r2 import R2Config, upload_asset


def test_r2_config_load(tmp_path: Path) -> None:
    # Empty config
    cfg = R2Config.load(tmp_path)
    assert not cfg.enabled

    # Valid config
    toml_path = tmp_path / "r2.toml"
    toml_path.write_text(
        """
[r2]
enabled = true
endpoint = "https://12345.r2.cloudflarestorage.com"
access_key = "abc"
secret_key = "def"
bucket = "my-bucket"
custom_domain = "https://pub.example.com"
"""
    )
    cfg2 = R2Config.load(tmp_path)
    assert cfg2.enabled
    assert cfg2.endpoint == "https://12345.r2.cloudflarestorage.com"
    assert cfg2.access_key == "abc"
    assert cfg2.secret_key == "def"
    assert cfg2.bucket == "my-bucket"
    assert cfg2.custom_domain == "https://pub.example.com"


@patch("boto3.client")
def test_upload_asset(mock_client_cls: MagicMock, tmp_path: Path) -> None:
    mock_s3 = MagicMock()
    mock_client_cls.return_value = mock_s3

    cfg = R2Config(
        enabled=True,
        endpoint="https://12345.r2.cloudflarestorage.com",
        access_key="abc",
        secret_key="def",
        bucket="my-bucket",
        custom_domain="https://pub.example.com/",
    )

    vault_root = tmp_path
    asset_file = vault_root / "assets" / "audio" / "test.mp3"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_text("dummy audio")

    url = upload_asset(cfg, asset_file, vault_root)

    # Check upload call
    mock_s3.upload_file.assert_called_once_with(
        str(asset_file), "my-bucket", "assets/audio/test.mp3"
    )

    # Check returned URL
    assert url == "https://pub.example.com/assets/audio/test.mp3"


@patch("boto3.client")
def test_upload_asset_disabled(mock_client_cls: MagicMock, tmp_path: Path) -> None:
    cfg = R2Config(enabled=False, bucket="my-bucket")
    asset_file = tmp_path / "assets" / "test.mp3"
    
    url = upload_asset(cfg, asset_file, tmp_path)
    assert url is None
    mock_client_cls.assert_not_called()
