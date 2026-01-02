# Copyright (c) 2025, invoice and contributors
# For license information, please see license.txt

"""
Import Lieferando Invoice Print Format
"""
import frappe
import json
import os

def import_lieferando_print_format():
	"""Import the Lieferando Invoice Print Format"""
	
	# Get the path to the print format JSON file
	json_path = os.path.join(
		frappe.get_app_path("invoice"),
		"invoice",
		"print_format",
		"lieferando_invoice_format",
		"lieferando_invoice_format.json"
	)
	
	print(f"📄 Importing Print Format from: {json_path}")
	
	if not os.path.exists(json_path):
		print(f"❌ File not found: {json_path}")
		return
	
	try:
		# Read the JSON file
		with open(json_path, 'r', encoding='utf-8') as f:
			data = json.load(f)
		
		# Check if Print Format already exists
		if frappe.db.exists("Print Format", data.get("name")):
			print(f"⚠️  Print Format '{data.get('name')}' already exists. Updating...")
			pf = frappe.get_doc("Print Format", data.get("name"))
			# Remove fields that shouldn't be updated
			data.pop("modified", None)
			data.pop("modified_by", None)
			data.pop("creation", None)
			pf.update(data)
			pf.reload()
			pf.save(ignore_permissions=True, ignore_version=True)
			frappe.db.commit()
			print(f"✅ Print Format updated: {pf.name}")
		else:
			print(f"📝 Creating new Print Format: {data.get('name')}")
			# Remove creation/modified fields for new document
			data.pop("modified", None)
			data.pop("modified_by", None)
			data.pop("creation", None)
			pf = frappe.get_doc(data)
			pf.insert(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Print Format created: {pf.name}")
		
		# Verify
		if frappe.db.exists("Print Format", data.get("name")):
			pf = frappe.get_doc("Print Format", data.get("name"))
			print(f"\n✅ Print Format successfully imported!")
			print(f"   Name: {pf.name}")
			print(f"   Doc Type: {pf.doc_type}")
			print(f"   Format Type: {pf.print_format_type}")
			print(f"   Standard: {pf.standard}")
			print(f"   Disabled: {pf.disabled}")
		else:
			print("❌ Print Format not found after import!")
			
	except Exception as e:
		print(f"❌ Error: {str(e)}")
		import traceback
		traceback.print_exc()

if __name__ == "__main__":
	import_lieferando_print_format()



