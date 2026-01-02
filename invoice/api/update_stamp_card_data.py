#!/usr/bin/env python3
"""
Update existing Lieferando Invoices with stamp card (loyalty program) data
Extracts stamp_card_orders and stamp_card_amount from raw_text if available
"""

import frappe
import re
from frappe.utils import flt

def _extract_decimal_from_match(match, group_index=1):
    """Extract decimal value from regex match"""
    if not match:
        return None
    try:
        amount_str = match.group(group_index).replace('.', '').replace(',', '.')
        return float(amount_str)
    except (ValueError, IndexError, AttributeError):
        return None

def extract_stamp_card_from_text(raw_text):
    """Extract stamp card data from raw PDF text"""
    if not raw_text:
        return None, None
    
    # Extract stamp card (Stempelkarte) orders and amount
    # Pattern: "davon mit Stempelkarte bezahlt **: 1 Bestellung im Wert von € 12,69"
    stamp_card_patterns = [
        r'davon mit Stempelkarte bezahlt\s*\*\*\s*:\s*(\d+)\s+Bestellung[^€]*€\s*([\d,\.]+)',  # With colon
        r'davon mit Stempelkarte bezahlt\s*\*\*\s+(\d+)\s+Bestellung[^€]*€\s*([\d,\.]+)',  # Without colon
        r'Stempelkarte bezahlt\s*\*\*\s*:\s*(\d+)\s+Bestellung[^€]*€\s*([\d,\.]+)',  # Alternative format
    ]
    
    for pattern in stamp_card_patterns:
        stamp_card_match = re.search(pattern, raw_text, re.IGNORECASE)
        if stamp_card_match:
            orders = int(stamp_card_match.group(1))
            amount = _extract_decimal_from_match(stamp_card_match, group_index=2)
            if amount is not None:
                return orders, amount
    
    return None, None

def update_invoice_stamp_card_data(invoice_name):
    """Update a single invoice with stamp card data"""
    try:
        invoice = frappe.get_doc("Lieferando Invoice", invoice_name)
        
        # Skip if already has stamp card data
        if invoice.stamp_card_orders and invoice.stamp_card_orders > 0:
            print(f"  ⏭️  {invoice.invoice_number}: Zaten stamp_card verisi var (orders: {invoice.stamp_card_orders})")
            return False
        
        # Extract from raw_text
        if not invoice.raw_text:
            print(f"  ⚠️  {invoice.invoice_number}: raw_text yok, atlanıyor")
            return False
        
        orders, amount = extract_stamp_card_from_text(invoice.raw_text)
        
        if orders is not None and amount is not None:
            invoice.stamp_card_orders = orders
            invoice.stamp_card_amount = flt(amount)
            invoice.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"  ✅ {invoice.invoice_number}: Güncellendi (orders: {orders}, amount: €{amount:.2f})")
            return True
        else:
            print(f"  ⚠️  {invoice.invoice_number}: PDF'de stamp_card verisi bulunamadı")
            return False
            
    except Exception as e:
        print(f"  ❌ {invoice_name}: Hata - {str(e)}")
        frappe.log_error(
            title="Stamp Card Update Error",
            message=f"Invoice: {invoice_name}\nError: {str(e)}"
        )
        return False

def update_all_invoices():
    """Update all Lieferando Invoices with stamp card data"""
    print("=" * 80)
    print("STAMP CARD (LOYALTY PROGRAM) VERİLERİNİ GÜNCELLEME")
    print("=" * 80)
    
    # Get all invoices
    invoices = frappe.get_all(
        "Lieferando Invoice",
        fields=["name", "invoice_number"],
        filters={},
        order_by="creation desc"
    )
    
    total = len(invoices)
    updated = 0
    skipped = 0
    errors = 0
    
    print(f"\nToplam {total} fatura bulundu.\n")
    
    for inv in invoices:
        result = update_invoice_stamp_card_data(inv.name)
        if result:
            updated += 1
        elif inv.name:
            skipped += 1
        else:
            errors += 1
    
    print("\n" + "=" * 80)
    print("ÖZET:")
    print(f"  Toplam: {total}")
    print(f"  Güncellenen: {updated}")
    print(f"  Atlanan: {skipped}")
    print(f"  Hata: {errors}")
    print("=" * 80)

def update_single_invoice(invoice_number):
    """Update a single invoice by invoice number"""
    print("=" * 80)
    print(f"FATURA GÜNCELLEME: {invoice_number}")
    print("=" * 80)
    
    invoice = frappe.get_all(
        "Lieferando Invoice",
        fields=["name"],
        filters={"invoice_number": invoice_number},
        limit=1
    )
    
    if not invoice:
        print(f"❌ Fatura bulunamadı: {invoice_number}")
        return
    
    result = update_invoice_stamp_card_data(invoice[0].name)
    
    if result:
        print(f"\n✅ Fatura başarıyla güncellendi: {invoice_number}")
    else:
        print(f"\n⚠️  Fatura güncellenemedi: {invoice_number}")

def update_single(invoice_number):
    """Update single invoice - for bench execute"""
    update_single_invoice(invoice_number)
    frappe.db.commit()

def update_all():
    """Update all invoices - for bench execute"""
    update_all_invoices()
    frappe.db.commit()

