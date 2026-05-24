"""Stage 15 provenance helpers.

Spec: ``specs/015-neuroscape-context/`` — CA-008 + research R-009.

The provenance file is the single audit record for an
``ohbmcli build-atlas-package`` run; it MUST contain only repo-
relative paths so the bundle is portable to other machines (Principle
VIII — no absolute or user-home paths anywhere in the record).

This module exposes ``normalise_path``, the gate used by every Stage
15 callsite that records a filesystem path into provenance. The
function returns a repo-relative ``str`` on the happy path and raises
:class:`ohbm2026.exceptions.AtlasProvenanceError` with structured
kwargs on violation.

Per Principle VI the rejection is loud — there is no silent fallback
that strips the offending prefix.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Union

from ohbm2026.exceptions import AtlasProvenanceError

__all__ = ["normalise_path"]


PathLike = Union[str, Path]


def normalise_path(path: PathLike, *, field: str | None = None) -> str:
    """Return ``path`` as a repo-relative ``str``, or raise.

    A path is **accepted** when it is repo-relative — that is, it does
    not start with ``/`` or ``~`` and does not escape the repo root
    after normalisation. Internal ``..`` segments that cancel out
    against earlier segments (e.g. ``data/cache/../outputs/foo``) are
    accepted and rewritten to their canonical form.

    A path is **rejected** when:

    - it is an absolute path (POSIX ``/...`` or Windows ``C:\\...``);
    - it begins with ``~`` (user-home reference);
    - normalisation produces a leading ``..`` segment (the path
      escapes the repo root);
    - it is the empty string.

    Parameters
    ----------
    path:
        The path to normalise. May be a ``str`` or a
        :class:`pathlib.Path`.
    field:
        Optional name of the provenance field that contributed this
        path. Propagated into the raised exception so the operator can
        identify the offending field without scanning the full
        record.

    Raises
    ------
    AtlasProvenanceError
        Raised on any rejection above; carries ``field``, ``expected``,
        and ``actual`` kwargs.
    """

    raw = str(path)

    if raw == "":
        raise AtlasProvenanceError(
            "empty path in provenance",
            field=field,
            expected="<repo-relative>",
            actual="",
        )

    if raw.startswith("~"):
        raise AtlasProvenanceError(
            "user-home (~)-relative path in provenance",
            field=field,
            expected="<repo-relative>",
            actual=raw,
        )

    candidate = Path(raw)
    if candidate.is_absolute():
        raise AtlasProvenanceError(
            "absolute path in provenance",
            field=field,
            expected="<repo-relative>",
            actual=raw,
        )

    # PurePosixPath normalisation handles the legitimate `a/b/../c`
    # case without touching the filesystem. We then re-check the
    # resulting parts: any leading `..` means the path escapes the
    # repo root, which is rejected loudly.
    parts: list[str] = []
    for piece in candidate.parts:
        if piece in ("", "."):
            continue
        if piece == "..":
            if not parts:
                # Leading `..` — escape attempt.
                raise AtlasProvenanceError(
                    "parent-escape path in provenance",
                    field=field,
                    expected="<repo-relative>",
                    actual=raw,
                )
            parts.pop()
            continue
        parts.append(piece)

    return str(PurePosixPath(*parts)) if parts else "."
