"""Normalize fonts in generated .docx files.

noScribe's template uses the 'Play' font and documents made with new Office
versions reference 'Aptos' — neither is installed on every machine, so Word
shows the "Choose which fonts to replace" dialog when opening our output on
another computer. We rewrite those font references to Calibri, which every
Word installation (Mac + Windows) ships.
"""
from __future__ import annotations

from docx.oxml.ns import qn

BAD_FONTS = {"Play", "Aptos", "Aptos Display", "Aptos Narrow", "Aptos Mono", "Aptos Serif"}
SAFE_FONT = "Calibri"

_RFONT_ATTRS = ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs")


def normalize_fonts(doc, bad=None, safe=SAFE_FONT):
    """Replace unavailable fonts everywhere they can hide: direct run formatting,
    style definitions + document defaults, and the Office theme part."""
    bad = bad or BAD_FONTS
    for root in (doc.element, doc.styles.element):
        for rf in root.iter(qn("w:rFonts")):
            for attr in _RFONT_ATTRS:
                if rf.get(qn(attr)) in bad:
                    rf.set(qn(attr), safe)
    try:  # theme fonts (this is where Aptos usually lives)
        for part in doc.part.package.iter_parts():
            name = str(part.partname)
            if "theme" in name and name.endswith(".xml"):
                xml = part.blob.decode("utf-8", "ignore")
                fixed = xml
                for f in bad:
                    fixed = fixed.replace(f'typeface="{f}"', f'typeface="{safe}"')
                if fixed != xml:
                    part._blob = fixed.encode("utf-8")
    except Exception:  # noqa: BLE001 — cosmetic step, never break saving
        pass
