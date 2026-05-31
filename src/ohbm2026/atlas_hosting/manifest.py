"""Upload manifest — machine-readable provenance for an R2 publish run.

Spec: ``specs/020-cloudflare-r2-migration/`` — data-model.md, CA-008.
Schema: ``contracts/upload-manifest.schema.json``.

The manifest is the data bundle's provenance record (Principle VIII): it
links each published content-addressed object to its source build and
records the run's code revision / command line / timestamp. It carries
NO secret (only bucket name, public base URL, content hashes, and
public URLs) and NO absolute or user-home path — ``source_package_dir``
is forced through :func:`ohbm2026.atlas_package.provenance.normalise_path`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ohbm2026.artifacts import _stable_hash
from ohbm2026.atlas_package.provenance import normalise_path

SCHEMA_VERSION = "atlas_upload_manifest.v1"

#: Registry subkeys, in canonical order. All four are required — the
#: production build ships the semantic-index sidecar
#: (neuroscape_vectors.parquet) by default (spec 019).
LOGICAL_NAMES = ("ohbm2026", "neuroscape", "atlas", "neuroscape_vectors")
REQUIRED_LOGICAL = ("ohbm2026", "neuroscape", "atlas", "neuroscape_vectors")


@dataclass(frozen=True)
class ContentAddressedObject:
    """One atlas-package artifact as published to R2."""

    logical_name: str
    filename: str
    sha256: str
    size_bytes: int
    object_key: str
    public_url: str
    source_build_state_key: Optional[str]
    action: str  # "uploaded" | "skipped"

    def to_dict(self) -> dict:
        return {
            "logical_name": self.logical_name,
            "filename": self.filename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "object_key": self.object_key,
            "public_url": self.public_url,
            "source_build_state_key": self.source_build_state_key,
            "action": self.action,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContentAddressedObject":
        return cls(
            logical_name=data["logical_name"],
            filename=data["filename"],
            sha256=data["sha256"],
            size_bytes=int(data["size_bytes"]),
            object_key=data["object_key"],
            public_url=data["public_url"],
            source_build_state_key=data.get("source_build_state_key"),
            action=data["action"],
        )


def build_channel_entry(objects: list[ContentAddressedObject]) -> dict:
    """Registry-shaped ``{logical_name: {url, sha256}}`` for the objects.

    Shape matches the existing ``OHBM2026_UI_DATA_PACKAGE_URLS`` channel
    value so the operator can paste it straight into the GitHub variable.
    """

    return {
        obj.logical_name: {"url": obj.public_url, "sha256": obj.sha256}
        for obj in objects
    }


@dataclass
class UploadManifest:
    bucket: str
    public_base_url: str
    key_prefix: str
    code_revision: str
    command_line: str
    uploaded_utc: str
    source_package_dir: str
    artifacts: list[ContentAddressedObject]
    channel_entry: dict

    def __post_init__(self) -> None:
        # CA-008: the recorded package dir MUST be repo-relative. This
        # raises AtlasProvenanceError on an absolute / ~ path rather than
        # silently stripping the prefix (Principle VI).
        self.source_package_dir = normalise_path(
            self.source_package_dir, field="source_package_dir"
        )

    @property
    def upload_state_key(self) -> str:
        basis = {
            "bucket": self.bucket,
            "key_prefix": self.key_prefix,
            "artifacts": sorted((o.logical_name, o.sha256) for o in self.artifacts),
        }
        return _stable_hash(basis)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "upload_state_key": self.upload_state_key,
            "bucket": self.bucket,
            "public_base_url": self.public_base_url,
            "key_prefix": self.key_prefix,
            "code_revision": self.code_revision,
            "command_line": self.command_line,
            "uploaded_utc": self.uploaded_utc,
            "source_package_dir": self.source_package_dir,
            "artifacts": [o.to_dict() for o in self.artifacts],
            "channel_entry": self.channel_entry,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UploadManifest":
        return cls(
            bucket=data["bucket"],
            public_base_url=data["public_base_url"],
            key_prefix=data["key_prefix"],
            code_revision=data["code_revision"],
            command_line=data["command_line"],
            uploaded_utc=data["uploaded_utc"],
            source_package_dir=data["source_package_dir"],
            artifacts=[ContentAddressedObject.from_dict(a) for a in data["artifacts"]],
            channel_entry=data["channel_entry"],
        )

    def write(self, out_dir: Path | str) -> Path:
        """Write the manifest JSON to
        ``<out_dir>/atlas_upload_provenance__<upload_state_key>.json``.
        """

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"atlas_upload_provenance__{self.upload_state_key}.json"
        out_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True))
        return out_path
