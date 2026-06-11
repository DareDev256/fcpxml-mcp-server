"""Validate FCPXML against Apple's official DTDs.

Apple stopped publishing FCPXML DTDs online after version 1.10 — the only
authoritative spec is the set of DTD files shipped inside the Final Cut
Pro app bundle (FCPXMLv1_0.dtd through FCPXMLv1_14.dtd as of FCP 12.x).
This module locates those DTDs on the local machine and validates
generated FCPXML against them with ``xmllint``.

Validation is strictly opt-in/best-effort: on machines without Final Cut
Pro (CI, Linux, servers) every helper degrades to "DTDs unavailable"
rather than failing, so the server never *requires* FCP to be installed.

Set ``FCPXML_DTD_DIR`` to point at a directory of ``FCPXMLv*_*.dtd``
files to validate without an FCP install (e.g. DTDs copied to a CI
runner — note Apple's DTDs are Apple-copyrighted, so they are located
at runtime rather than redistributed with this project).
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# Where FCP 10.6+ keeps its DTDs (verified against FCP 12.2)
_INTERCHANGE_RESOURCES = Path(
    "/Applications/Final Cut Pro.app/Contents/Frameworks/"
    "Interchange.framework/Versions/A/Resources"
)

_XMLLINT_TIMEOUT_SECONDS = 30


def dtd_search_dir() -> Path:
    """Directory searched for Apple FCPXML DTDs (env-overridable)."""
    return Path(os.environ.get("FCPXML_DTD_DIR", str(_INTERCHANGE_RESOURCES)))


def find_apple_dtd(version: str) -> Optional[Path]:
    """Locate the Apple DTD for an FCPXML *version* (e.g. ``"1.13"``).

    Returns None when the DTD (or the whole directory) is absent —
    typically a machine without Final Cut Pro installed.
    """
    safe = version.strip()
    if not safe.replace(".", "").isdigit():
        return None
    candidate = dtd_search_dir() / f"FCPXMLv{safe.replace('.', '_')}.dtd"
    return candidate if candidate.is_file() else None


def available_dtd_versions() -> list[str]:
    """List FCPXML versions with a locally available Apple DTD."""
    directory = dtd_search_dir()
    if not directory.is_dir():
        return []
    versions = []
    for dtd in directory.glob("FCPXMLv*_*.dtd"):
        versions.append(dtd.stem.removeprefix("FCPXMLv").replace("_", "."))
    return sorted(versions, key=lambda v: [int(p) for p in v.split(".")])


def validate_against_dtd(
    fcpxml_path: str,
    version: Optional[str] = None,
) -> Tuple[Optional[bool], str]:
    """Validate an FCPXML file against Apple's DTD via ``xmllint``.

    Args:
        fcpxml_path: Path to a ``.fcpxml`` file or ``.fcpxmld`` bundle.
        version: FCPXML version to validate against.  Defaults to the
            file's own ``version`` attribute.

    Returns:
        ``(ok, detail)`` where *ok* is True (valid), False (invalid), or
        None (validation unavailable: no xmllint, no DTD on this
        machine, or unreadable input — *detail* says which).
    """
    path = Path(fcpxml_path)
    if path.suffix.lower() == ".fcpxmld":
        path = path / "Info.fcpxml"
    if not path.is_file():
        return None, f"File not found: {path}"

    if shutil.which("xmllint") is None:
        return None, "xmllint not available on PATH"

    if version is None:
        # Cheap version sniff without a full parse
        from .safe_xml import safe_parse

        version = safe_parse(str(path)).getroot().get("version", "1.13")

    dtd = find_apple_dtd(version)
    if dtd is None:
        return None, (
            f"No Apple DTD for FCPXML {version} found in {dtd_search_dir()} "
            f"(Final Cut Pro not installed? Set FCPXML_DTD_DIR to override)"
        )

    # xmllint treats the --dtdvalid argument as a URI: raw paths containing
    # spaces (e.g. ".../Final Cut Pro.app/...") fail entity resolution with
    # "xmlSAX2ResolveEntity".  Path.as_uri() percent-encodes them.
    proc = subprocess.run(
        ["xmllint", "--noout", "--dtdvalid", dtd.resolve().as_uri(), str(path)],
        capture_output=True,
        text=True,
        timeout=_XMLLINT_TIMEOUT_SECONDS,
    )
    if proc.returncode == 0:
        return True, f"Valid against FCPXML {version} DTD ({dtd.name})"
    return False, proc.stderr.strip() or f"xmllint exit code {proc.returncode}"
