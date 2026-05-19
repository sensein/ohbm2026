"""pandoc subprocess wrappers for PDF + DOCX output.

PDF path: pandoc + xelatex with the LaTeX preamble (`-H header...`),
`\\makeindex` + `\\printindex` already in the markdown source. After
pandoc emits the PDF we strip the embedded timestamps for
determinism (R6).

DOCX path: implemented in T033 (US3). Currently a stub that raises;
keeps the import surface stable so the CLI can lazy-load it.
"""

from __future__ import annotations

import datetime as _dt
import io
import pathlib
import re
import shutil
import subprocess
import zipfile
from importlib import resources

from ohbm2026.exceptions import BookBuildError


def _which_or_raise(binary: str, hint: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise BookBuildError(
            f"required system dep `{binary}` not on PATH; {hint}",
            details=f"shutil.which({binary!r}) returned None",
        )
    return path


def resolve_pdf_engine() -> tuple[str, str] | None:
    """Return `(binary_name, version_line)` of the first LaTeX engine
    on PATH that pandoc accepts as `--pdf-engine`.

    Preference order: `xelatex` (TeX Live / MacTeX) → `tectonic`
    (lighter, on-demand-fetch). Returns None when neither is available.
    """
    for binary in ("xelatex", "tectonic"):
        path = shutil.which(binary)
        if path:
            return binary, _first_line(subprocess.check_output([path, "--version"]))
    return None


def preflight(*, need_xelatex: bool) -> dict[str, str]:
    """Verify pandoc + (optionally) a LaTeX engine are on PATH.

    Returns a dict of `{name: version_line}` for provenance capture.
    Raises BookBuildError with an operator-actionable install hint
    when a binary is absent. `xelatex` and `tectonic` are accepted
    interchangeably — pandoc handles both as a `--pdf-engine`.
    """
    versions: dict[str, str] = {}
    pandoc = _which_or_raise(
        "pandoc",
        "install via `brew install pandoc` (macOS) or "
        "`apt-get install pandoc` (Linux). See quickstart.md step 2.",
    )
    versions["pandoc"] = _first_line(subprocess.check_output([pandoc, "--version"]))
    if need_xelatex:
        engine = resolve_pdf_engine()
        if engine is None:
            raise BookBuildError(
                "neither `xelatex` nor `tectonic` is on PATH; install one "
                "(Tectonic recommended for lightness: `brew install tectonic` "
                "or full TeX Live `apt-get install texlive-xetex`). "
                "See quickstart.md step 2.",
                details=f"shutil.which('xelatex')={shutil.which('xelatex')!r}, "
                f"shutil.which('tectonic')={shutil.which('tectonic')!r}",
            )
        binary, version_line = engine
        # The provenance schema field stays `xelatex_version` to keep
        # the contract stable — value records which engine actually ran.
        versions["xelatex"] = f"{binary}: {version_line}"
    return versions


def _first_line(b: bytes) -> str:
    return b.decode("utf-8", errors="replace").splitlines()[0].strip()


def _header_includes_path(style: str) -> pathlib.Path:
    """Return the absolute path to the right LaTeX header-includes
    file (plain vs tufte-book). Files live alongside the book
    package so the operator never has to manage them.
    """
    pkg = resources.files("ohbm2026.book.templates")
    if style == "tufte":
        return pathlib.Path(str(pkg.joinpath("header-includes-tufte.tex")))
    return pathlib.Path(str(pkg.joinpath("header-includes.tex")))


def to_pdf(
    md_path: pathlib.Path,
    output_path: pathlib.Path,
    *,
    style: str = "plain",
    strip_metadata: bool = True,
) -> None:
    """Run pandoc + xelatex against `md_path`, writing `output_path`.

    Strips `/CreationDate` + `/ModDate` from the resulting PDF for
    determinism (R6) unless `strip_metadata` is False (debug only).
    """
    pandoc = shutil.which("pandoc") or _which_or_raise(
        "pandoc", "see quickstart.md step 2"
    )
    engine = resolve_pdf_engine()
    if engine is None:
        raise BookBuildError(
            "neither `xelatex` nor `tectonic` is on PATH; install one. "
            "See quickstart.md step 2.",
        )
    engine_binary = engine[0]

    header_includes = _header_includes_path(style)
    if not header_includes.exists():
        raise BookBuildError(
            f"header-includes file missing at {header_includes} "
            f"(style={style!r})"
        )

    resource_path = md_path.parent
    argv = [
        pandoc,
        str(md_path),
        # `-strikeout` disables pandoc's `~~strikethrough~~` markdown
        # extension — that's the writer that emits `\sout{}` calls,
        # which fail under the `soul` LaTeX package on complex content
        # (e.g. citations + math + accented chars in the strikeout
        # span). A book of abstracts has no legitimate strikethrough,
        # so dropping the extension is purely defensive.
        "--from=markdown+raw_tex+pandoc_title_block-strikeout",
        "--to=pdf",
        f"--pdf-engine={engine_binary}",
        "-H",
        str(header_includes),
        f"--resource-path={resource_path}",
        "--standalone",
        "--toc",
        "-o",
        str(output_path),
    ]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BookBuildError(
            f"pandoc returned non-zero ({proc.returncode}) building PDF",
            details=(proc.stderr or "").strip(),
        )

    if strip_metadata:
        _strip_pdf_metadata(output_path)


def _strip_pdf_metadata(pdf_path: pathlib.Path) -> None:
    """Overwrite /CreationDate + /ModDate to a fixed epoch (R6)."""
    import pikepdf

    fixed = "D:19700101000000Z"
    with pikepdf.Pdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        with pdf.open_metadata() as meta:
            # pikepdf's metadata helper handles XMP — clear the
            # producer/creator stamps too so two pandoc versions
            # produce the same body.
            for k in ("xmp:CreateDate", "xmp:ModifyDate", "xmp:MetadataDate"):
                if k in meta:
                    del meta[k]
        info = pdf.trailer.get("/Info")
        if info is not None:
            info["/CreationDate"] = fixed
            info["/ModDate"] = fixed
        pdf.save(pdf_path)


def to_docx(
    md_path: pathlib.Path,
    output_path: pathlib.Path,
    *,
    strip_metadata: bool = True,
) -> None:
    """Run pandoc against `md_path`, writing a `.docx` to `output_path`.

    Strips `docProps/core.xml` timestamps for determinism (R6) unless
    `strip_metadata` is False. Pandoc's docx writer doesn't emit
    PAGEREF field codes, so the author index in the resulting docx
    uses clickable anchor cross-references — documented limitation
    in `contracts/cli.md § Known limitations`.
    """
    pandoc = shutil.which("pandoc") or _which_or_raise(
        "pandoc", "see quickstart.md step 2"
    )
    resource_path = md_path.parent
    argv = [
        pandoc,
        str(md_path),
        "--from=markdown+raw_tex",
        "--to=docx",
        f"--resource-path={resource_path}",
        "--standalone",
        "-o",
        str(output_path),
    ]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BookBuildError(
            f"pandoc returned non-zero ({proc.returncode}) building DOCX",
            details=(proc.stderr or "").strip(),
        )

    if strip_metadata:
        _strip_docx_metadata(output_path)


def _strip_docx_metadata(docx_path: pathlib.Path) -> None:
    """Rewrite docProps/core.xml created/modified to a fixed epoch +
    rebuild the zip with sorted entries and zeroed mtimes (R6).
    """
    fixed_iso = "1970-01-01T00:00:00Z"
    payload: dict[str, bytes] = {}
    with zipfile.ZipFile(docx_path, "r") as zin:
        for name in zin.namelist():
            payload[name] = zin.read(name)

    core_xml = payload.get("docProps/core.xml")
    if core_xml is not None:
        text = core_xml.decode("utf-8", errors="replace")
        # Both dcterms:created and dcterms:modified carry an ISO-8601
        # value. Replace them in-place; pattern is permissive (no DTD
        # validation required).
        text = re.sub(
            r"(<dcterms:created[^>]*>)[^<]*(</dcterms:created>)",
            rf"\g<1>{fixed_iso}\g<2>",
            text,
        )
        text = re.sub(
            r"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
            rf"\g<1>{fixed_iso}\g<2>",
            text,
        )
        payload["docProps/core.xml"] = text.encode("utf-8")

    # Re-zip with sorted entry order + zeroed mtimes + deterministic
    # compression so two runs produce byte-identical .docx files.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        for name in sorted(payload):
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(info, payload[name])
    docx_path.write_bytes(buf.getvalue())
