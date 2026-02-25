"""
Safe XML parsing — defused against XXE, billion laughs, and entity expansion.

Centralizes all XML parsing so every entry point (parser, writer, export,
rough_cut) uses the same hardened functions. Drop-in replacements for
ET.parse() and ET.fromstring().

Blocks:
- External entity injection (XXE): file:///etc/passwd, http:// callbacks
- Billion laughs / entity expansion: exponential DTD bombs
- DTD retrieval: remote DTD loading
"""

import xml.etree.ElementTree as ET

import defusedxml.ElementTree as _safe_ET


def safe_parse(source: str) -> ET.ElementTree:
    """Parse an XML file with XXE and entity-expansion protection.

    Returns a standard ElementTree so downstream code is unchanged.
    """
    return _safe_ET.parse(source)


def safe_fromstring(text: str) -> ET.Element:
    """Parse an XML string with XXE and entity-expansion protection.

    Returns a standard Element so downstream code is unchanged.
    """
    return _safe_ET.fromstring(text)
