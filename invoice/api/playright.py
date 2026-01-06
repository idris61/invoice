import frappe
import json
import tempfile
import os
import re
import base64
from frappe.core.doctype.file.file import File
# We use the synchronous API because Frappe workers are synchronous
from playwright.sync_api import sync_playwright
from invoice.api.constants import DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS

def get_print_format_html(
    doctype: str,
    name: str,
    print_format: str,
    no_letterhead: bool = True,
) -> str|None:
    """
    Print format HTML'ini render eder (sadece HTML, PDF değil).
    
    Recursion hatası önlemek için internal fonksiyonları doğrudan kullanıyoruz.
    """
    from frappe.www.printview import (
        get_rendered_template,
        get_print_style,
        set_link_titles,
    )
    
    doc = frappe.get_doc(doctype, name)
    meta = frappe.get_meta(doctype)
    
    # Print format doc'u doğrudan al (get_print_format_doc form_dict kullanıyor)
    if not print_format or print_format == "Standard":
        print_format_doc = None
    else:
        try:
            print_format_doc = frappe.get_doc("Print Format", print_format)
        except frappe.DoesNotExistError:
            frappe.logger().warning(f"Print format bulunamadı: {print_format}, Standard kullanılıyor")
            print_format_doc = None
    
    # Link başlıklarını ayarla
    set_link_titles(doc)
    
    # HTML'i render et
    try:
        html = get_rendered_template(
            doc=doc,
            print_format=print_format_doc,
            meta=meta,
            no_letterhead=no_letterhead,
            letterhead=None,
            trigger_print=False,
            settings=None,
        )
    except Exception as e:
        frappe.logger().error(f"Print format HTML render hatası: {str(e)}")
        frappe.log_error(
            title="Print Format HTML Render Error",
            message=f"Error: {str(e)}\n{frappe.get_traceback()}"
        )
        return None
    
    if not html:
        return None
    
    # Style'ı al
    style = get_print_style(style=None, print_format=print_format_doc)
    
    # HTML ve style'ı birleştir
    if html and style:
        if "<head>" in html:
            html = html.replace("<head>", f"<head>\n<style>\n{style}\n</style>")
        elif "<html>" in html:
            html = html.replace(
                "<html>",
                f"<html>\n<head>\n<style>\n{style}\n</style>\n</head>",
            )
        else:
            html = f"<head>\n<style>\n{style}\n</style>\n</head>\n{html}"
    
    return html


def get_lieferando_invoice_context(doc_name: str) -> dict:
    """
    Fetches the document and prepares the dictionary context for Jinja.
    (Same logic as before, just kept here for completeness)
    """
    doc = frappe.get_doc("Lieferando Invoice Analysis", doc_name)
    
    # Parse the JSON field securely
    raw_json = doc.invoice_data_json
    invoice_data_dict = {}
    
    if raw_json:
        try:
            if isinstance(raw_json, str):
                invoice_data_dict = json.loads(raw_json)
            elif isinstance(raw_json, dict):
                invoice_data_dict = raw_json
        except Exception:
            frappe.log_error("Failed to parse invoice_data_json")

    context_doc = {
        "restaurant_name": doc.restaurant_name or "",
        "customer_number": doc.customer_number or "",
        "invoice_number": doc.invoice_number or "",
        "period_start": doc.period_start,
        "period_end": doc.period_end,
        "customer_tax_number": doc.customer_tax_number or "",
        "total_revenue": float(doc.total_revenue or 0.0),
        "online_paid_amount": float(doc.online_paid_amount or 0.0),
        "cash_paid_amount": float(doc.cash_paid_amount or 0.0),
        "chargeback_amount": float(doc.chargeback_amount or 0.0),
        "cash_service_fee_amount": float(doc.cash_service_fee_amount or 0.0),
        "total_orders": int(doc.total_orders or 0),
        "online_paid_orders": int(doc.online_paid_orders or 0),
        "cash_paid_orders": int(doc.cash_paid_orders or 0),
        "chargeback_orders": int(doc.chargeback_orders or 0),
        "service_fee_rate": float(doc.service_fee_rate or 0.0),
        "management_fee": float(doc.management_fee or 0.0),
        "additional_service_fee": float(doc.additional_service_fee or 0.0),
        "culinary_account_fee": float(doc.culinary_account_fee or 0.0),
        "tips_amount": float(doc.tips_amount or 0.0),
        "stamp_card_amount": float(doc.stamp_card_amount or 0.0),
        "pending_online_payments_g": float(doc.pending_online_payments_g or 0.0),
        "reference_service_fee_rate": float(doc.reference_service_fee_rate) if doc.reference_service_fee_rate else None,
        "notes": doc.notes or None,
        "invoice_data": invoice_data_dict
    }

    return {
        "doc": context_doc,
        "max": max,
        "frappe": frappe
    }

def convert_image_urls_to_base64(html: str) -> str:
    """
    HTML'deki relative image URL'lerini base64 data URI'ye çevirir.
    Playwright file:// protokolü ile çalışırken relative path'leri yükleyemediği için gerekli.
    """
    # /files/ ile başlayan image src'lerini bul
    pattern = r'src=["\'](/files/[^"\']+)["\']'
    
    def replace_with_base64(match):
        file_path = match.group(1)
        
        try:
            # File doctype'ından dosyayı al
            # /files/logocc.png -> logocc.png
            file_name = file_path.replace('/files/', '')
            
            # File kaydını bul
            file_doc = frappe.db.get_value(
                "File",
                {"file_name": file_name},
                ["name", "file_url"],
                as_dict=True
            )
            
            if not file_doc:
                # Alternatif: file_url ile dene
                file_doc = frappe.db.get_value(
                    "File",
                    {"file_url": file_path},
                    ["name", "file_url"],
                    as_dict=True
                )
            
            if file_doc:
                try:
                    file_obj = frappe.get_doc("File", file_doc.name)
                    file_content = file_obj.get_content()
                    
                    # MIME type'ı belirle
                    if file_name.lower().endswith('.png'):
                        mime_type = 'image/png'
                    elif file_name.lower().endswith('.jpg') or file_name.lower().endswith('.jpeg'):
                        mime_type = 'image/jpeg'
                    elif file_name.lower().endswith('.gif'):
                        mime_type = 'image/gif'
                    elif file_name.lower().endswith('.svg'):
                        mime_type = 'image/svg+xml'
                    else:
                        mime_type = 'image/png'  # Default
                    
                    # Base64'e çevir
                    base64_data = base64.b64encode(file_content).decode('utf-8')
                    data_uri = f"data:{mime_type};base64,{base64_data}"
                    
                    frappe.logger().info(f"Image base64'e çevrildi: {file_name} ({len(base64_data)} karakter)")
                    return f'src="{data_uri}"'
                except Exception as e:
                    frappe.logger().warning(f"Image base64'e çevrilemedi: {file_name} - {str(e)}")
                    return match.group(0)  # Orijinal src'yi koru
            else:
                frappe.logger().warning(f"File bulunamadı: {file_path}")
                return match.group(0)  # Orijinal src'yi koru
                
        except Exception as e:
            frappe.logger().warning(f"Image URL dönüştürme hatası: {file_path} - {str(e)}")
            return match.group(0)  # Orijinal src'yi koru
    
    # Tüm image src'lerini değiştir
    html = re.sub(pattern, replace_with_base64, html)
    
    return html

@frappe.whitelist()
def generate_lieferando_pdf(doc_name: str) -> File:
    """
    Generates a PDF using Headless Chrome (Playwright) for perfect CSS Grid support.
    """
    temp_html_path = ""
    
    try:
        # 1. Prepare Context & Render HTML
        #context = get_lieferando_invoice_context(doc_name)
        #template_path = "invoice/api/pdf_test/lieferando_invoice_analysis_format.html"
        #html_content = frappe.render_template(template_path, context)
        
        print_format_name = "Lieferando Invoice Analysis Format"
        html_content = get_print_format_html(
            doctype=DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS,
            name=doc_name,
            print_format=print_format_name,
            no_letterhead=True,
        )
        
        if not html_content:
            frappe.throw("Print format HTML'i boş geldi.")
        
        # Logo ve diğer image URL'lerini base64'e çevir
        html_content = convert_image_urls_to_base64(html_content)
        
        # 2. Write HTML to a temporary file
        # Playwright works best loading from a file or URL to handle relative assets correctly
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(html_content)
            temp_html_path = tmp.name

        pdf_bytes = b""

        # 3. Launch Headless Chrome
        with sync_playwright() as p:
            # Launch browser (headless=True is default)
            browser = p.chromium.launch()
            page = browser.new_page()
            
            # Load the local HTML file
            # 'file://' protocol ensures it renders the local temp file
            page.goto(f"file://{temp_html_path}")
            
            # Generate PDF
            # format="A4" handles the page size. 
            # print_background=True ensures CSS background colors/images render.
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"} # Margins handled in CSS @page
            )
            
            browser.close()

        # 4. Save to ERPNext
        filename = f"Lieferando-Analysis-{doc_name}.pdf"
        
        # Cleanup existing file if needed
        existing = frappe.get_all("File", filters={
            "attached_to_doctype": "Lieferando Invoice Analysis",
            "attached_to_name": doc_name,
            "file_name": filename
        })
        for f in existing:
            frappe.delete_doc("File", f.name)

        saved_file = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "attached_to_doctype": "Lieferando Invoice Analysis",
            "attached_to_name": doc_name,
            "content": pdf_bytes,
            "is_private": 1 
        })
        saved_file.save()
        
        return {
            "success": True,
            "message": "PDF başarıyla oluşturuldu ve eklendi",
            "file_name": filename,
            "file_url": saved_file.file_url
        }

    except Exception as e:
        frappe.log_error(f"PDF Generation Error: {str(e)}")
        frappe.throw(f"Failed to generate PDF: {str(e)}")
        
    finally:
        # Cleanup the temp HTML file
        if temp_html_path and os.path.exists(temp_html_path):
            os.remove(temp_html_path)