from __future__ import annotations

"""
Custom PDF generator hook that uses Chrome's print-to-PDF engine.

This is wired via the `pdf_generator` hook in `hooks.py`.
When a Print Format has pdf_generator == "chrome", Frappe will call this
function instead of the default wkhtmltopdf-based implementation.
"""

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import frappe


def _find_chrome_binary() -> str:
	"""Best-effort lookup for a Chrome/Chromium binary on Linux."""

	candidates = [
		os.environ.get("CHROME_PATH"),
		"google-chrome",
		"google-chrome-stable",
		"chromium",
		"chromium-browser",
	]

	for cmd in candidates:
		if not cmd:
			continue
		try:
			subprocess.run(
				[cmd, "--version"],
				check=False,
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
		except FileNotFoundError:
			continue
		else:
			return cmd

	# Fallback – let it fail clearly later
	return "google-chrome"


def chrome_pdf_generator(
	*,
	print_format: str,
	html: str,
	options: dict[str, Any] | None = None,
	output=None,
	pdf_generator: str | None = None,
) -> bytes | None:
	"""
	Hook function for Frappe's `pdf_generator` mechanism.

	Args:
	    print_format: Print Format name (unused, but part of the hook signature)
	    html: Rendered HTML to convert
	    options: wkhtmltopdf-style options (currently ignored)
	    output: Optional PdfWriter – unsupported for Chrome, so we ignore and
	            return raw bytes.
	    pdf_generator: Name of the requested PDF generator; we only handle "chrome".

	Returns:
	    PDF bytes, or None to let Frappe fall back to the default behaviour.
	"""

	# Only handle explicit chrome requests; otherwise let Frappe fall back.
	if pdf_generator != "chrome":
		return None

	chrome_bin = _find_chrome_binary()

	# Write HTML to a temporary file so Chrome can open it.
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir_path = Path(tmpdir)
		html_path = tmpdir_path / "document.html"
		pdf_path = tmpdir_path / "document.pdf"

		html_path.write_text(html, encoding="utf-8")

		# Build Chrome headless command.
		# NOTE: `--no-sandbox` is often required under containers / WSL.
		cmd = [
			chrome_bin,
			"--headless",
			"--disable-gpu",
			"--no-sandbox",
			"--print-to-pdf-no-header",
			f"--print-to-pdf={pdf_path}",
			str(html_path),
		]

		try:
			proc = subprocess.run(
				cmd,
				check=False,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
			)
		except FileNotFoundError as exc:
			frappe.log_error(
				title="Chrome PDF Generator - binary not found",
				message=f"Command: {shlex.join(cmd)}\nError: {exc}",
			)
			return None

		if proc.returncode != 0 or not pdf_path.exists():
			frappe.log_error(
				title="Chrome PDF Generator - conversion failed",
				message=(
					f"Command: {shlex.join(cmd)}\n"
					f"Return code: {proc.returncode}\n"
					f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
				),
			)
			return None

		pdf_bytes = pdf_path.read_bytes()

		# Frappe's print_utils expects raw bytes when using custom generators.
		return pdf_bytes



