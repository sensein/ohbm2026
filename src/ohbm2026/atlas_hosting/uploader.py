"""Upload a built atlas package to R2 under content-addressed keys.

Spec: ``specs/020-cloudflare-r2-migration/`` — US1 + US2,
``contracts/cli-upload-atlas-package.md``.

The uploader is idempotent and non-destructive: each artifact is keyed
by the SHA-256 of its bytes, an existing key is skipped (dedup), and a
new version only ever ADDS keys (FR-008/FR-009/FR-013). Artifact
discovery is runtime (Principle VII) — a missing required parquet or an
unexpected one fails loudly (:class:`ArtifactDiscoveryError`), and an
existing object whose size disagrees with the content-addressed key
fails loudly (:class:`ContentHashMismatchError`).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Tuple

from ohbm2026.artifacts import utc_now_isoformat
from ohbm2026.exceptions import ArtifactDiscoveryError, ContentHashMismatchError

from .content_hash import derive_object_key, public_url, sha256_file
from .manifest import (
    ContentAddressedObject,
    UploadManifest,
    build_channel_entry,
)
from .r2_client import R2Client, R2Settings

logger = logging.getLogger(__name__)

#: logical name → on-disk filename (the known artifact set).
FILENAME_BY_LOGICAL = {
    "ohbm2026": "ohbm2026.parquet",
    "neuroscape": "neuroscape.parquet",
    "atlas": "atlas.parquet",
    "neuroscape_vectors": "neuroscape_vectors.parquet",
}
LOGICAL_BY_FILENAME = {v: k for k, v in FILENAME_BY_LOGICAL.items()}
#: canonical emit order (required first, optional last).
_ORDER = ("ohbm2026", "neuroscape", "atlas", "neuroscape_vectors")
#: What `build-atlas-package --output-root` writes (all REQUIRED — the
#: production build runs with the semantic index ON, so
#: neuroscape_vectors.parquet is always present). NOTE: ohbm2026.parquet
#: is the Stage-10 INPUT (it lives under data/outputs/parquets/<key>/),
#: not a build output — it is supplied separately via ``--ohbm2026-parquet``.
_PACKAGE_DIR_LOGICAL = ("neuroscape", "atlas", "neuroscape_vectors")
_PACKAGE_DIR_REQUIRED = ("neuroscape", "atlas", "neuroscape_vectors")
_PACKAGE_DIR_FILENAMES = {FILENAME_BY_LOGICAL[n] for n in _PACKAGE_DIR_LOGICAL}

DEFAULT_MANIFEST_OUT = "data/provenance"


class _ClientLike(Protocol):
    def object_exists(self, key: str) -> Tuple[bool, Optional[int]]: ...
    def upload(self, key: str, path, **kwargs) -> None: ...


@dataclass
class UploadResult:
    manifest: Optional[UploadManifest]  # None under --dry-run
    channel_entry: dict
    summary: dict  # {"uploaded": int, "skipped": int}
    objects: list[ContentAddressedObject]
    dry_run: bool
    manifest_path: Optional[Path] = None


def discover_artifacts(
    package_dir: Path | str, ohbm2026_parquet: Path | str
) -> dict[str, Path]:
    """Return ``{logical_name: path}`` for the data bundle's artifacts.

    The bundle spans two locations (discovered at runtime, Principle
    VII): ``ohbm2026.parquet`` is the Stage-10 build (supplied via
    ``ohbm2026_parquet``, typically ``data/outputs/parquets/<key>/``),
    while ``neuroscape.parquet`` + ``atlas.parquet`` +
    ``neuroscape_vectors.parquet`` are what ``build-atlas-package``
    writes into ``package_dir`` (all three required — the production
    build keeps the semantic index ON). A missing required artifact or
    an unexpected ``*.parquet`` in ``package_dir`` raises
    :class:`ArtifactDiscoveryError`.
    """

    ohbm2026_parquet = Path(ohbm2026_parquet)
    if not ohbm2026_parquet.is_file():
        raise ArtifactDiscoveryError(
            f"ohbm2026 parquet not found: {ohbm2026_parquet}",
            path=str(ohbm2026_parquet),
            missing=[FILENAME_BY_LOGICAL["ohbm2026"]],
        )
    result: dict[str, Path] = {"ohbm2026": ohbm2026_parquet}

    package_dir = Path(package_dir)
    if not package_dir.is_dir():
        raise ArtifactDiscoveryError(
            f"package dir not found: {package_dir}", path=str(package_dir)
        )

    present = {p.name: p for p in sorted(package_dir.glob("*.parquet"))}

    unexpected = sorted(n for n in present if n not in _PACKAGE_DIR_FILENAMES)
    if unexpected:
        raise ArtifactDiscoveryError(
            f"unexpected parquet(s) in package dir: {', '.join(unexpected)}",
            path=str(package_dir),
            unexpected=unexpected,
        )

    missing = [
        FILENAME_BY_LOGICAL[name]
        for name in _PACKAGE_DIR_REQUIRED
        if FILENAME_BY_LOGICAL[name] not in present
    ]
    if missing:
        raise ArtifactDiscoveryError(
            f"missing required artifact(s) in package dir: {', '.join(missing)}",
            path=str(package_dir),
            missing=missing,
        )

    for name, path in present.items():
        result[LOGICAL_BY_FILENAME[name]] = path
    return result


def read_build_state_key(parquet_path: Path | str) -> Optional[str]:
    """Best-effort read of the source build's ``state_key`` from a parquet.

    Uses hyparquet-style predicate pushdown (``table_name == 'manifest'``)
    so only the manifest row group is read, not the whole envelope. The
    field is OPTIONAL provenance — any failure (not a parquet, no
    manifest row, unrecognised shape) returns ``None`` rather than
    aborting the upload.
    """

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pq.read_table(
            str(parquet_path),
            filters=[("table_name", "==", "manifest")],
            columns=["table_bytes"],
        )
        if table.num_rows == 0:
            return None
        blob = bytes(table.column("table_bytes")[0].as_py())
        rows = pq.read_table(pa.BufferReader(blob)).to_pylist()
        return _extract_state_key(rows[0]) if rows else None
    except Exception as exc:  # noqa: BLE001 — optional provenance; null is a valid, documented outcome
        logger.debug("build state_key unreadable from %s: %s", parquet_path, exc)
        return None


def _extract_state_key(row: dict) -> Optional[str]:
    """Pull a build ``state_key`` out of a manifest-table row.

    Handles the shapes seen across the bundle: a direct ``state_key``
    column; a ``build_info`` dict column; and (the atlas/neuroscape
    case) a ``manifest_json`` JSON string whose ``build_info.state_key``
    holds it. Returns ``None`` for any other shape.
    """

    if isinstance(row.get("state_key"), str):
        return row["state_key"]
    for column in ("build_info", "manifest_json"):
        value = row.get(column)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                continue
        if isinstance(value, dict):
            if isinstance(value.get("state_key"), str):
                return value["state_key"]
            build_info = value.get("build_info")
            if isinstance(build_info, dict) and isinstance(
                build_info.get("state_key"), str
            ):
                return build_info["state_key"]
    return None


def _read_code_revision() -> str:
    """Best-effort ``git rev-parse HEAD``; ``"unknown"`` if unavailable."""

    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def upload_atlas_package(
    package_dir: Path | str,
    *,
    ohbm2026_parquet: Path | str,
    settings: R2Settings,
    client: Optional[_ClientLike] = None,
    dry_run: bool = False,
    manifest_out: Path | str = DEFAULT_MANIFEST_OUT,
    code_revision: Optional[str] = None,
    command_line: str = "",
    uploaded_utc: Optional[str] = None,
) -> UploadResult:
    """Publish the data bundle to R2; return an :class:`UploadResult`.

    The bundle = ``ohbm2026_parquet`` (Stage-10 build) + the
    ``neuroscape``/``atlas`` (+ optional ``neuroscape_vectors``) parquets
    in ``package_dir`` (``build-atlas-package`` output). Existence is
    discovered per content-addressed key; absent keys are uploaded
    (skipped under ``dry_run``), present keys are skipped with a
    size-equality guard. Under ``dry_run`` no PUT is issued and no
    manifest is written.
    """

    package_dir = Path(package_dir)
    artifacts_paths = discover_artifacts(package_dir, ohbm2026_parquet)

    if client is None:
        # head_object existence checks run in dry-run too, so a client is
        # always needed (only the PUT + manifest write are skipped).
        client = R2Client.from_settings(settings)

    objects: list[ContentAddressedObject] = []
    uploaded = skipped = 0

    for logical in _ORDER:
        path = artifacts_paths.get(logical)
        if path is None:
            continue
        filename = FILENAME_BY_LOGICAL[logical]
        sha = sha256_file(path)
        size = path.stat().st_size
        key = derive_object_key(sha, filename, prefix=settings.key_prefix)
        url = public_url(settings.public_base_url, key)
        source_state_key = read_build_state_key(path)

        exists, remote_size = client.object_exists(key)
        if exists:
            if remote_size is not None and remote_size != size:
                raise ContentHashMismatchError(
                    "object at content-addressed key has unexpected size",
                    key=key,
                    expected=str(size),
                    actual=str(remote_size),
                )
            action = "skipped"
            skipped += 1
            logger.info("skip (already present): %s → %s", logical, key)
        else:
            if not dry_run:
                client.upload(key, path)
            action = "uploaded"
            uploaded += 1
            logger.info(
                "%s: %s → %s", "would upload" if dry_run else "uploaded", logical, key
            )

        objects.append(
            ContentAddressedObject(
                logical_name=logical,
                filename=filename,
                sha256=sha,
                size_bytes=size,
                object_key=key,
                public_url=url,
                source_build_state_key=source_state_key,
                action=action,
            )
        )

    channel_entry = build_channel_entry(objects)

    manifest: Optional[UploadManifest] = None
    manifest_path: Optional[Path] = None
    if not dry_run:
        manifest = UploadManifest(
            bucket=settings.bucket,
            public_base_url=settings.public_base_url,
            key_prefix=settings.key_prefix,
            code_revision=code_revision or _read_code_revision(),
            command_line=command_line,
            uploaded_utc=uploaded_utc or utc_now_isoformat(),
            source_package_dir=str(package_dir),
            artifacts=objects,
            channel_entry=channel_entry,
        )
        manifest_path = manifest.write(manifest_out)

    return UploadResult(
        manifest=manifest,
        channel_entry=channel_entry,
        summary={"uploaded": uploaded, "skipped": skipped},
        objects=objects,
        dry_run=dry_run,
        manifest_path=manifest_path,
    )
