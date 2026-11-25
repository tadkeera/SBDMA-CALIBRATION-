"""The report renderer must find its fonts wherever it is deployed.

Production found this the hard way: the weekly KPI job returned
``KeyError: 'DejaVuSans-Bold'`` on Vercel, where there is no ``/usr/share/fonts``. The
font was registered only if a *system* path existed, while the styles and the
measurement code named it unconditionally — so every document carrying the letterhead
failed on the platform and passed on the developer's machine.

What is pinned here:
  * the Arabic-capable font ships **with the application** (no host dependency);
  * the loader finds the bundled copy even when no system font directory exists;
  * the names the styles use are always registered fonts, so no build can raise a
    KeyError from inside a PDF;
  * a report still renders when the font is genuinely unavailable (degraded shaping,
    not a 500).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics

from app.services import report_service as rs

TTF_MAGIC = b"\x00\x01\x00\x00"


def test_the_arabic_font_ships_with_the_application() -> None:
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        path = rs.ASSET_FONT_DIR / name
        assert path.is_file(), f"{name} must be bundled: the host cannot be trusted"
        assert path.read_bytes()[:4] == TTF_MAGIC, f"{name} is not a TrueType font"
    assert (rs.ASSET_FONT_DIR / "LICENSE-DejaVu.txt").is_file(), "ship the licence too"


def test_the_bundled_copy_is_found_without_system_fonts(monkeypatch) -> None:  # noqa: ANN001
    """The deployment that has no /usr/share/fonts is the one that broke."""
    monkeypatch.setattr(rs, "FONT_SEARCH_PATH", (rs.ASSET_FONT_DIR, Path("/nonexistent")))
    assert rs._font_source("DejaVuSans.ttf") == rs.ASSET_FONT_DIR / "DejaVuSans.ttf"
    assert rs._font_source("DejaVuSans-Bold.ttf") == rs.ASSET_FONT_DIR / "DejaVuSans-Bold.ttf"


def test_every_name_a_style_uses_is_registered() -> None:
    """``pdfmetrics.getFont`` raises for an unknown name — at build time, in production."""
    assert rs.HAS_ARABIC_FONT, "the bundled font should always register"
    for name in (rs.FONT_BODY, rs.FONT_STRONG):
        assert pdfmetrics.getFont(name).fontName  # raises if unregistered


def test_the_fallback_names_are_real_reportlab_fonts() -> None:
    """If the font is ever missing, the renderer degrades instead of failing."""
    for name in (rs.FALLBACK_REGULAR, rs.FALLBACK_BOLD):
        assert pdfmetrics.getFont(name).fontName


def test_arabic_shaping_is_a_no_op_without_the_font(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(rs, "HAS_ARABIC_FONT", False)
    assert rs.ar("معايرة") == "معايرة"
