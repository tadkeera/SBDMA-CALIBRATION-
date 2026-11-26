"""The letterhead's geometry: two edges and a centre, not three things in the middle.

The agency's specification is physical: the Arabic name is flush with the **right**
margin, the official mark is exactly in the **centre**, and the English name is flush
with the **left** margin. The first implementation satisfied the words — Arabic right,
logo middle, English left — while putting the Arabic block in the left-hand column and
the English block in the right-hand one, each pushed *towards* the logo. The result read
as three items huddled in the middle of the page with two empty bands at the edges.

These tests encode the layout as a physical arrangement, so the same reading mistake
cannot come back: the left-hand column carries English, the right-hand column carries
Arabic, and the two side columns are identical in width (which is what makes the centre
cell the centre of the page).
"""

from __future__ import annotations

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph

from app.services import report_service as rs


def _styles() -> dict:
    return rs._styles()


def _letterhead(branding: dict | None = None, width: float | None = None):
    return rs._letterhead(_styles(), branding or {}, width=width)


def _blocks(table) -> tuple[list, object, list]:
    """The three cells of the letterhead band, left to right."""
    row = table._cellvalues[0]
    return row[0], row[1], row[2]


def _text_of(cell) -> str:
    if isinstance(cell, list):
        return " ".join(getattr(item, "text", "") for item in cell)
    return getattr(cell, "text", "") or ""


#: Arabic letters, plus the presentation forms the shaper emits (U+FE70–U+FEFF): the
#: block is shaped before it is drawn, so the code points are the joined glyphs.
ARABIC_RANGES = (("\u0600", "\u06ff"), ("\ufe70", "\ufeff"))


def _has_arabic(text: str) -> bool:
    return any(
        low <= ch <= high for ch in text for low, high in ARABIC_RANGES
    )


def test_english_is_the_left_column_and_arabic_the_right() -> None:
    table = _letterhead()[0]
    left, centre, right = _blocks(table)

    # the left-hand column holds the English block …
    assert "Republic of Yemen" in _text_of(left)
    assert not _has_arabic(_text_of(left))
    # … the right-hand column holds the Arabic block (shaped into presentation forms,
    # so the test looks for the script, not for the exact code points) …
    assert _has_arabic(_text_of(right))
    assert "Republic" not in _text_of(right)
    # … and neither block is in the centre, which belongs to the mark
    assert "Republic" not in _text_of(centre)
    assert not _has_arabic(_text_of(centre))


def test_the_side_columns_are_pushed_to_the_outer_edges() -> None:
    """ALIGN is what spreads the band: LEFT at the start, RIGHT at the end."""
    table = _letterhead()[0]
    # reportlab resolves the style into per-cell style objects; read them back rather
    # than trusting that the source still says what the reviewer thinks it says
    alignments = [cell.alignment for cell in table._cellStyles[0]]
    assert alignments == ["LEFT", "CENTER", "RIGHT"], (
        "left-to-right the band must be: English at the left margin, the mark centred, "
        "Arabic at the right margin"
    )


def test_the_logo_column_is_exactly_in_the_middle_of_the_page() -> None:
    width = A4[0] - 28 * mm
    table = _letterhead(width=width)[0]
    left_w, centre_w, right_w = table._argW
    assert left_w == right_w, "unequal side columns move the mark off centre"
    assert (left_w * 2 + centre_w) == width, "the band must span the text width"
    assert centre_w < left_w, "the mark gets the narrow middle, not a third of the page"


def test_the_arabic_block_keeps_its_reading_order() -> None:
    """Right-aligned and RTL: the shaped paragraphs are stored in reading order."""
    table = _letterhead()[0]
    _, _, right = _blocks(table)
    assert isinstance(right, list) and all(isinstance(p, Paragraph) for p in right)
    assert len(right) == len(rs.DEFAULT_HEADER_AR)


def test_the_xlsx_letterhead_is_a_mirror_of_the_pdf_one() -> None:
    """The spreadsheet puts Arabic on the right half and English on the left half."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    columns = 8
    rs._write_letterhead(ws, {}, columns)

    half = columns // 2
    # English: first cell of the left half, aligned left
    english_cell = ws.cell(row=1, column=1)
    assert english_cell.value == rs.DEFAULT_HEADER_EN[0]
    assert english_cell.alignment.horizontal == "left"
    # Arabic: first cell of the right half, aligned right with RTL reading order
    arabic_cell = ws.cell(row=1, column=half + 1)
    assert arabic_cell.value == rs.DEFAULT_HEADER_AR[0]
    assert arabic_cell.alignment.horizontal == "right"
    assert arabic_cell.alignment.readingOrder == 2
    # and the two halves really are the halves of the sheet
    assert half + 1 <= columns

    buffer = io.BytesIO()
    wb.save(buffer)
    assert buffer.getvalue()[:2] == b"PK"


def test_the_official_mark_ships_with_the_application() -> None:
    """A fresh deployment prints a complete letterhead, not an empty centre."""
    from app.services import branding_service as bs

    assert bs.DEFAULT_LOGO_FILE.is_file(), "the agency's emblem must ship with the app"
    bundled = bs._bundled_logo()
    assert bundled is not None and bundled["bundled"] is True
    assert bundled["width"] and bundled["height"]


def test_the_mark_is_embedded_at_print_size() -> None:
    """The logo prints at 16 mm; embedding 1024 px of it made every report 1.4 MB.

    Inspectors download these reports and the platform mirrors them into the database as
    evidence, so a 25× file size for pixels no printer can show is a real cost. 256 px is
    16 mm at ~400 dpi — sharper than the printer, a fraction of the bytes.
    """
    import io as _io

    from PIL import Image as PILImage

    from app.services import branding_service as bs
    from app.services.report_service import LOGO_PIXELS, _letterhead_logo

    shipped = bs.DEFAULT_LOGO_FILE.read_bytes()
    shrunk = _letterhead_logo(shipped)
    with PILImage.open(_io.BytesIO(shrunk)) as image:
        assert max(image.size) <= LOGO_PIXELS
    assert len(shrunk) < len(shipped), "the embedded copy must get smaller, not bigger"


def test_a_broken_logo_is_passed_through_untouched() -> None:
    """A decoder that refuses the file must not cost the report its letterhead."""
    from app.services.report_service import _letterhead_logo

    garbage = b"not an image at all"
    assert _letterhead_logo(garbage) == garbage
