from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llmwiki.r2 import R2Config, R2UploadError, R2VerifyError, upload_asset


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


def _make_cfg() -> R2Config:
    return R2Config(
        enabled=True,
        endpoint="https://12345.r2.cloudflarestorage.com",
        access_key="abc",
        secret_key="def",
        bucket="my-bucket",
        custom_domain="https://pub.example.com/",
    )


@patch("llmwiki.r2.boto3.client")
def test_upload_asset(mock_client_cls: MagicMock, tmp_path: Path) -> None:
    mock_s3 = MagicMock()
    mock_client_cls.return_value = mock_s3

    cfg = _make_cfg()

    vault_root = tmp_path
    asset_file = vault_root / "assets" / "audio" / "test.mp3"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"dummy audio")
    mock_s3.head_object.return_value = {"ContentLength": asset_file.stat().st_size}

    url = upload_asset(cfg, asset_file, vault_root)

    # Check upload call
    mock_s3.upload_file.assert_called_once_with(
        str(asset_file), "my-bucket", "assets/audio/test.mp3"
    )
    mock_s3.head_object.assert_called_once_with(
        Bucket="my-bucket", Key="assets/audio/test.mp3"
    )

    # Check returned URL
    assert url == "https://pub.example.com/assets/audio/test.mp3"


@patch("llmwiki.r2.boto3.client")
def test_upload_asset_disabled(mock_client_cls: MagicMock, tmp_path: Path) -> None:
    cfg = R2Config(enabled=False, bucket="my-bucket")
    asset_file = tmp_path / "assets" / "test.mp3"

    url = upload_asset(cfg, asset_file, tmp_path)
    assert url is None
    mock_client_cls.assert_not_called()


@patch("llmwiki.r2.boto3.client")
def test_upload_asset_uses_timeout_config(
    mock_client_cls: MagicMock, tmp_path: Path
) -> None:
    mock_s3 = MagicMock()
    mock_client_cls.return_value = mock_s3
    cfg = _make_cfg()

    asset_file = tmp_path / "assets" / "audio" / "x.mp3"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"hi")
    mock_s3.head_object.return_value = {"ContentLength": asset_file.stat().st_size}

    upload_asset(cfg, asset_file, tmp_path)

    boto_cfg = mock_client_cls.call_args.kwargs.get("config")
    assert boto_cfg is not None
    assert boto_cfg.connect_timeout == 10
    assert boto_cfg.read_timeout == 60
    assert boto_cfg.retries.get("max_attempts") == 3


@patch("llmwiki.r2.boto3.client")
def test_upload_asset_head_size_mismatch_raises(
    mock_client_cls: MagicMock, tmp_path: Path
) -> None:
    mock_s3 = MagicMock()
    mock_client_cls.return_value = mock_s3
    cfg = _make_cfg()

    asset_file = tmp_path / "assets" / "audio" / "y.mp3"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"abcdef")
    mock_s3.head_object.return_value = {"ContentLength": 1}

    with pytest.raises(R2VerifyError):
        upload_asset(cfg, asset_file, tmp_path)

    assert asset_file.exists()


_SECRET_MARKERS = ("Signature=", "secret_key", "AKIA", "LEAKED")


def _assert_no_leak(text: str) -> None:
    for marker in _SECRET_MARKERS:
        assert marker not in text, f"leak marker {marker!r} found in: {text!r}"


@patch("llmwiki.r2.boto3.client")
def test_upload_asset_error_does_not_leak_secrets(
    mock_client_cls: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_s3 = MagicMock()
    mock_client_cls.return_value = mock_s3
    cfg = _make_cfg()

    class BotoLikeError(Exception):
        pass

    mock_s3.upload_file.side_effect = BotoLikeError(
        "PutObject failed Signature=AKIAIOSFODNN7EXAMPLE secret_key=LEAKED"
    )

    asset_file = tmp_path / "assets" / "audio" / "z.mp3"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"x")

    caplog.set_level(logging.ERROR, logger="llmwiki.r2")

    with pytest.raises(R2UploadError) as exc_info:
        upload_asset(cfg, asset_file, tmp_path)

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__
    _assert_no_leak(str(exc_info.value))

    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    for record in caplog.records:
        _assert_no_leak(record.getMessage())
        _assert_no_leak(formatter.format(record))


@patch("llmwiki.r2.boto3.client")
def test_upload_asset_head_error_does_not_leak_secrets(
    mock_client_cls: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_s3 = MagicMock()
    mock_client_cls.return_value = mock_s3
    cfg = _make_cfg()

    class BotoLikeError(Exception):
        pass

    mock_s3.head_object.side_effect = BotoLikeError(
        "HeadObject failed Signature=BAD secret_key=LEAKED"
    )

    asset_file = tmp_path / "assets" / "audio" / "h.mp3"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"x")

    caplog.set_level(logging.ERROR, logger="llmwiki.r2")

    with pytest.raises(R2UploadError) as exc_info:
        upload_asset(cfg, asset_file, tmp_path)

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__
    _assert_no_leak(str(exc_info.value))

    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    for record in caplog.records:
        _assert_no_leak(record.getMessage())
        _assert_no_leak(formatter.format(record))
