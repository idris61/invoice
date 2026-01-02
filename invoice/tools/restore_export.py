from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

import frappe
from frappe.modules import scrub


def _ensure_dir(p: Path) -> None:
	p.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str | None) -> None:
	if content is None:
		return
	path.write_text(content, encoding="utf-8")


def _write_json(path: Path, obj: Any) -> None:
	path.write_text(frappe.as_json(obj), encoding="utf-8")


def _strip_child_defaults(doc: "frappe.model.document.Document", doc_export: dict[str, Any]) -> dict[str, Any]:
	"""Best-effort: strip default fields from child rows (similar to Frappe exporter)."""
	import frappe.model

	# Frappe standard exporter strips migration_hash from DocType exports
	if doc.doctype == "DocType" and doc_export.get("migration_hash"):
		doc_export.pop("migration_hash", None)

	for df in doc.meta.get_table_fields():
		for d in doc_export.get(df.fieldname) or []:
			for fieldname in frappe.model.default_fields + frappe.model.child_table_fields:
				d.pop(fieldname, None)
	return doc_export


def _export_doc(
	doctype: str,
	name: str,
	out_dir: Path,
	folder: str,
	code_fields: dict[str, str] | None = None,
) -> None:
	doc = frappe.get_doc(doctype, name)
	doc_export = doc.as_dict(no_nulls=True)
	doc.run_method("before_export", doc_export)
	doc_export = _strip_child_defaults(doc, doc_export)

	target_dir = out_dir / folder / scrub(name)
	_ensure_dir(target_dir)

	# write code fields (and strip from json)
	if code_fields:
		for fieldname, ext in code_fields.items():
			val = getattr(doc, fieldname, None)
			if val:
				_write_text(target_dir / f"{scrub(name)}.{ext}", val)
				doc_export.pop(fieldname, None)

	_write_json(target_dir / f"{scrub(name)}.json", doc_export)


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
	for i in range(0, len(items), size):
		yield items[i : i + size]


@frappe.whitelist()
def export_invoice_documents(out_dir: str, module: str = "invoice") -> dict[str, Any]:
	"""
	Export invoice-related "documents" from the current site's DB into a standalone folder:
	- DocType (module=invoice)
	- Print Format (module=invoice)
	- Customizations (Custom Field / Property Setter / Custom DocPerm / DocType Link) for invoice doctypes
	- Client Script and Server Script referencing invoice doctypes

	This is intentionally NOT using Frappe's standard exporters because those write into app folders.
	"""
	out = Path(out_dir).resolve()
	_ensure_dir(out)

	# safety: avoid writing into the site directory by accident
	site_path = Path(frappe.get_site_path()).resolve()
	if out == site_path or out.is_relative_to(site_path):
		raise frappe.ValidationError(f"Refusing to export into site directory: {out}")

	stats: dict[str, Any] = {"out_dir": str(out), "module": module}

	# 1) DocTypes (module=invoice)
	doctypes = frappe.get_all("DocType", filters={"module": module}, pluck="name") or []
	stats["doctypes"] = len(doctypes)
	for name in doctypes:
		_export_doc("DocType", name, out, "doctype")

	# 2) Print Formats (module=invoice)
	print_formats = frappe.get_all("Print Format", filters={"module": module}, pluck="name") or []
	stats["print_formats"] = len(print_formats)
	for name in print_formats:
		_export_doc(
			"Print Format",
			name,
			out,
			"print_format",
			code_fields={
				"html": "html",
				"css": "css",
				"raw_commands": "raw",
				"format_data": "format_data.json",
			},
		)

	# 3) Customizations for invoice doctypes
	custom_dir = out / "custom"
	_ensure_dir(custom_dir)
	customizations_written = 0
	for dt_chunk in _chunks(doctypes, 25):
		# gather related rows
		custom_fields = frappe.get_all(
			"Custom Field", fields="*", filters={"dt": ["in", dt_chunk]}, order_by="name"
		)
		property_setters = frappe.get_all(
			"Property Setter", fields="*", filters={"doc_type": ["in", dt_chunk]}, order_by="name"
		)
		custom_perms = frappe.get_all(
			"Custom DocPerm", fields="*", filters={"parent": ["in", dt_chunk]}, order_by="name"
		)
		links = frappe.get_all("DocType Link", fields="*", filters={"parent": ["in", dt_chunk]}, order_by="name")

		# group by doctype
		by_dt: dict[str, dict[str, Any]] = {}
		for dt in dt_chunk:
			by_dt[dt] = {
				"doctype": dt,
				"sync_on_migrate": 1,
				"custom_fields": [],
				"property_setters": [],
				"custom_perms": [],
				"links": [],
			}

		for row in custom_fields:
			by_dt[row.get("dt")]["custom_fields"].append(row)
		for row in property_setters:
			by_dt[row.get("doc_type")]["property_setters"].append(row)
		for row in custom_perms:
			by_dt[row.get("parent")]["custom_perms"].append(row)
		for row in links:
			by_dt[row.get("parent")]["links"].append(row)

		for dt, payload in by_dt.items():
			if payload["custom_fields"] or payload["property_setters"] or payload["custom_perms"] or payload["links"]:
				_write_json(custom_dir / f"{scrub(dt)}.json", payload)
				customizations_written += 1

	stats["customization_files"] = customizations_written

	# 4) Client Scripts referencing invoice doctypes
	client_scripts = frappe.get_all(
		"Client Script", fields=["name"], filters={"dt": ["in", doctypes]}, order_by="modified desc"
	)
	stats["client_scripts"] = len(client_scripts)
	for row in client_scripts:
		_export_doc("Client Script", row["name"], out, "client_script", code_fields={"script": "js"})

	# 5) Server Scripts referencing invoice doctypes
	# Note: field is reference_doctype in most Frappe versions
	server_scripts = frappe.get_all(
		"Server Script",
		fields=["name"],
		filters={"reference_doctype": ["in", doctypes]},
		order_by="modified desc",
	)
	stats["server_scripts"] = len(server_scripts)
	for row in server_scripts:
		_export_doc("Server Script", row["name"], out, "server_script", code_fields={"script": "py"})

	(out / "EXPORT_STATS.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
	return stats


