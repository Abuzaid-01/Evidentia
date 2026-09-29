"""HTML -> PDF with headless Chromium (Playwright). Install the browser once:

uv run playwright install chromium
"""

from __future__ import annotations


class PdfRendererUnavailable(RuntimeError):
    """Playwright or its Chromium build is not installed: retrying will not help."""


INSTALL_HINT = "run `uv run playwright install chromium` on the worker machine"


def html_to_pdf(html: str, *, timeout_ms: int = 60_000) -> bytes:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise PdfRendererUnavailable(f"Playwright is not installed; {INSTALL_HINT}") from exc

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Error as exc:
            raise PdfRendererUnavailable(f"Chromium is not available; {INSTALL_HINT}") from exc
        try:
            page = browser.new_page()
            # networkidle: figures are signed Cloudinary renditions and must load before printing
            page.set_content(html, wait_until="networkidle", timeout=timeout_ms)
            return page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
            )
        finally:
            browser.close()
