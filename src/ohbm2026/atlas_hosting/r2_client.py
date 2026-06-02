"""Cloudflare R2 (S3-compatible) client for Stage 20 publishing.

Spec: ``specs/020-cloudflare-r2-migration/`` — research R-3/R-4/R-5.

Credentials are read from the environment / ``.env`` by name only and
never logged (Principle V / CA-004). Existence is discovered at runtime
via ``head_object`` (Principle VII); a 404 means "object absent", any
other S3 failure is re-raised as a precise :class:`R2UploadError`
(Principle VI — no bare except, no silent fallback).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

from ohbm2026.exceptions import R2CredentialsError, R2UploadError

PathLike = Union[str, Path]

REQUIRED_VARS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
)

# Objects are content-addressed, so a long immutable cache is always safe.
# Public name (spec 022) so the uploader can record the applied policy in the
# upload-manifest provenance (FR-010); `_DEFAULT_CACHE_CONTROL` stays as a
# private back-compat alias for existing references.
DEFAULT_CACHE_CONTROL = "public, max-age=31536000, immutable"
_DEFAULT_CACHE_CONTROL = DEFAULT_CACHE_CONTROL
_PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"
# Multipart kicks in above this size so the large vectors sidecar
# uploads in parts without loading whole into memory.
_MULTIPART_THRESHOLD = 8 * 1024 * 1024


@dataclass(frozen=True)
class R2Settings:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: str
    key_prefix: str = ""

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Minimal ``.env`` reader (no python-dotenv dependency)."""

    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def load_settings(env_path: PathLike = ".env") -> R2Settings:
    """Build :class:`R2Settings` from the environment + ``.env``.

    Real environment variables take precedence over the file. A missing
    or blank REQUIRED var raises :class:`R2CredentialsError` naming the
    var — before any network client is constructed.
    """

    file_values = _parse_env_file(Path(env_path))

    def read(var: str, *, required: bool) -> str:
        value = os.environ.get(var) or file_values.get(var)
        if required and not value:
            raise R2CredentialsError(
                f"missing required R2 credential: {var}", var=var
            )
        return value or ""

    return R2Settings(
        account_id=read("R2_ACCOUNT_ID", required=True),
        access_key_id=read("R2_ACCESS_KEY_ID", required=True),
        secret_access_key=read("R2_SECRET_ACCESS_KEY", required=True),
        bucket=read("R2_BUCKET", required=True),
        public_base_url=read("R2_PUBLIC_BASE_URL", required=True),
        key_prefix=read("R2_KEY_PREFIX", required=False),
    )


def build_s3_client(settings: R2Settings):
    """Construct a boto3 S3 client pointed at the R2 endpoint.

    ``boto3`` is imported lazily so the base install (without the ``r2``
    extra) can still import this module.
    """

    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


class R2Client:
    """Thin wrapper over a boto3 S3 client bound to one bucket."""

    def __init__(self, client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: R2Settings) -> "R2Client":
        return cls(build_s3_client(settings), settings.bucket)

    def object_exists(self, key: str) -> Tuple[bool, Optional[int]]:
        """Return ``(exists, size_bytes)`` for ``key``.

        A 404 / NoSuchKey is the expected "absent" signal and returns
        ``(False, None)``. Any other S3 error re-raises as
        :class:`R2UploadError` (never swallowed).
        """

        from botocore.exceptions import ClientError

        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=key)
            return True, int(resp["ContentLength"])
        except ClientError as exc:
            error = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
            code = str(error.get("Code", ""))
            status = (
                exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if hasattr(exc, "response")
                else None
            )
            if code in ("404", "NoSuchKey", "NotFound") or status == 404:
                return False, None
            raise R2UploadError(
                "head_object failed",
                key=key,
                bucket=self._bucket,
                op="head_object",
                reason=code or str(status),
            ) from exc

    def upload(
        self,
        key: str,
        path: PathLike,
        *,
        content_type: str = _PARQUET_CONTENT_TYPE,
        cache_control: str = _DEFAULT_CACHE_CONTROL,
    ) -> None:
        """Upload ``path`` to ``key`` (multipart for large files).

        Never overwrites by intent — callers gate on
        :meth:`object_exists` first. Any S3 failure re-raises as
        :class:`R2UploadError`.
        """

        from boto3.s3.transfer import TransferConfig
        from botocore.exceptions import ClientError

        transfer = TransferConfig(
            multipart_threshold=_MULTIPART_THRESHOLD,
            multipart_chunksize=_MULTIPART_THRESHOLD,
        )
        try:
            self._client.upload_file(
                str(path),
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type, "CacheControl": cache_control},
                Config=transfer,
            )
        except ClientError as exc:
            error = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
            raise R2UploadError(
                "upload_file failed",
                key=key,
                bucket=self._bucket,
                op="upload",
                reason=str(error.get("Code", "")) or str(exc),
            ) from exc
