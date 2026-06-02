"""Tests for the Stage 20 R2 client.

Spec: ``specs/020-cloudflare-r2-migration/`` — research R-3/R-4. No
network: credential loading is exercised against a synthetic env, and
S3 calls are intercepted with ``botocore.stub.Stubber``.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from botocore.stub import Stubber

from ohbm2026.atlas_hosting import r2_client
from ohbm2026.exceptions import R2CredentialsError, R2UploadError


def _settings() -> r2_client.R2Settings:
    return r2_client.R2Settings(
        account_id="acct123",
        access_key_id="AKIA_TEST",
        secret_access_key="secret_test",
        bucket="aadata",
        public_base_url="https://aadata.cirrusscience.org",
        key_prefix="",
    )


class LoadSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.missing_env = Path(self._tmp.name) / "nonexistent.env"

    def test_missing_required_var_raises_credentials_error(self) -> None:
        env = {
            "R2_ACCOUNT_ID": "acct123",
            "R2_ACCESS_KEY_ID": "k",
            "R2_SECRET_ACCESS_KEY": "s",
            # R2_BUCKET deliberately absent
            "R2_PUBLIC_BASE_URL": "https://aadata.cirrusscience.org",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            with self.assertRaises(R2CredentialsError) as ctx:
                r2_client.load_settings(self.missing_env)
        self.assertEqual(ctx.exception.var, "R2_BUCKET")

    def test_loads_all_vars_and_optional_prefix(self) -> None:
        env = {
            "R2_ACCOUNT_ID": "acct123",
            "R2_ACCESS_KEY_ID": "k",
            "R2_SECRET_ACCESS_KEY": "s",
            "R2_BUCKET": "aadata",
            "R2_PUBLIC_BASE_URL": "https://aadata.cirrusscience.org",
            "R2_KEY_PREFIX": "atlas",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            settings = r2_client.load_settings(self.missing_env)
        self.assertEqual(settings.bucket, "aadata")
        self.assertEqual(settings.key_prefix, "atlas")

    def test_endpoint_url_from_account_id(self) -> None:
        self.assertEqual(
            _settings().endpoint_url,
            "https://acct123.r2.cloudflarestorage.com",
        )


class ObjectExistsTests(unittest.TestCase):
    def _client_and_stub(self):
        client = r2_client.build_s3_client(_settings())
        return client, Stubber(client)

    def test_404_means_absent(self) -> None:
        client, stub = self._client_and_stub()
        stub.add_client_error(
            "head_object", service_error_code="404", http_status_code=404
        )
        with stub:
            exists, size = r2_client.R2Client(client, "aadata").object_exists("k1")
        self.assertFalse(exists)
        self.assertIsNone(size)

    def test_present_returns_size(self) -> None:
        client, stub = self._client_and_stub()
        stub.add_response(
            "head_object",
            {"ContentLength": 4096},
            expected_params={"Bucket": "aadata", "Key": "k2"},
        )
        with stub:
            exists, size = r2_client.R2Client(client, "aadata").object_exists("k2")
        self.assertTrue(exists)
        self.assertEqual(size, 4096)

    def test_other_client_error_raises_upload_error(self) -> None:
        client, stub = self._client_and_stub()
        stub.add_client_error(
            "head_object", service_error_code="AccessDenied", http_status_code=403
        )
        with stub:
            with self.assertRaises(R2UploadError) as ctx:
                r2_client.R2Client(client, "aadata").object_exists("k3")
        self.assertEqual(ctx.exception.op, "head_object")
        self.assertEqual(ctx.exception.bucket, "aadata")


class UploadCachePolicyTests(unittest.TestCase):
    """Spec 022 (US2) — every uploaded object carries the immutable
    Cache-Control. boto3 ``upload_file`` applies ``ExtraArgs`` to BOTH
    single-part and multipart transfers, so this one assertion covers all
    object sizes (the vectors sidecar uploads multipart via TransferConfig)."""

    def test_upload_sets_immutable_cache_control_extraargs(self) -> None:
        client = mock.Mock()
        r2 = r2_client.R2Client(client, "aadata")
        with TemporaryDirectory() as td:
            path = Path(td) / "ohbm2026.parquet"
            path.write_bytes(b"hello world")
            r2.upload("9f/ohbm2026.parquet", path)

        client.upload_file.assert_called_once()
        extra = client.upload_file.call_args.kwargs["ExtraArgs"]
        self.assertEqual(extra["CacheControl"], "public, max-age=31536000, immutable")
        self.assertEqual(extra["CacheControl"], r2_client.DEFAULT_CACHE_CONTROL)
        self.assertIn("ContentType", extra)
        # multipart threshold/chunk are configured so large files go multipart
        # with the SAME ExtraArgs (no separate uncached path).
        cfg = client.upload_file.call_args.kwargs.get("Config")
        self.assertIsNotNone(cfg)


if __name__ == "__main__":
    unittest.main()
