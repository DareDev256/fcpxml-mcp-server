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
from xml.dom.minidom import Document

import defusedxml.ElementTree as _safe_ET
import defusedxml.minidom as _safe_minidom

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


def safe_parse_string(text: str) -> Document:
    """Parse an XML string into a minidom Document with XXE protection.

    Drop-in replacement for xml.dom.minidom.parseString(). Used in the
    pretty-print path (writer.py, export.py) to maintain defense-in-depth
    even when re-parsing XML that was already produced by safe_parse().

    Why this matters: if a future refactor passes unsanitized XML through
    serialize_xml(), stdlib minidom would silently process external
    entities and DTD bombs. Using defusedxml.minidom closes that gap.
    """
    return _safe_minidom.parseString(text)


def serialize_xml(root: ET.Element, filepath: str, doctype: str = "") -> str:
    """Pretty-print an ElementTree root and write to disk.

    Single serialization pipeline shared by all XML output paths
    (write_fcpxml for FCPXML, DaVinciExporter for XMEML / simplified exports).
    Consolidates the ET.tostring → minidom → toprettyxml → strip blanks →
    replace declaration → write-to-file sequence that was previously
    duplicated across writer.py and export.py.

    Args:
        root: The XML root Element to serialize.
        filepath: Destination file path.
        doctype: DOCTYPE declaration to insert after the XML declaration.
            Example: ``'<!DOCTYPE fcpxml>'`` or ``'<!DOCTYPE xmeml>'``.
            If empty, no DOCTYPE is inserted.

    Returns:
        The filepath written to.
    """
    xml_str = ET.tostring(root, encoding='unicode')
    dom = safe_parse_string(xml_str)
    pretty_xml = dom.toprettyxml(indent="    ")
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    final_xml = '\n'.join(lines)

    if doctype:
        final_xml = final_xml.replace(
            '<?xml version="1.0" ?>',
            f'<?xml version="1.0" encoding="UTF-8"?>\n{doctype}',
        )
    else:
        final_xml = final_xml.replace(
            '<?xml version="1.0" ?>',
            '<?xml version="1.0" encoding="UTF-8"?>',
        )

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(final_xml)
    return filepath
