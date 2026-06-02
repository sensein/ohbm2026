"""Tests for the Stage 20 upload manifest (provenance, CA-008).

Spec: ``specs/020-cloudflare-r2-migration/`` — data-model.md,
``contracts/upload-manifest.schema.json``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema

from ohbm2026 import artifacts
from ohbm2026.atlas_hosting.manifest import (
    ContentAddressedObject,
    UploadManifest,
    build_channel_entry,
)
from ohbm2026.exceptions import AtlasProvenanceError

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "specs/020-cloudflare-r2-migration/contracts/upload-manifest.schema.json"
)


def _object(logical: str, sha: str, action: str = "uploaded") -> ContentAddressedObject:
    filename = f"{logical}.parquet"
    return ContentAddressedObject(
        logical_name=logical,
        filename=filename,
        sha256=sha,
        size_bytes=1024,
        object_key=f"{sha}/{filename}",
        public_url=f"https://aadata.cirrusscience.org/{sha}/{filename}",
        source_build_state_key=None,
        action=action,
    )


def _manifest() -> UploadManifest:
    objs = [
        _object("ohbm2026", "a" * 64),
        _object("neuroscape", "b" * 64),
        _object("atlas", "c" * 64),
        _object("neuroscape_vectors", "d" * 64),
    ]
    return UploadManifest(
        bucket="aadata",
        public_base_url="https://aadata.cirrusscience.org",
        key_prefix="",
        code_revision="deadbeef",
        command_line="ohbmcli upload-atlas-package --package-dir data/outputs/atlas-package__x",
        uploaded_utc="2026-05-31T12:00:00+00:00",
        source_package_dir="data/outputs/atlas-package__x",
        artifacts=objs,
        channel_entry=build_channel_entry(objs),
        cache_control="public, max-age=31536000, immutable",
    )


class UploadStateKeyTests(unittest.TestCase):
    def test_deterministic_stable_hash(self) -> None:
        m = _manifest()
        expected = artifacts._stable_hash(
            {
                "bucket": "aadata",
                "key_prefix": "",
                "artifacts": sorted(
                    [
                        ("ohbm2026", "a" * 64),
                        ("neuroscape", "b" * 64),
                        ("atlas", "c" * 64),
                        ("neuroscape_vectors", "d" * 64),
                    ]
                ),
            }
        )
        self.assertEqual(m.upload_state_key, expected)
        # Stable across reconstruction.
        self.assertEqual(m.upload_state_key, _manifest().upload_state_key)


class CachePolicyProvenanceTests(unittest.TestCase):
    """Spec 022 (US2 / FR-010) — the applied cache policy is recorded."""

    def test_to_dict_records_cache_control(self) -> None:
        d = _manifest().to_dict()
        self.assertEqual(d["cache_control"], "public, max-age=31536000, immutable")

    def test_cache_control_roundtrips(self) -> None:
        again = UploadManifest.from_dict(_manifest().to_dict())
        self.assertEqual(again.cache_control, "public, max-age=31536000, immutable")

    def test_from_dict_defaults_cache_control_for_legacy_manifests(self) -> None:
        raw = _manifest().to_dict()
        del raw["cache_control"]  # a pre-spec-022 manifest
        self.assertEqual(UploadManifest.from_dict(raw).cache_control, "")


class RoundTripTests(unittest.TestCase):
    def test_to_from_dict_roundtrip(self) -> None:
        m = _manifest()
        again = UploadManifest.from_dict(m.to_dict())
        self.assertEqual(again.to_dict(), m.to_dict())


class SchemaValidationTests(unittest.TestCase):
    def test_to_dict_validates_against_contract_schema(self) -> None:
        schema = json.loads(_SCHEMA_PATH.read_text())
        jsonschema.validate(instance=_manifest().to_dict(), schema=schema)


class ProvenancePathSafetyTests(unittest.TestCase):
    def test_absolute_source_package_dir_rejected(self) -> None:
        objs = [_object("ohbm2026", "a" * 64), _object("neuroscape", "b" * 64), _object("atlas", "c" * 64)]
        with self.assertRaises(AtlasProvenanceError):
            UploadManifest(
                bucket="aadata",
                public_base_url="https://aadata.cirrusscience.org",
                key_prefix="",
                code_revision="deadbeef",
                command_line="x",
                uploaded_utc="2026-05-31T12:00:00+00:00",
                source_package_dir="/Users/op/data/outputs/atlas-package__x",
                artifacts=objs,
                channel_entry=build_channel_entry(objs),
            )


if __name__ == "__main__":
    unittest.main()
