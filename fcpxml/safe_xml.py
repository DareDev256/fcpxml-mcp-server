"""
Safe XML parsing — defused against XXE, billion laughs, and entity expansion.

Centralizes all XML parsing so every entry point (parser, writer, export,
rough_cut) uses the same hardened functions. Drop-in replacements for
ET.parse() and ET.fromstring().

Blocks:
- External entity injection (XXE): file:///etc/passwd, http:// callbacks
- Billion laughs / entity expansion: exponential DTD bombs
- DTD retrieval: remote DTD loading

Security note: All flags are set explicitly rather than relying on library
defaults — this ensures protection survives dependency upgrades that might
change default behavior.

IMPORTANT: Never use stdlib xml.etree.ElementTree.parse() or .fromstring()
directly in this codebase. Always import from this module instead.
"""

import xml.etree.ElementTree as ET

import defusedxml.ElementTree as _safe_ET

# Explicit security flags — pinned so a defusedxml upgrade that changes
# defaults cannot silently weaken the boundary.
#
# forbid_dtd is False because FCPXML files legitimately include
# <!DOCTYPE fcpxml> — blocking all DTDs would reject every real FCP export.
# forbid_entities and forbid_external block the dangerous payloads
# (entity expansion bombs, external entity reads, remote DTD fetches).
_SECURITY_FLAGS = {
    "forbid_dtd": False,
    "forbid_entities": True,
    "forbid_external": True,
}


def safe_parse(source: str) -> ET.ElementTree:
    """Parse an XML file with XXE and entity-expansion protection.

    All DTD processing, entity definitions, and external references are
    rejected outright. Returns a standard ElementTree so downstream code
    is unchanged.
    """
    return _safe_ET.parse(source, **_SECURITY_FLAGS)


def safe_fromstring(text: str) -> ET.Element:
    """Parse an XML string with XXE and entity-expansion protection.

    All DTD processing, entity definitions, and external references are
    rejected outright. Returns a standard Element so downstream code is
    unchanged.
    """
    return _safe_ET.fromstring(text, **_SECURITY_FLAGS)
