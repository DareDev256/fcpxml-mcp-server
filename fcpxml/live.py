"""Live mode v1 — officially-supported control of a running Final Cut Pro.

This module is the first piece of the dual-mode (XML + Live) architecture
(see docs/CAPABILITY-AUDIT-2026-06.md).  Everything here rides Apple's
sanctioned surfaces only — no injection, no private APIs, no accessibility
scripting:

- **push_to_fcp** — programmatic FCPXML *import* via the Open Document
  Apple event, Apple's documented zero-click ingestion path.  Behavior is
  steered by an ``<import-options>`` element injected into the document
  (library location, suppress warnings, copy assets).

Live-verified findings (FCP 12.2, 2026-06-11) that shape the contract:

1. **Truly zero-click requires a ``.fcpbundle`` library location.**  Given
   a new ``.fcpbundle`` path, FCP silently creates the library + a dated
   event and imports.  With NO location, or a ``.fcplibrary``/bare path,
   FCP raises a modal "Open Library" picker — a *required choice* that
   ``suppress warnings`` does not cover — and the Apple event blocks until
   a human answers.  ``inject_import_options`` therefore normalises the
   location to ``.fcpbundle``.
2. **Media-identity collisions** — importing a project whose media already
   exists in the target library fails with "the media already exists with a
   unique identifier".  Push into a fresh library, or reuse the exact asset
   IDs FCP already holds.
- **list_fcp_libraries** — FCP 12's AppleScript dictionary is read-only
  library inspection (suite ``com.apple.FinalCut.library.inspection``);
  we use it to enumerate open libraries → events → projects.

The asymmetry is structural: import is scriptable, but Apple offers NO
programmatic export — reading back the user's current timeline still
requires a manual File > Export XML.  Live mode therefore *pushes*;
round-trips come back through the XML tools.

macOS notes: ``osascript`` targeting Final Cut Pro requires the host
process to hold an Apple Events automation grant (System Settings →
Privacy & Security → Automation) — the first call triggers the consent
prompt.  ``tell application "Final Cut Pro"`` launches FCP if it is not
already running; ``list_fcp_libraries`` checks first and declines to
launch, while ``push_to_fcp`` launching FCP is the point.
"""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

_OSASCRIPT_TIMEOUT_SECONDS = 120  # FCP cold-launch + import can be slow
_FCP_BUNDLE_ID = "com.apple.FinalCut"

# Field separators for AppleScript list output — ASCII unit/record
# separators cannot appear in user-facing library/project names.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"


def _applescript_quote(value: str) -> str:
    """Escape a string for embedding in a double-quoted AppleScript literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=_OSASCRIPT_TIMEOUT_SECONDS,
    )


def fcp_is_running() -> bool:
    """True when a Final Cut Pro process is active (no launch side-effect)."""
    proc = subprocess.run(
        ["pgrep", "-x", "Final Cut Pro"], capture_output=True, text=True
    )
    return proc.returncode == 0


def inject_import_options(
    fcpxml_path: str,
    output_path: str,
    library_location: Optional[str] = None,
    suppress_warnings: bool = True,
    copy_assets: Optional[bool] = None,
) -> str:
    """Write a copy of *fcpxml_path* with an ``<import-options>`` element.

    The DTD requires ``import-options`` as the FIRST child of ``<fcpxml>``
    (``<!ELEMENT fcpxml (import-options?, resources?, ...)>``).  Any
    existing import-options element is replaced.

    Args:
        fcpxml_path: Source ``.fcpxml`` document.
        output_path: Where to write the import-ready copy.
        library_location: Path or ``file://`` URL of the target library
            (FCP creates the library if none exists there).
        suppress_warnings: Suppress non-fatal import warning dialogs.
        copy_assets: True = copy media into the library, False = link
            in place, None = let FCP use its default.

    Returns:
        *output_path*.
    """
    from .safe_xml import safe_parse
    from .writer import write_fcpxml

    tree = safe_parse(fcpxml_path)
    root = tree.getroot()

    for stale in root.findall('import-options'):
        root.remove(stale)

    options = ET.Element('import-options')
    if library_location:
        loc = library_location
        if not loc.startswith('file://'):
            from urllib.parse import quote
            resolved = Path(loc).expanduser()
            # Live-verified on FCP 12.2: FCP auto-creates a library ONLY when
            # the location carries the .fcpbundle extension.  A bare directory
            # or a .fcplibrary path triggers the modal "Open Library" picker
            # (a required choice that `suppress warnings` does NOT dismiss),
            # which blocks the Apple event.  Normalise to .fcpbundle.
            if resolved.suffix.lower() != '.fcpbundle':
                resolved = resolved.with_suffix('.fcpbundle')
            loc = 'file://' + quote(str(resolved.resolve()))
        ET.SubElement(options, 'option', key='library location', value=loc)
    ET.SubElement(
        options, 'option',
        key='suppress warnings', value='1' if suppress_warnings else '0',
    )
    if copy_assets is not None:
        ET.SubElement(
            options, 'option',
            key='copy assets', value='1' if copy_assets else '0',
        )
    root.insert(0, options)

    write_fcpxml(root, output_path)
    return output_path


def push_to_fcp(
    fcpxml_path: str,
    library_location: Optional[str] = None,
    suppress_warnings: bool = True,
    copy_assets: Optional[bool] = None,
    import_copy_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Send an FCPXML document to Final Cut Pro via the Open Document event.

    This is Apple's documented programmatic-import path: FCP ingests the
    document without any clicks, creating libraries/events as directed by
    ``<import-options>``.  Launches FCP when it isn't running.

    Args:
        fcpxml_path: ``.fcpxml`` file or ``.fcpxmld`` bundle to import.
        library_location: Target library path/URL (created if absent).
        suppress_warnings: Suppress non-fatal import warning dialogs.
        copy_assets: Copy media into the library vs. link in place.
        import_copy_path: Where to write the options-injected copy for
            flat files (defaults handled by the caller; required when
            options are used on a flat file).

    Returns:
        Dict with ``sent`` (path actually opened), ``launched_fcp``
        (whether FCP was started by this call), and ``stdout``.

    Raises:
        RuntimeError: When osascript fails (most commonly a missing
            Automation permission grant for the host process).
    """
    path = Path(fcpxml_path)
    send_path = path

    # Bundles: open directly (option injection inside a copied bundle is
    # a v0.10 refinement); flat files get an import-ready copy so the
    # user's original is never touched.
    if path.suffix.lower() != '.fcpxmld' and import_copy_path:
        send_path = Path(
            inject_import_options(
                str(path),
                import_copy_path,
                library_location=library_location,
                suppress_warnings=suppress_warnings,
                copy_assets=copy_assets,
            )
        )

    was_running = fcp_is_running()
    script = (
        'tell application "Final Cut Pro"\n'
        'activate\n'
        f'open POSIX file "{_applescript_quote(str(send_path.resolve()))}"\n'
        'end tell'
    )
    proc = _run_osascript(script)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        hint = ""
        if "-1743" in stderr or "not allowed" in stderr.lower():
            hint = (
                " — grant Automation permission: System Settings → "
                "Privacy & Security → Automation → allow your terminal/MCP "
                "host to control Final Cut Pro, then retry"
            )
        raise RuntimeError(f"osascript failed: {stderr}{hint}")

    return {
        "sent": str(send_path),
        "launched_fcp": not was_running,
        "stdout": proc.stdout.strip(),
    }


def list_fcp_libraries(allow_launch: bool = False) -> List[Dict[str, Any]]:
    """Enumerate open libraries → events → projects via AppleScript.

    Uses FCP 12's read-only scripting dictionary.  By default this
    refuses to launch FCP (``tell application`` would start it);
    pass ``allow_launch=True`` to override.

    Returns:
        List of ``{name, events: [{name, projects: [str, ...]}, ...]}``.

    Raises:
        RuntimeError: FCP not running (and *allow_launch* False), or
            osascript failure.
    """
    if not allow_launch and not fcp_is_running():
        raise RuntimeError(
            "Final Cut Pro is not running (pass allow_launch=true to start it)"
        )

    script = (
        'set fieldSep to (ASCII character 31)\n'
        'set recSep to (ASCII character 30)\n'
        'set out to ""\n'
        'tell application "Final Cut Pro"\n'
        '  repeat with lib in libraries\n'
        '    set libName to name of lib\n'
        '    repeat with evt in (events of lib)\n'
        '      set evtName to name of evt\n'
        '      set projNames to ""\n'
        '      repeat with proj in (projects of evt)\n'
        '        set projNames to projNames & (name of proj) & fieldSep\n'
        '      end repeat\n'
        '      set out to out & libName & fieldSep & evtName & fieldSep '
        '& projNames & recSep\n'
        '    end repeat\n'
        '    if (count of events of lib) is 0 then\n'
        '      set out to out & libName & fieldSep & recSep\n'
        '    end if\n'
        '  end repeat\n'
        'end tell\n'
        'return out'
    )
    proc = _run_osascript(script)
    if proc.returncode != 0:
        raise RuntimeError(f"osascript failed: {proc.stderr.strip()}")

    libraries: Dict[str, Dict[str, Any]] = {}
    for record in proc.stdout.strip().split(_RECORD_SEP):
        record = record.strip('\n')
        if not record:
            continue
        fields = record.split(_FIELD_SEP)
        lib_name = fields[0]
        lib = libraries.setdefault(lib_name, {"name": lib_name, "events": []})
        if len(fields) >= 2 and fields[1]:
            projects = [p for p in fields[2:] if p]
            lib["events"].append({"name": fields[1], "projects": projects})
    return list(libraries.values())
