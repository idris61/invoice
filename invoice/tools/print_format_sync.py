from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe
from invoice.api.constants import (
	DOCTYPE_LIEFERANDO_INVOICE,
	DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS
)


def _read_json(path: Path) -> dict[str, Any]:
	return json.loads(path.read_text(encoding="utf-8"))


def _upsert_print_format(pf_name: str, doc_type: str, module: str, html: str, base_fields: dict[str, Any]):
	"""
	Create or update a Print Format in DB. We deliberately source the HTML from the .html file.
	"""
	data = dict(base_fields or {})
	data.pop("creation", None)
	data.pop("modified", None)
	data.pop("modified_by", None)
	data.pop("owner", None)
	# PDF motoru sahada her zaman wkhtmltopdf olacağı için,
	# JSON içindeki pdf_generator alanını zorlama.
	data.pop("pdf_generator", None)

	# force important fields
	data.update(
		{
			"doctype": "Print Format",
			"name": pf_name,
			"doc_type": doc_type,
			"module": module,
			"print_format_for": "DocType",
			"print_format_type": "Jinja",
			"custom_format": 1,
			"standard": "No",
			"disabled": 0,
			"html": html,
		}
	)

	if frappe.db.exists("Print Format", pf_name):
		pf = frappe.get_doc("Print Format", pf_name)
		pf.update(data)
		pf.save(ignore_permissions=True, ignore_version=True)
	else:
		pf = frappe.get_doc(data)
		pf.insert(ignore_permissions=True)

	return pf


@frappe.whitelist()
def sync_lieferando_print_formats_from_repo(module: str = "invoice") -> dict[str, Any]:
	"""
	Sync the Lieferando Print Formats from repo files into the current site's DB:
	- apps/invoice/.../print_format/lieferando_invoice_format/*.html|*.json
	- apps/invoice/.../print_format/lieferando_invoice_analysis_format/*.html|*.json
	"""
	app_path = Path(frappe.get_app_path("invoice"))

	def pf_paths(slug: str):
		base = app_path / "invoice" / "print_format" / slug
		return base / f"{slug}.json", base / f"{slug}.html"

	targets = [
		{
			"name": "Lieferando Invoice Format",
			"doc_type": DOCTYPE_LIEFERANDO_INVOICE,
			"slug": "lieferando_invoice_format",
		},
		{
			"name": "Lieferando Invoice Analysis Format",
			"doc_type": DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS,
			"slug": "lieferando_invoice_analysis_format",
		},
	]

	results: dict[str, Any] = {"updated": [], "created": []}
	for t in targets:
		json_path, html_path = pf_paths(t["slug"])
		base_fields = _read_json(json_path) if json_path.exists() else {}
		html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""

		existed = bool(frappe.db.exists("Print Format", t["name"]))
		pf = _upsert_print_format(t["name"], t["doc_type"], module, html, base_fields)

		# set as default print format (property setter style)
		frappe.make_property_setter(
			{
				"doctype_or_field": "DocType",
				"doctype": t["doc_type"],
				"property": "default_print_format",
				"value": t["name"],
				"property_type": "Data",
			}
		)

		(results["updated"] if existed else results["created"]).append(pf.name)

	frappe.db.commit()
	return results





