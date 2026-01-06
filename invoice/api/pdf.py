import os
from typing import Optional, Dict, Any

import frappe
import requests
from frappe import _

from invoice.api.constants import DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS


logger = frappe.logger("invoice.pdf", allow_site=frappe.local.site)


def get_pdf_service_url() -> str:
    """PDF servisinin URL'ini alır (site_config veya env)."""
    site_config = frappe.get_site_config()
    pdf_service_url = site_config.get("pdf_service_url")

    if not pdf_service_url:
        pdf_service_url = os.environ.get("PDF_SERVICE_URL", "http://localhost:3000")

    return pdf_service_url.rstrip("/")


@frappe.whitelist()
def generate_and_attach_modern_pdf(docname: str) -> Dict[str, Any]:
    """Lieferando Invoice Analysis için modern CSS destekli PDF oluştur ve attach et."""
    try:
        # Doküman kontrolü
        if not frappe.db.exists(DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS, docname):
            frappe.throw(_("Lieferando Invoice Analysis bulunamadı: {0}").format(docname))

        analysis_doc = frappe.get_doc(DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS, docname)

        # Print permission kontrolü
        from frappe.utils.print_format import validate_print_permission

        validate_print_permission(analysis_doc)

        # Print Format HTML'ini al
        print_format_name = "Lieferando Invoice Analysis Format"
        html_content = get_print_format_html(
            doctype=DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS,
            name=docname,
            print_format=print_format_name,
            no_letterhead=True,
        )

        if not html_content or not html_content.strip():
            frappe.throw(_("Print format HTML'i boş geldi. Print format kontrol edin."))

        logger.info(f"Print format HTML alındı ({len(html_content)} karakter)")
        
        # Image URL'lerini base64'e çevir (logo için)
        html_content = convert_image_urls_to_base64(html_content)

        # PDF Service'e gönder
        pdf_service_url = get_pdf_service_url()
        file_name = f"{docname.replace(' ', '-').replace('/', '-')}.pdf"

        pdf_binary = render_pdf_from_html(
            html=html_content,
            file_name=file_name,
            pdf_service_url=pdf_service_url,
        )

        if not pdf_binary:
            frappe.throw(_("PDF servisi boş yanıt döndü. Servis kontrol edin."))

        logger.info(f"PDF oluşturuldu ({len(pdf_binary)} byte)")

        # Eski aynı isimli PDF'leri sil
        old_files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS,
                "attached_to_name": docname,
                "file_name": file_name,
            },
            fields=["name"],
        )
        for old_file in old_files:
            try:
                frappe.delete_doc("File", old_file.name, ignore_permissions=True)
            except Exception as e:
                logger.warning(f"Eski PDF silinemedi: {old_file.name} - {str(e)}")

        # Yeni File kaydı oluştur (private)
        file_doc = frappe.new_doc("File")
        file_doc.file_name = file_name
        file_doc.content = pdf_binary
        file_doc.attached_to_doctype = DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS
        file_doc.attached_to_name = docname
        file_doc.is_private = 1
        file_doc.flags.ignore_permissions = True
        file_doc.insert()
        frappe.db.commit()

        logger.info(f"PDF başarıyla attach edildi: {file_name}")

        return {
            "success": True,
            "message": _("PDF başarıyla oluşturuldu ve eklendi"),
            "file_name": file_name,
            "file_url": file_doc.file_url,
        }

    except requests.exceptions.RequestException as e:
        error_msg = _("PDF servisine bağlanılamadı: {0}").format(str(e))
        logger.error(error_msg)
        frappe.log_error(
            title="PDF Service Connection Error",
            message=f"Analysis: {docname}\nError: {str(e)}\n{frappe.get_traceback()}",
        )
        return {"success": False, "message": error_msg}
    except Exception as e:
        error_msg = _("PDF oluşturulurken hata oluştu: {0}").format(str(e))
        logger.error(error_msg)
        frappe.log_error(
            title="Modern PDF Generation Error",
            message=f"Analysis: {docname}\nError: {str(e)}\n{frappe.get_traceback()}",
        )
        return {"success": False, "message": error_msg}


def get_print_format_html(
    doctype: str,
    name: str,
    print_format: str,
    no_letterhead: bool = True,
) -> Optional[str]:
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
            logger.warning(f"Print format bulunamadı: {print_format}, Standard kullanılıyor")
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
        logger.error(f"Print format HTML render hatası: {str(e)}")
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


def convert_image_urls_to_base64(html: str) -> str:
    """
    HTML'deki relative image URL'lerini base64 data URI'ye çevirir.
    Playwright external URL'leri yükleyemediği için gerekli.
    """
    import re
    import base64
    
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
                    
                    logger.info(f"Image base64'e çevrildi: {file_name} ({len(base64_data)} karakter)")
                    return f'src="{data_uri}"'
                except Exception as e:
                    logger.warning(f"Image base64'e çevrilemedi: {file_name} - {str(e)}")
                    return match.group(0)  # Orijinal src'yi koru
            else:
                logger.warning(f"File bulunamadı: {file_path}")
                return match.group(0)  # Orijinal src'yi koru
                
        except Exception as e:
            logger.warning(f"Image URL dönüştürme hatası: {file_path} - {str(e)}")
            return match.group(0)  # Orijinal src'yi koru
    
    # Tüm image src'lerini değiştir
    html = re.sub(pattern, replace_with_base64, html)
    
    return html


def render_pdf_from_html(
    html: str,
    file_name: str,
    pdf_service_url: str,
    timeout: int = 30,
) -> Optional[bytes]:
    """HTML'i PDF servisine gönderir ve binary PDF döner."""
    endpoint = f"{pdf_service_url}/render-pdf"
    payload = {"html": html, "file_name": file_name}

    logger.info(f"PDF servisine istek gönderiliyor: {endpoint}")

    response = requests.post(
        endpoint,
        json=payload,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
    )

    # Response tipini kontrol et
    content_type = response.headers.get("Content-Type", "").lower()
    
    if "application/pdf" in content_type:
        # PDF binary döndü
        return response.content
    elif "application/json" in content_type:
        # JSON hata cevabı
        try:
            error_data = response.json()
            error_msg = error_data.get("error", "Bilinmeyen hata")
            error_detail = error_data.get("message", "")
            raise requests.exceptions.RequestException(
                f"PDF servisi hatası: {error_msg}" + (f" - {error_detail}" if error_detail else "")
            )
        except ValueError:
            raise requests.exceptions.RequestException("PDF servisi geçersiz JSON yanıtı döndü")
    else:
        # Beklenmeyen content type
        response.raise_for_status()  # HTTP status koduna göre hata fırlat
        # Eğer status OK ise ama content type beklenmedikse, içeriği döndür
        return response.content


