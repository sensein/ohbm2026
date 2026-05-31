"""Tests for the Stage 20 uploader (US1 happy path + US2 guarantees).

Spec: ``specs/020-cloudflare-r2-migration/`` — US1/US2,
``contracts/cli-upload-atlas-package.md``, data-model validation table.

A ``FakeR2Client`` test double stands in for the boto3-backed
:class:`R2Client` (whose own behaviour is covered by
``test_atlas_hosting_r2_client.py`` via the botocore Stubber). Tests run
from a temp CWD so the manifest's ``source_package_dir`` is repo-relative.

The data bundle = ``ohbm2026.parquet`` (Stage-10 build, supplied via
``ohbm2026_parquet``) + ``neuroscape.parquet`` + ``atlas.parquet`` +
``neuroscape_vectors.parquet`` (the build-atlas-package output dir). All
four are REQUIRED — the production build keeps the semantic index ON.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Tuple

from ohbm2026.atlas_hosting import uploader
from ohbm2026.atlas_hosting.content_hash import derive_object_key, sha256_file
from ohbm2026.atlas_hosting.r2_client import R2Settings
from ohbm2026.exceptions import ArtifactDiscoveryError, ContentHashMismatchError

# What build-atlas-package writes into --package-dir (all required).
PACKAGE_FILES = ("neuroscape.parquet", "atlas.parquet", "neuroscape_vectors.parquet")
ALL_LOGICAL = {"ohbm2026", "neuroscape", "atlas", "neuroscape_vectors"}


class FakeR2Client:
    """Duck-typed stand-in: ``exists`` maps key → remote size (bytes)."""

    def __init__(self, exists: Optional[dict[str, int]] = None) -> None:
        self.exists = dict(exists or {})
        self.uploaded: list[tuple[str, str]] = []

    def object_exists(self, key: str) -> Tuple[bool, Optional[int]]:
        if key in self.exists:
            return True, self.exists[key]
        return False, None

    def upload(self, key: str, path, **kwargs) -> None:
        self.uploaded.append((key, str(path)))


def _settings(prefix: str = "") -> R2Settings:
    return R2Settings(
        account_id="acct",
        access_key_id="AKIA_SECRET_KEYID",
        secret_access_key="TOP_SECRET_VALUE",
        bucket="aadata",
        public_base_url="https://aadata.cirrusscience.org",
        key_prefix=prefix,
    )


def _key(path: Path) -> str:
    return derive_object_key(sha256_file(path), Path(path).name)


class _TempCwd(unittest.TestCase):
    """Base: chdir into a temp dir; lay down a package dir + ohbm2026.parquet."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(lambda: os.chdir(self._cwd))

        # build-atlas-package output dir (neuroscape + atlas + vectors).
        self.pkg = Path("data/outputs/atlas-package__test")
        self.pkg.mkdir(parents=True)
        for name in PACKAGE_FILES:
            (self.pkg / name).write_bytes(b"content-of-" + name.encode())

        # ohbm2026.parquet lives elsewhere (Stage-10 build).
        ohbm_dir = Path("data/outputs/parquets/abc123")
        ohbm_dir.mkdir(parents=True)
        self.ohbm = ohbm_dir / "ohbm2026.parquet"
        self.ohbm.write_bytes(b"content-of-ohbm2026.parquet")

    def _upload(self, client, **kw):
        return uploader.upload_atlas_package(
            self.pkg, ohbm2026_parquet=self.ohbm, settings=_settings(), client=client, **kw
        )

    def _all_keys(self) -> dict[str, int]:
        keys = {_key(self.ohbm): self.ohbm.stat().st_size}
        for name in PACKAGE_FILES:
            p = self.pkg / name
            keys[_key(p)] = p.stat().st_size
        return keys


class HappyPathTests(_TempCwd):
    def test_uploads_all_four_writes_manifest_and_channel_entry(self) -> None:
        client = FakeR2Client(exists={})
        result = self._upload(client, command_line="ohbmcli upload-atlas-package")
        self.assertEqual(result.summary, {"uploaded": 4, "skipped": 0})
        self.assertEqual(len(client.uploaded), 4)
        self.assertEqual(set(result.channel_entry), ALL_LOGICAL)
        for sub in result.channel_entry.values():
            self.assertTrue(sub["url"].startswith("https://aadata.cirrusscience.org/"))
            self.assertRegex(sub["sha256"], r"^[0-9a-f]{64}$")
        self.assertIsNotNone(result.manifest_path)
        self.assertTrue(result.manifest_path.exists())
        self.assertTrue(
            str(result.manifest_path).startswith("data/provenance/atlas_upload_provenance__")
        )
        for obj in result.objects:
            self.assertIsNone(obj.source_build_state_key)


class IdempotentSkipTests(_TempCwd):
    def test_all_present_zero_uploads(self) -> None:  # FR-009 / SC-003
        result = self._upload(FakeR2Client(exists=self._all_keys()))
        self.assertEqual(result.summary, {"uploaded": 0, "skipped": 4})
        for obj in result.objects:
            self.assertEqual(obj.action, "skipped")


class ImmutableMultiVersionTests(_TempCwd):
    def test_change_one_only_new_key_uploaded_prior_keys_intact(self) -> None:  # FR-008 / SC-004
        exists = self._all_keys()
        original_neuro = _key(self.pkg / "neuroscape.parquet")
        client = FakeR2Client(exists=exists)

        (self.pkg / "neuroscape.parquet").write_bytes(b"NEW-neuroscape-bytes-v2")
        new_neuro_key = _key(self.pkg / "neuroscape.parquet")
        self.assertNotEqual(new_neuro_key, original_neuro)

        result = self._upload(client)
        self.assertEqual(result.summary, {"uploaded": 1, "skipped": 3})
        self.assertEqual([k for k, _ in client.uploaded], [new_neuro_key])
        self.assertIn(original_neuro, client.exists)  # prior key never deleted


class DiscoveryTests(_TempCwd):
    def test_missing_required_package_artifact_raises(self) -> None:
        (self.pkg / "atlas.parquet").unlink()
        with self.assertRaises(ArtifactDiscoveryError) as ctx:
            self._upload(FakeR2Client())
        self.assertIn("atlas.parquet", ctx.exception.missing)

    def test_missing_neuroscape_vectors_raises(self) -> None:  # now REQUIRED
        (self.pkg / "neuroscape_vectors.parquet").unlink()
        with self.assertRaises(ArtifactDiscoveryError) as ctx:
            self._upload(FakeR2Client())
        self.assertIn("neuroscape_vectors.parquet", ctx.exception.missing)

    def test_missing_ohbm2026_parquet_raises(self) -> None:
        self.ohbm.unlink()
        with self.assertRaises(ArtifactDiscoveryError) as ctx:
            self._upload(FakeR2Client())
        self.assertIn("ohbm2026.parquet", ctx.exception.missing)

    def test_unexpected_parquet_in_package_dir_raises(self) -> None:
        (self.pkg / "stray.parquet").write_bytes(b"x")
        with self.assertRaises(ArtifactDiscoveryError) as ctx:
            self._upload(FakeR2Client())
        self.assertIn("stray.parquet", ctx.exception.unexpected)

    def test_ohbm2026_parquet_in_package_dir_is_unexpected(self) -> None:
        (self.pkg / "ohbm2026.parquet").write_bytes(b"x")
        with self.assertRaises(ArtifactDiscoveryError) as ctx:
            self._upload(FakeR2Client())
        self.assertIn("ohbm2026.parquet", ctx.exception.unexpected)


class HashMismatchGuardTests(_TempCwd):
    def test_existing_size_mismatch_raises(self) -> None:  # FR-016 edge case
        bad = {_key(self.ohbm): 999999}
        with self.assertRaises(ContentHashMismatchError) as ctx:
            self._upload(FakeR2Client(exists=bad))
        self.assertEqual(ctx.exception.key, _key(self.ohbm))


class DryRunTests(_TempCwd):
    def test_dry_run_no_upload_no_manifest(self) -> None:
        client = FakeR2Client(exists={})
        result = self._upload(client, dry_run=True)
        self.assertEqual(client.uploaded, [])
        self.assertIsNone(result.manifest)
        self.assertIsNone(result.manifest_path)
        self.assertEqual(set(result.channel_entry), ALL_LOGICAL)
        prov = Path("data/provenance")
        self.assertFalse(list(prov.glob("*.json")) if prov.exists() else [])


class ManifestSafetyTests(_TempCwd):
    def test_manifest_has_no_abs_path_and_no_secret(self) -> None:  # CA-004 / CA-008
        result = self._upload(FakeR2Client())
        text = result.manifest_path.read_text()
        data = json.loads(text)
        self.assertFalse(data["source_package_dir"].startswith(("/", "~")))
        self.assertNotIn("TOP_SECRET_VALUE", text)
        self.assertNotIn("AKIA_SECRET_KEYID", text)


if __name__ == "__main__":
    unittest.main()
