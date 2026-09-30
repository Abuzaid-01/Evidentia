"""Report rendering. `render_html` is a pure function of a snapshot manifest; `html_to_pdf` prints
that HTML with headless Chromium (worker only)."""

from evidentia_reporting.pdf import PdfRendererUnavailable, html_to_pdf
from evidentia_reporting.render import RENDERER_VERSION, render_html, renderer_version

__all__ = [
    "RENDERER_VERSION",
    "PdfRendererUnavailable",
    "html_to_pdf",
    "render_html",
    "renderer_version",
]
