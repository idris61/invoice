import frappe
from frappe import _
import re
import json
from datetime import datetime
from invoice.api.constants import (
	DEFAULT_EXTRACTION_CONFIDENCE,
	FIELD_STATUS_DRAFT,
	FIELD_PDF_FILE,
	DOCTYPE_LIEFERANDO_INVOICE,
	DOCTYPE_WOLT_INVOICE,
	DOCTYPE_UBER_EATS_INVOICE,
	FIELD_NETTING_REPORT_PDF,
	USER_TYPE_SYSTEM,
	COMMUNICATION_TYPE,
	SENT_OR_RECEIVED_RECEIVED,
	DOCTYPE_COMMUNICATION,
)

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

logger = frappe.logger("invoice.email_handler", allow_site=frappe.local.site)


def _check_invoice_exists(doctype, invoice_number):
    """Invoice number'a göre duplicate kontrolü yap"""
    if not invoice_number:
        return False
    
    return bool(frappe.db.exists(doctype, {"invoice_number": invoice_number}))


def process_invoice_email(doc, method=None):
    """Communication DocType'ına gelen email'leri yakala ve fatura oluştur"""
    logger.info(f"Email işleme başladı: {doc.subject} (Communication: {doc.name})")
    
    stats = {
        "total_detected": 0,
        "already_processed": 0,
        "newly_processed": 0,
        "errors": 0,
        "invoices_created": []
    }
    
    try:
        if doc.communication_type != COMMUNICATION_TYPE or doc.sent_or_received != SENT_OR_RECEIVED_RECEIVED:
            logger.info(f"Email atlandı - type: {doc.communication_type}, received: {doc.sent_or_received}")
            return
        
        # NOT: Duplicate kontrolü sadece invoice_number (Rechnungsnummer) ile yapılacak
        # Email seviyesinde kontrol kaldırıldı - aynı email'den farklı faturalar gelebilir
        
        attachments = frappe.get_all("File",
            filters={
                "attached_to_doctype": DOCTYPE_COMMUNICATION,
                "attached_to_name": doc.name,
            },
            fields=["name", "file_url", "file_name", "file_size"]
        )
        
        pdf_attachments = [
            att for att in attachments 
            if att.get('file_name') and att.get('file_name').lower().endswith('.pdf')
        ]
        
        subject = (doc.subject or "").lower()
        
        # ÖNEMLİ: "Ihre neue Aktivitätsübersicht" içeren email'ler UberEats faturaları
        is_uber_eats_report = "ihre neue aktivitätsübersicht" in subject
        if is_uber_eats_report:
            logger.info(f"UberEats Aktivitätsübersicht email'i tespit edildi: {doc.subject}")
            logger.info(f"Tüm PDF'ler taranacak ({len(pdf_attachments)} adet)")
            stats["total_detected"] = len(pdf_attachments)
            
            if not pdf_attachments:
                logger.warning("UberEats email'inde PDF bulunamadı")
                stats["errors"] = 1
                show_summary_notification(stats, doc.subject)
                return
        
        # ÖNEMLİ: "Wolt payout report" içeren email'lerdeki tüm PDF'leri işle
        is_wolt_payout_report = "wolt payout report" in subject
        if is_wolt_payout_report:
            logger.info(f"Wolt payout report email'i tespit edildi: {doc.subject}")
            logger.info(f"Tüm PDF'ler taranacak ({len(pdf_attachments)} adet)")
            stats["total_detected"] = len(pdf_attachments)
            
            if not pdf_attachments:
                logger.warning("Wolt payout report email'inde PDF bulunamadı")
                stats["errors"] = 1
                show_summary_notification(stats, doc.subject)
                return
        
        # Normal fatura kontrolü - sadece özel email'ler değilse
        if not is_uber_eats_report and not is_wolt_payout_report:
            keywords = ["invoice", "fatura", "rechnung", "facture", "bill", "wolt"]
            has_invoice_subject = any(keyword in subject for keyword in keywords)
            
            if not has_invoice_subject:
                logger.info(f"Email atlandı - fatura değil: {doc.subject}")
                return
            
            logger.info(f"Fatura email'i tespit edildi: {doc.subject}")
            stats["total_detected"] = 1
            
            if not pdf_attachments:
                stats["errors"] = 1
                show_summary_notification(stats, doc.subject)
                return
        
        # İlk tur: faturaları (Selbstfakturierung) işle, netting raporlarını topla
        netting_pdfs = []
        for pdf in pdf_attachments:
            try:
                # UberEats email'lerinde: Sadece "Bestell- und Zahlungsübersicht" başlığı olan PDF'leri işle
                if is_uber_eats_report:
                    # PDF içeriğini hızlıca kontrol et
                    has_uber_eats_header = check_pdf_has_uber_eats_header(pdf)
                    if not has_uber_eats_header:
                        logger.info(f"PDF atlandı (Bestell- und Zahlungsübersicht yok): {pdf.file_name}")
                        continue
                    logger.info(f"PDF işlenecek (Bestell- und Zahlungsübersicht bulundu): {pdf.file_name}")
                
                # Wolt payout report email'lerinde: fatura PDF'lerini hemen işle, netting raporlarını ikinci tura bırak
                if is_wolt_payout_report:
                    has_selbstfakturierung = check_pdf_has_selbstfakturierung(pdf)
                    if not has_selbstfakturierung:
                        has_netting_report = check_pdf_has_wolt_netting_report(pdf)
                        if has_netting_report:
                            netting_pdfs.append(pdf)
                            logger.info(f"Netting raporu tespit edildi (queue): {pdf.file_name}")
                        else:
                            logger.info(f"PDF atlandı (Rechnung(Selbstfakturierung) ya da Netting yok): {pdf.file_name}")
                        continue
                    logger.info(f"PDF işlenecek (Rechnung(Selbstfakturierung) bulundu): {pdf.file_name}")
                
                invoice = create_invoice_from_pdf(doc, pdf)
                if invoice:
                    stats["newly_processed"] += 1
                    stats["invoices_created"].append({
                        "doctype": invoice.doctype,
                        "name": invoice.name,
                        "invoice_number": getattr(invoice, "invoice_number", "N/A")
                    })
                else:
                    stats["already_processed"] += 1
            except Exception as e:
                stats["errors"] += 1
                error_message = f"Communication: {doc.name}\nSubject: {doc.subject}\nPDF: {pdf.file_name}\nError: {str(e)}\n{frappe.get_traceback()}"
                frappe.log_error(
                    title="Invoice PDF Processing Error",
                    message=error_message
                )
                logger.error(f"PDF işleme hatası: {pdf.file_name} - {str(e)}")

        # İkinci tur: netting raporlarını artık oluşmuş Wolt Invoice'lara ekle
        for net_pdf in netting_pdfs:
            try:
                handle_wolt_netting_report(doc, net_pdf)
            except Exception as e:
                stats["errors"] += 1
                error_message = f"Communication: {doc.name}\nSubject: {doc.subject}\nPDF: {net_pdf.file_name}\nError: {str(e)}\n{frappe.get_traceback()}"
                frappe.log_error(
                    title="Wolt Netting PDF Error",
                    message=error_message
                )
                logger.error(f"Wolt Netting PDF işleme hatası: {net_pdf.file_name} - {str(e)}")
        
        # Database commit - hata olursa rollback yap
        try:
            frappe.db.commit()
            logger.info(f"Email işleme tamamlandı. Stats: {stats}")
            show_summary_notification(stats, doc.subject)
        except Exception as commit_error:
            frappe.db.rollback()
            logger.error(f"Database commit hatası: {str(commit_error)}")
            stats["errors"] = stats.get("errors", 0) + 1
            frappe.log_error(
                title="Invoice Email Processing - Database Commit Error",
                message=f"Communication: {doc.name}\nSubject: {doc.subject}\nError: {str(commit_error)}\n{frappe.get_traceback()}"
            )
            # Commit hatası olsa bile kullanıcıya bildirim gönder
            show_summary_notification(stats, doc.subject)
        
    except Exception as e:
        logger.error(f"Email işleme hatası: {str(e)}")
        error_message = f"Communication: {doc.name}\nSubject: {doc.subject}\nError: {str(e)}\n{frappe.get_traceback()}"
        frappe.log_error(
            title="Invoice Email Processing Error",
            message=error_message
        )
        # Ana exception'da da kullanıcıya hata bildirimi gönder
        error_stats = {
            "total_detected": 0,
            "already_processed": 0,
            "newly_processed": 0,
            "errors": 1,
            "invoices_created": []
        }
        try:
            show_summary_notification(error_stats, doc.subject)
        except Exception as notify_error:
            logger.error(f"Error notification gönderme hatası: {str(notify_error)}")


def create_invoice_from_pdf(communication_doc, pdf_attachment):
    """PDF'den Invoice kaydı oluştur"""
    file_name = pdf_attachment.get('file_name', '')
    logger.info(f"PDF işleniyor: {file_name}")
    
    # Dosya adına göre platform tespiti (öncelikli)
    file_name_lower = file_name.lower() if file_name else ''
    platform_from_filename = detect_platform_from_filename(file_name_lower)
    logger.info(f"Dosya adından platform: {platform_from_filename}")
    
    extracted_data = extract_invoice_data_from_pdf(pdf_attachment)
    
    # PDF içeriğinden platform tespiti
    platform_from_content = extracted_data.get("platform")
    logger.info(f"İçerikten platform: {platform_from_content}")
    
    # Dosya adı tespiti öncelikli, yoksa içerik tespiti
    platform = platform_from_filename or platform_from_content
    
    # ÖNEMLİ: Platform tespit edilemezse işleme (1&1, diğer faturalar gibi)
    if not platform or platform == "unknown":
        logger.warning(f"Platform tespit edilemedi, email atlanıyor: {file_name}")
        return None
    
    logger.info(f"Seçilen platform: {platform}")
    
    if platform == "wolt":
        logger.info("Wolt Invoice oluşturuluyor")
        return create_wolt_invoice_doc(communication_doc, pdf_attachment, extracted_data)
    
    if platform == "uber_eats":
        logger.info("UberEats Invoice oluşturuluyor")
        return create_uber_eats_invoice_doc(communication_doc, pdf_attachment, extracted_data)
    
    logger.info("Lieferando Invoice oluşturuluyor")
    return create_lieferando_invoice_doc(communication_doc, pdf_attachment, extracted_data)


def create_lieferando_invoice_doc(communication_doc, pdf_attachment, extracted_data):
    """Lieferando Invoice kaydı oluştur"""
    invoice_number = extracted_data.get("invoice_number")
    
    # Duplicate kontrolü: Sadece invoice_number (Rechnungsnummer) ile kontrol
    if _check_invoice_exists(DOCTYPE_LIEFERANDO_INVOICE, invoice_number):
        return None
    
    invoice = frappe.new_doc(DOCTYPE_LIEFERANDO_INVOICE)
    invoice.update({
        "invoice_number": invoice_number or generate_temp_invoice_number(),
        "invoice_date": extracted_data.get("invoice_date") or frappe.utils.today(),
        "period_start": extracted_data.get("period_start"),
        "period_end": extracted_data.get("period_end"),
        "status": FIELD_STATUS_DRAFT,
        "supplier_name": extracted_data.get("supplier_name") or "yd.yourdelivery GmbH",
        "supplier_email": extracted_data.get("supplier_email") or communication_doc.sender,
        "supplier_ust_idnr": extracted_data.get("supplier_ust_idnr"),
        "supplier_geschäftsführer": extracted_data.get("supplier_geschäftsführer"),
        "supplier_amtsgericht": extracted_data.get("supplier_amtsgericht"),
        "supplier_hrb": extracted_data.get("supplier_hrb"),
        "supplier_iban": extracted_data.get("supplier_iban"),
        "restaurant_name": extracted_data.get("restaurant_name"),
        "customer_number": extracted_data.get("customer_number"),
        "customer_tax_number": extracted_data.get("customer_tax_number"),
        "customer_company": extracted_data.get("customer_company"),
        "restaurant_address": extracted_data.get("restaurant_address"),
        "customer_bank_iban": extracted_data.get("customer_bank_iban"),
        "total_orders": extracted_data.get("total_orders") or 0,
        "total_revenue": extracted_data.get("total_revenue") or 0,
        "online_paid_orders": extracted_data.get("online_paid_orders") if extracted_data.get("online_paid_orders") is not None else 0,
        "online_paid_amount": extracted_data.get("online_paid_amount") or 0,
        "cash_paid_orders": extracted_data.get("cash_paid_orders") or 0,
        "cash_paid_amount": extracted_data.get("cash_paid_amount") or 0,
        "cash_service_fee_amount": extracted_data.get("cash_service_fee_amount") or 0,
        "chargeback_orders": extracted_data.get("chargeback_orders") or 0,
        "chargeback_amount": extracted_data.get("chargeback_amount") or 0,
        "stamp_card_orders": extracted_data.get("stamp_card_orders") or 0,
        "stamp_card_amount": extracted_data.get("stamp_card_amount") or 0,
        "ausstehende_am_datum": extracted_data.get("invoice_date"),
        "ausstehende_onlinebezahlungen_betrag": extracted_data.get("outstanding_balance") or 0,
        "rechnungsausgleich_betrag": extracted_data.get("total_amount") or 0,
        "auszahlung_gesamt": extracted_data.get("payout_amount") or 0,
        "zu_begleichender_betrag": extracted_data.get("zu_begleichender_betrag") or 0,
        "confirmation_payment_date": extracted_data.get("confirmation_payment_date"),
        "confirmation_code_message": extracted_data.get("confirmation_code_message"),
        "service_fee_rate": extracted_data.get("service_fee_rate") or 30,
        "service_fee_amount": extracted_data.get("service_fee_amount") or 0,
        "admin_fee_rate": extracted_data.get("admin_fee_rate"),
        "admin_fee_amount": extracted_data.get("admin_fee_amount") or 0,
        "subtotal": extracted_data.get("subtotal") or 0,
        "tax_rate": extracted_data.get("tax_rate"),
        "tax_amount": extracted_data.get("tax_amount") or 0,
        "total_amount": extracted_data.get("total_amount") or 0,
        "paid_online_payments": extracted_data.get("paid_online_payments") or 0,
        "outstanding_amount": extracted_data.get("outstanding_amount") or 0,
        "payout_amount": extracted_data.get("payout_amount") or 0,
        "outstanding_balance": extracted_data.get("outstanding_balance") or 0,
        "email_subject": communication_doc.subject,
        "email_from": communication_doc.sender,
        "received_date": communication_doc.creation,
        "processed_date": frappe.utils.now(),
        "extraction_confidence": extracted_data.get("confidence", DEFAULT_EXTRACTION_CONFIDENCE),
        "raw_text": extracted_data.get("raw_text", "")
    })
    
    # Child table'ları ekle (order_items ve tip_items)
    order_items = extracted_data.get("order_items", [])
    if order_items:
        invoice.extend("order_items", order_items)
    
    tip_items = extracted_data.get("tip_items", [])
    if tip_items:
        invoice.extend("tip_items", tip_items)
    
    # name (ID) field'ını invoice_number (Rechnungsnummer) ile aynı yap
    invoice.name = invoice_number or generate_temp_invoice_number()
    
    invoice.insert(ignore_permissions=True, ignore_mandatory=True)
    attach_pdf_to_invoice(pdf_attachment, invoice.name, DOCTYPE_LIEFERANDO_INVOICE)
    notify_invoice_created(DOCTYPE_LIEFERANDO_INVOICE, invoice.name, invoice.invoice_number, communication_doc.subject)
    
    return invoice


def create_wolt_invoice_doc(communication_doc, pdf_attachment, extracted_data):
    """Wolt Invoice kaydı oluştur"""
    invoice_number = extracted_data.get("invoice_number")
    
    # Duplicate kontrolü: Sadece invoice_number (Rechnungsnummer) ile kontrol
    if _check_invoice_exists(DOCTYPE_WOLT_INVOICE, invoice_number):
        return None
    
    invoice = frappe.new_doc(DOCTYPE_WOLT_INVOICE)
    invoice.update({
        "invoice_number": invoice_number or generate_temp_invoice_number(),
        "invoice_date": extracted_data.get("invoice_date") or frappe.utils.today(),
        "period_start": extracted_data.get("period_start"),
        "period_end": extracted_data.get("period_end"),
        "status": FIELD_STATUS_DRAFT,
        "supplier_name": extracted_data.get("supplier_name") or "Wolt Enterprises Deutschland GmbH",
        "supplier_vat": extracted_data.get("supplier_vat"),
        "supplier_address": extracted_data.get("supplier_address"),
        "restaurant_name": extracted_data.get("restaurant_name"),
        "customer_number": extracted_data.get("customer_number"),
        "restaurant_address": extracted_data.get("restaurant_address"),
        "goods_net_7": extracted_data.get("goods_net_7") or 0,
        "goods_vat_7": extracted_data.get("goods_vat_7") or 0,
        "goods_gross_7": extracted_data.get("goods_gross_7") or 0,
        "goods_net_19": extracted_data.get("goods_net_19") or 0,
        "goods_vat_19": extracted_data.get("goods_vat_19") or 0,
        "goods_gross_19": extracted_data.get("goods_gross_19") or 0,
        "goods_net_total": extracted_data.get("goods_net_total") or 0,
        "goods_vat_total": extracted_data.get("goods_vat_total") or 0,
        "goods_gross_total": extracted_data.get("goods_gross_total") or 0,
        "distribution_net_total": extracted_data.get("distribution_net_total") or 0,
        "distribution_vat_total": extracted_data.get("distribution_vat_total") or 0,
        "distribution_gross_total": extracted_data.get("distribution_gross_total") or 0,
        "netprice_net_7": extracted_data.get("netprice_net_7") or 0,
        "netprice_vat_7": extracted_data.get("netprice_vat_7") or 0,
        "netprice_gross_7": extracted_data.get("netprice_gross_7") or 0,
        "netprice_net_19": extracted_data.get("netprice_net_19") or 0,
        "netprice_vat_19": extracted_data.get("netprice_vat_19") or 0,
        "netprice_gross_19": extracted_data.get("netprice_gross_19") or 0,
        "netprice_net_total": extracted_data.get("netprice_net_total") or 0,
        "netprice_vat_total": extracted_data.get("netprice_vat_total") or 0,
        "netprice_gross_total": extracted_data.get("netprice_gross_total") or 0,
        "end_amount_net": extracted_data.get("end_amount_net") or 0,
        "end_amount_vat": extracted_data.get("end_amount_vat") or 0,
        "end_amount_gross": extracted_data.get("end_amount_gross") or 0,
        "email_subject": communication_doc.subject,
        "email_from": communication_doc.sender,
        "received_date": communication_doc.creation,
        "processed_date": frappe.utils.now(),
        "extraction_confidence": extracted_data.get("confidence", DEFAULT_EXTRACTION_CONFIDENCE),
        "raw_text": extracted_data.get("raw_text", "")
    })
    
    # name (ID) field'ını invoice_number (Rechnungsnummer) ile aynı yap
    invoice.name = invoice_number or generate_temp_invoice_number()
    
    invoice.insert(ignore_permissions=True, ignore_mandatory=True)
    attach_pdf_to_invoice(pdf_attachment, invoice.name, DOCTYPE_WOLT_INVOICE)
    notify_invoice_created(DOCTYPE_WOLT_INVOICE, invoice.name, invoice.invoice_number, communication_doc.subject)
    
    return invoice


def check_pdf_has_uber_eats_header(pdf_attachment):
    """PDF içinde 'Bestell- und Zahlungsübersicht' başlığı var mı kontrol et (UberEats faturaları için)"""
    try:
        if PyPDF2 is None:
            logger.warning("PyPDF2 modülü yüklü değil")
            return False
        
        file_doc = frappe.get_doc("File", pdf_attachment.name)
        file_path = file_doc.get_full_path()
        
        # Sadece ilk sayfayı oku (başlık genellikle ilk sayfada)
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            if len(pdf_reader.pages) > 0:
                first_page_text = pdf_reader.pages[0].extract_text()
                normalized = (first_page_text or "").lower()
                
                # "bestell- und zahlungsübersicht" başlığı olmalı
                has_header = "bestell- und zahlungsübersicht" in normalized or "bestell- und zahlungsübersicht" in first_page_text
                
                result = has_header
                logger.debug(f"PDF UberEats header kontrolü: {pdf_attachment.file_name} → {result}")
                return result
        
        return False
    except Exception as e:
        logger.warning(f"PDF UberEats header kontrolü hatası: {str(e)}")
        return False


def check_pdf_has_selbstfakturierung(pdf_attachment):
    """PDF içinde 'Rechnung(Selbstfakturierung)' başlığı var mı kontrol et (Wolt faturaları için)"""
    try:
        if PyPDF2 is None:
            logger.warning("PyPDF2 modülü yüklü değil")
            return False
        
        file_doc = frappe.get_doc("File", pdf_attachment.name)
        file_path = file_doc.get_full_path()
        
        # Sadece ilk sayfayı oku (başlık genellikle ilk sayfada)
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            if len(pdf_reader.pages) > 0:
                first_page_text = pdf_reader.pages[0].extract_text()
                normalized = (first_page_text or "").lower()
                
                # Hem "rechnung" hem de "selbstfakturierung" kelimeleri olmalı
                has_rechnung = "rechnung" in normalized
                has_selbstfakturierung = "selbstfakturierung" in normalized
                
                result = has_rechnung and has_selbstfakturierung
                logger.debug(f"PDF Selbstfakturierung kontrolü: {pdf_attachment.file_name} → {result}")
                return result
        
        return False
    except Exception as e:
        logger.warning(f"PDF Selbstfakturierung kontrolü hatası: {str(e)}")
        return False


def check_pdf_has_wolt_netting_report(pdf_attachment):
    """PDF içinde 'Übersicht Umsätze und Auszahlungen' başlığı var mı kontrol et (Wolt netting raporu)"""
    try:
        if PyPDF2 is None:
            logger.warning("PyPDF2 modülü yüklü değil")
            return False
        
        file_doc = frappe.get_doc("File", pdf_attachment.name)
        file_path = file_doc.get_full_path()
        
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            if len(pdf_reader.pages) > 0:
                first_page_text = pdf_reader.pages[0].extract_text()
                normalized = (first_page_text or "").lower()
                
                has_header = "übersicht umsätze und auszahlungen" in normalized
                logger.debug(f"PDF Netting header kontrolü: {pdf_attachment.file_name} → {has_header}")
                return has_header
        
        return False
    except Exception as e:
        logger.warning(f"PDF Netting header kontrolü hatası: {str(e)}")
        return False


def extract_invoice_data_from_pdf(pdf_attachment):
    """PDF'den fatura verilerini çıkar"""
    try:
        if PyPDF2 is None:
            logger.warning("PyPDF2 modülü yüklü değil")
            return {"raw_text": "", "confidence": 0}
        
        file_doc = frappe.get_doc("File", pdf_attachment.name)
        file_path = file_doc.get_full_path()
        
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            full_text = "".join(page.extract_text() for page in pdf_reader.pages)
        
        data = {
            "raw_text": full_text,
            "confidence": DEFAULT_EXTRACTION_CONFIDENCE
        }
        
        # Rechnungsnummer extraction - UberEats faturaları için özel pattern (öncelikli)
        # Format: "Rechnungsnummer: UBER_DEU-FIGGGCEE-01-2025-0000001"
        uber_rechnung_match = re.search(r'Rechnungsnummer:\s*([A-Z0-9_\-]+)', full_text, re.IGNORECASE)
        if uber_rechnung_match:
            data["invoice_number"] = uber_rechnung_match.group(1).strip()
            logger.info(f"UberEats Rechnungsnummer bulundu: {data['invoice_number']}")
        else:
            # Rechnungsnummer extraction - Wolt faturaları için özel pattern
            # Format: "Rechnungsnummer DEU/25/HRB274170B/1/35" veya "Rechnungsnummer: DEU/25/HRB274170B/1/35"
            rechnung_match = re.search(r'Rechnungsnummer[\s:]+([A-Z]{3}/\d{2}/[A-Z0-9]+(?:/\d+)+)', full_text, re.IGNORECASE)
            if rechnung_match:
                data["invoice_number"] = rechnung_match.group(1).strip()
                logger.info(f"Rechnungsnummer bulundu: {data['invoice_number']}")
            else:
                # Fallback: Daha genel pattern'ler
                invoice_patterns = [
                    r'Rechnungsnummer[\s:]+([A-Z0-9\/\-]+)',
                    r'Invoice\s*(?:Number|No|#)[\s:]+([A-Z0-9\-]+)',
                    r'Rechnung\s*(?:Nr|#)[\s:]+([A-Z0-9\-]+)',
                    r'Fatura\s*(?:No|#)[\s:]+([A-Z0-9\-]+)',
                ]
                
                for pattern in invoice_patterns:
                    match = re.search(pattern, full_text, re.IGNORECASE)
                    if match:
                        invoice_num = match.group(1).strip()
                        # USt.-ID formatını (DE123456789) filtrele
                        if not re.match(r'^DE\d{9}$', invoice_num):
                            data["invoice_number"] = invoice_num
                            logger.info(f"Rechnungsnummer bulundu (fallback): {data['invoice_number']}")
                            break
        
        date_patterns = [
            r'Date[\s:]*(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4})',
            r'Datum[\s:]*(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4})',
            r'(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4})',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, full_text)
            if match:
                try:
                    data["invoice_date"] = parse_date(match.group(1))
                    break
                except:
                    pass
        
        total_patterns = [
            r'Total[\s:]*[€$£]?\s*([\d,\.]+)',
            r'Gesamt[\s:]*[€$£]?\s*([\d,\.]+)',
            r'Toplam[\s:]*[€$£]?\s*([\d,\.]+)',
            r'[€$£]\s*([\d,\.]+)',
        ]
        
        for pattern in total_patterns:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                amounts = []
                for m in matches:
                    try:
                        amounts.append(float(m.replace(',', '')))
                    except:
                        pass
                if amounts:
                    data["total_amount"] = max(amounts)
                    break
        
        iban_match = re.search(r'([A-Z]{2}\d{2}[\s]?[\d\s]{10,30})', full_text)
        if iban_match:
            data["iban"] = iban_match.group(1).replace(' ', '')
        
        platform = detect_invoice_platform(full_text)
        data["platform"] = platform or "lieferando"
        
        if platform == "wolt":
            data.update(extract_wolt_fields(full_text))
        elif platform == "uber_eats":
            data.update(extract_uber_eats_fields(full_text))
        else:
            data.update(extract_lieferando_fields(full_text))
        
        return data
        
    except ImportError:
        return {"raw_text": "", "confidence": 0}
    except Exception as e:
        frappe.log_error(
            title="PDF Extraction Error",
            message=f"Error: {str(e)}\n{frappe.get_traceback()}"
        )
        return {"raw_text": "", "confidence": 0}


def detect_platform_from_filename(file_name: str) -> str:
    """Dosya adından platform tespit et"""
    if not file_name:
        logger.debug("detect_platform_from_filename: Dosya adı boş")
        return None
    
    file_name_lower = file_name.lower()
    logger.debug(f"detect_platform_from_filename: {file_name_lower}")
    
    # ÖNEMLİ: "rechnung_und" ile başlayan dosyalar kesinlikle Lieferando
    if file_name_lower.startswith("rechnung_und"):
        logger.info("Lieferando pattern eşleşti: rechnung_und (başlangıç)")
        return "lieferando"
    
    # Wolt dosya adı pattern'leri:
    # - Edelweiss_Baumschulenstraße_2025-11-30_00:00:00.000_692cfcbbc3686f9e6b931ea6.pdf
    # - Edelweiss Baumschulenstraße__netting_report__semi_monthly__2025-11-16__2025-12-01.pdf
    # - Edelweiss Baumschulenstraße__sales_report__semi_monthly__2025-11-16__2025-12-01.pdf
    
    # Wolt pattern'leri: underscore ile ayrılmış tarih ve hash içeren dosyalar
    # veya __netting_report__ veya __sales_report__ içeren dosyalar
    wolt_patterns = [
        (r'__netting_report__', 'netting_report'),
        (r'__sales_report__', 'sales_report'),
        (r'_\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2}\.\d{3}_[a-f0-9]+\.pdf$', 'tarih_hash'),  # Tarih ve hash pattern
        (r'_\d{4}-\d{2}-\d{2}__\d{4}-\d{2}-\d{2}\.pdf$', 'tarih_araligi'),  # Tarih aralığı pattern
    ]
    
    for pattern, pattern_name in wolt_patterns:
        if re.search(pattern, file_name_lower):
            logger.info(f"Wolt pattern eşleşti: {pattern_name}")
            return "wolt"
    
    # Lieferando dosya adı pattern'leri (Wolt değilse)
    lieferando_patterns = [
        (r'^rechnung_und', 'rechnung_und_start'),  # Başlangıç kontrolü (zaten yukarıda kontrol edildi ama yine de)
        (r'lieferando', 'lieferando'),
        (r'yourdelivery', 'yourdelivery'),
        (r'takeaway', 'takeaway'),
        (r'rechnung_und', 'rechnung_und'),  # Herhangi bir yerde
    ]
    
    for pattern, pattern_name in lieferando_patterns:
        if re.search(pattern, file_name_lower):
            logger.info(f"Lieferando pattern eşleşti: {pattern_name}")
            return "lieferando"
    
    logger.debug("Dosya adından platform tespit edilemedi")
    return None


def detect_invoice_platform(full_text: str) -> str:
    """PDF içeriğinden platform tespit et"""
    normalized = (full_text or "").lower()
    
    # ÖNEMLİ: "Bestell- und Zahlungsübersicht" UberEats faturalarının karakteristik özelliği
    if "bestell- und zahlungsübersicht" in normalized or "bestell- und zahlungsübersicht" in full_text:
        logger.info("UberEats tespit edildi: 'Bestell- und Zahlungsübersicht' başlığı bulundu")
        return "uber_eats"
    
    # UberEats kontrolü
    if "uber eats" in normalized or "uber eats germany" in normalized:
        return "uber_eats"
    
    # ÖNEMLİ: "Rechnung (Selbstfakturierung)" Wolt faturalarının karakteristik özelliği
    # Hem "rechnung" hem de "selbstfakturierung" olmalı
    if "rechnung" in normalized and "selbstfakturierung" in normalized:
        # Lieferando değilse Wolt olarak işaretle
        if "lieferando" not in normalized and "yourdelivery" not in normalized and "takeaway" not in normalized:
            logger.info("Wolt tespit edildi: 'Rechnung (Selbstfakturierung)' başlığı bulundu")
            return "wolt"
    
    # Wolt kontrolü
    if "wolt" in normalized and "lieferando" not in normalized:
        return "wolt"
    
    # Lieferando kontrolü
    if "lieferando" in normalized or "yourdelivery" in normalized or "takeaway" in normalized:
        return "lieferando"
    
    return "unknown"


def extract_lieferando_fields(full_text: str) -> dict:
    """Lieferando fatura alanlarını çıkar"""
    data = {}
    
    customer_num_match = re.search(r'Kundennummer[\s:]*(\d+)', full_text)
    if customer_num_match:
        data["customer_number"] = customer_num_match.group(1)
    
    restaurant_match = re.search(r'z\.Hd\.\s*(.+?)(?:\n|$)', full_text)
    if restaurant_match:
        data["restaurant_name"] = restaurant_match.group(1).strip()
    
    period_match = re.search(r'(\d{2}-\d{2}-\d{4})\s+bis\s+(?:einschließlich\s+)?(\d{2}-\d{2}-\d{4})', full_text)
    if period_match:
        data["period_start"] = parse_date(period_match.group(1))
        data["period_end"] = parse_date(period_match.group(2))
    
    # Lieferando.de satırı (toplam sipariş + toplam ciro) - 1. sayfa
    # Örnek: "Lieferando.de (02-11-2025 bis einschließlich 08-11-2025): 26 Bestellungen im Wert von € 627,59"
    lieferando_line_match = re.search(
        r'Lieferando\.de\s*\([^)]+\)\s*:\s*(\d+)\s+Bestellungen\s+im\s+Wert\s+von\s*€\s*([\d,\.]+)',
        full_text,
        re.IGNORECASE
    )
    if lieferando_line_match:
        try:
            data["total_orders"] = int(lieferando_line_match.group(1))
        except ValueError:
            pass
        amount = parse_decimal(lieferando_line_match.group(2))
        if amount is not None:
            data["total_revenue"] = amount

    # Fallback: "Ihr Umsatz in der Zeit ..." satırı (toplam ciro)
    revenue_match = re.search(r'Ihr Umsatz in der Zeit[^€]*€\s*([\d,\.]+)', full_text)
    if revenue_match and data.get("total_revenue") is None:
        amount = parse_decimal(revenue_match.group(1))
        if amount is not None:
            data["total_revenue"] = amount

    # Fallback: "Gesamt X Bestellungen im Wert von € ..."
    if not data.get("total_orders") or data.get("total_revenue") is None:
        gesamt_match = re.search(
            r'Gesamt\s+(\d+)\s+Bestellungen?[^€]*€\s*([\d,\.]+)',
            full_text,
            re.IGNORECASE
        )
        if gesamt_match:
            try:
                data["total_orders"] = int(gesamt_match.group(1))
            except ValueError:
                pass
            amount = parse_decimal(gesamt_match.group(2))
            if amount is not None and data.get("total_revenue") is None:
                data["total_revenue"] = amount

    # Verwaltungsgebühr (Online-Zahlungen) satırı: online sipariş sayısı + online sipariş tutarı
    # Örnek: "Verwaltungsgebühr (Online-Zahlungen) (...): 21 Bestellungen im Wert von € 446,50"
    # Pattern'i multiline ve daha esnek hale getiriyoruz - newline karakterlerini de kabul ediyor
    admin_title_match = re.search(
        r'Verwaltungsgebühr\s*\(Online-Zahlungen\)\s*\([^)]+\)\s*:\s*(\d+)\s+Bestellungen\s+im\s+Wert\s+von\s*€\s*([\d,\.]+)',
        full_text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL
    )
    # Eğer ilk pattern match etmezse, daha esnek bir pattern dene (satırlar ayrılmış olabilir)
    if not admin_title_match:
        admin_title_match = re.search(
            r'Verwaltungsgebühr\s*\(Online-Zahlungen\)[\s\S]*?(\d+)\s+Bestellungen\s+im\s+Wert\s+von\s*€\s*([\d,\.]+)',
            full_text,
            re.IGNORECASE | re.MULTILINE | re.DOTALL
        )
    if admin_title_match:
        try:
            data["online_paid_orders"] = int(admin_title_match.group(1))
        except ValueError:
            pass
        amount = parse_decimal(admin_title_match.group(2))
        if amount is not None:
            data["online_paid_amount"] = amount

    # Verwaltungsgebühr satırındaki rate ve count: "Servicegebühr: € 0,64 x 21"
    admin_rate_match = re.search(
        r'Verwaltungsgebühr\s*\(Online-Zahlungen\)[\s\S]*?Servicegebühr:\s*€\s*([\d,\.]+)\s*x\s*(\d+)',
        full_text,
        re.IGNORECASE
    )
    if admin_rate_match:
        rate = parse_decimal(admin_rate_match.group(1))
        try:
            count = int(admin_rate_match.group(2))
        except ValueError:
            count = None

        if rate is not None:
            data["admin_fee_rate"] = rate
        if count is not None and (not data.get("online_paid_orders")):
            data["online_paid_orders"] = count
        if rate is not None and count is not None:
            data["admin_fee_amount"] = round(rate * count, 2)

    # Türetilen değerler (eğer PDF'de doğrudan yoksa)
    if (data.get("total_orders") is not None and data.get("online_paid_orders") is not None) and not data.get("cash_paid_orders"):
        cash_orders = max(0, int(data["total_orders"]) - int(data["online_paid_orders"]))
        if cash_orders > 0:
            data["cash_paid_orders"] = cash_orders

    if (data.get("total_revenue") is not None and data.get("online_paid_amount") is not None) and data.get("cash_paid_amount") is None:
        cash_amount = round(float(data["total_revenue"]) - float(data["online_paid_amount"]), 2)
        if cash_amount > 0:
            data["cash_paid_amount"] = cash_amount
    
    service_fee_match = re.search(r'Servicegebühr:\s*([\d,\.]+)%[^€]*€\s*[\d,\.]+\s*€\s*([\d,\.]+)', full_text)
    if service_fee_match:
        try:
            data["service_fee_rate"] = float(service_fee_match.group(1).replace(',', '.'))
        except ValueError:
            pass
        amount = parse_decimal(service_fee_match.group(2))
        if amount is not None:
            data["service_fee_amount"] = amount
    
    # NOTE: Eski regex (admin_fee_amount'a yanlış değer yazıyordu) kaldırıldı.
    
    subtotal_match = re.search(r'Zwischensumme\s*€\s*([\d,\.]+)', full_text)
    if subtotal_match:
        amount = parse_decimal(subtotal_match.group(1))
        if amount is not None:
            data["subtotal"] = amount
    
    tax_match = re.search(r'MwSt\.\s*\((\d+)%[^€]*€\s*[\d,\.]+\)\s*€\s*([\d,\.]+)', full_text)
    if tax_match:
        try:
            data["tax_rate"] = float(tax_match.group(1))
        except ValueError:
            pass
        amount = parse_decimal(tax_match.group(2))
        if amount is not None:
            data["tax_amount"] = amount
    
    total_match = re.search(r'Gesamtbetrag dieser Rechnung\s*€\s*([\d,\.]+)', full_text)
    if total_match:
        amount = parse_decimal(total_match.group(1))
        if amount is not None:
            data["total_amount"] = amount

    # Chargeback / Reversal (Rückbuchung)
    # Example: "Rückbuchung 2 Bestellungen im Wert von € 0,89"
    chargeback_match = re.search(
        r'R[üu]ckbuch\w*\s+(\d+)\s+Bestellungen?\s+im\s+Wert\s+von\s+€\s*([\d,\.]+)',
        full_text,
        re.IGNORECASE
    )
    if chargeback_match:
        try:
            data["chargeback_orders"] = int(chargeback_match.group(1))
        except ValueError:
            pass
        cb_amount = parse_decimal(chargeback_match.group(2))
        if cb_amount is not None:
            data["chargeback_amount"] = cb_amount
    
    paid_match = re.search(r'Verrechnet mit eingegangenen Onlinebezahlungen\s*€\s*([\d,\.]+)', full_text)
    if paid_match:
        amount = parse_decimal(paid_match.group(1))
        if amount is not None:
            data["paid_online_payments"] = amount
    
    outstanding_match = re.search(r'Offener Rechnungsbetrag\s*€\s*([\d,\.]+)', full_text)
    if outstanding_match:
        amount = parse_decimal(outstanding_match.group(1))
        if amount is not None:
            data["outstanding_amount"] = amount
    
    ausstehende_match = re.search(r'Ausstehende Onlinebezahlungen am[^€]*€\s*([\d,\.]+)', full_text)
    if ausstehende_match:
        amount = parse_decimal(ausstehende_match.group(1))
        if amount is not None:
            data["outstanding_balance"] = amount
    
    auszahlung_gesamt_match = re.search(r'COLLECTIVE GmbH[^€]*€\s*([\d,\.]+)\s*Datum', full_text, re.DOTALL)
    if auszahlung_gesamt_match:
        amount = parse_decimal(auszahlung_gesamt_match.group(1))
        if amount is not None:
            data["payout_amount"] = amount
    
    company_match = re.search(r'z\.Hd\.\s+(.+?GmbH)', full_text)
    if company_match:
        data["customer_company"] = company_match.group(1).strip()
    
    cust_iban_match = re.search(r'Bankkonto\s+(DE[\d\s]+)', full_text)
    if cust_iban_match:
        data["customer_bank_iban"] = cust_iban_match.group(1).replace(' ', '')
    
    supp_iban_match = re.search(r'IBAN:\s+(DE[\d\s]+)', full_text)
    if supp_iban_match:
        data["supplier_iban"] = supp_iban_match.group(1).replace(' ', '')
    
    ust_match = re.search(r'USt\.-IdNr\.\s+(DE\d+)', full_text)
    if ust_match:
        data["supplier_ust_idnr"] = ust_match.group(1)
    
    # Steuernummer (Tax Number) extraction
    # Pattern'ler: "Steuernummer: DE361596531" veya "Steuernummer: DE36/159/6531"
    steuernummer_patterns = [
        r'Steuernummer[:\s]+(DE\d+)',
        r'Steuernummer[:\s]+([A-Z]{2}\d+)',
        r'Steuernummer[:\s]+([A-Z]{2}[\d\/]+)',  # DE36/159/6531 formatı
    ]
    
    for pattern in steuernummer_patterns:
        tax_match = re.search(pattern, full_text, re.IGNORECASE)
        if tax_match:
            tax_number = tax_match.group(1).strip()
            # Format düzelt (DE36/159/6531 -> DE361596531)
            tax_number = tax_number.replace('/', '')
            data["customer_tax_number"] = tax_number
            break
    
    # Servicegebühren extraction (cash service fees)
    # Pattern: "Servicegebühren (02-11-2025 bis einschließlich 08-11-2025): 5 Bestellungen im Wert von € 3,38"
    servicegebuehren_match = re.search(
        r'Servicegebühren\s*\([^)]+\):\s*(\d+)\s+Bestellungen\s+im\s+Wert\s+von\s+€\s*([\d,\.]+)',
        full_text,
        re.IGNORECASE
    )
    if servicegebuehren_match:
        orders = int(servicegebuehren_match.group(1))
        amount = parse_decimal(servicegebuehren_match.group(2))
        if amount is not None:
            # Bu satır cash service fees için olabilir
            if not data.get("cash_paid_orders") or data.get("cash_paid_orders") == 0:
                data["cash_paid_orders"] = orders
            if not data.get("cash_service_fee_amount") or data.get("cash_service_fee_amount") == 0:
                data["cash_service_fee_amount"] = amount

    # Einzelauflistung - Order Items (PAGE 2)
    # Tablo başlığı: "Datum # €"
    # Satır örneği: "02-11-2025, 12:38:34 H7HH6B 22,00*" (sonundaki * online)
    try:
        order_items = []
        lines = (full_text or "").splitlines()
        header_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "Datum # €" or ("Datum" in line and "#" in line and "€" in line and len(line.strip()) <= 15):
                header_idx = i
                break

        if header_idx is not None:
            row_re = re.compile(
                r'^(?P<dt>\d{2}-\d{2}-\d{4},\s*\d{2}:\d{2}:\d{2})\s+(?P<oid>[A-Z0-9]+)\s+(?P<amt>[\d,\.]+)\*?$'
            )
            for line in lines[header_idx + 1:]:
                clean = (line or "").strip()
                if not clean:
                    break
                # dipnot / footer gelince dur
                if clean.startswith("**") or "Powered by TCPDF" in clean:
                    break
                m = row_re.match(clean)
                if not m:
                    continue
                dt_str = m.group("dt").strip()
                oid = m.group("oid").strip()
                amt_str = m.group("amt").strip()
                is_online = 1 if clean.endswith("*") else 0
                amt = parse_decimal(amt_str)
                order_dt = None
                try:
                    order_dt = datetime.strptime(dt_str, "%d-%m-%Y, %H:%M:%S")
                except Exception:
                    order_dt = None
                if amt is None:
                    continue
                order_items.append({
                    "order_date": order_dt,
                    "order_id": oid,
                    "amount": amt,
                    "is_online": is_online,
                })

        if order_items:
            data["order_items"] = order_items
    except Exception:
        # Parsing hatası olursa ana extract'i bozma
        pass

    # Trinkgelder - Tip Items (PAGE 3) (opsiyonel)
    # Eğer PDF'de "Trinkgelder" tablosu varsa: "Trinkgelder erhalten von" satırından sonra "Datum # €" başlığı gelir.
    try:
        tip_items = []
        lines = (full_text or "").splitlines()
        tips_start = None
        # "Trinkgelder erhalten von" satırını bul (bahşiş tablosu başlığı)
        for i, line in enumerate(lines):
            if "Trinkgelder erhalten von" in (line or ""):
                tips_start = i
                break
        # Eğer "Trinkgelder erhalten von" bulunamazsa, "Trinkgelder" içeren herhangi bir satırı ara
        if tips_start is None:
            for i, line in enumerate(lines):
                if "Trinkgelder" in (line or "") and "erhalten von" in (line or ""):
                    tips_start = i
                    break
        
        if tips_start is not None:
            header_idx = None
            # "Trinkgelder erhalten von" satırından sonra "Datum # €" başlığını ara
            for j in range(tips_start, len(lines)):
                if (lines[j] or "").strip() == "Datum # €":
                    header_idx = j
                    break
            if header_idx is not None:
                row_re = re.compile(
                    r'^(?P<dt>\d{2}-\d{2}-\d{4},\s*\d{2}:\d{2}:\d{2})\s+(?P<tid>[A-Z0-9]+)\s+(?P<amt>[\d,\.]+)$'
                )
                for line in lines[header_idx + 1:]:
                    clean = (line or "").strip()
                    if not clean:
                        break
                    if clean.startswith("**") or "Powered by TCPDF" in clean:
                        break
                    m = row_re.match(clean)
                    if not m:
                        continue
                    dt_str = m.group("dt").strip()
                    tid = m.group("tid").strip()
                    amt = parse_decimal(m.group("amt").strip())
                    tip_dt = None
                    try:
                        tip_dt = datetime.strptime(dt_str, "%d-%m-%Y, %H:%M:%S")
                    except Exception:
                        tip_dt = None
                    if amt is None:
                        continue
                    tip_items.append({
                        "tip_date": tip_dt,
                        "tip_id": tid,
                        "amount": amt,
                    })
        if tip_items:
            data["tip_items"] = tip_items
    except Exception:
        pass

    # Supplier footer fields (some PDFs include these as plain text)
    # Geschäftsführer
    try:
        gf_match = re.search(r'Geschäftsführer\s*:\s*([^\n]+)', full_text, re.IGNORECASE)
        if gf_match:
            gf = (gf_match.group(1) or "").strip()
            if gf:
                data["supplier_geschäftsführer"] = gf
        else:
            # Sometimes names follow on next line(s)
            gf_block = re.search(r'Geschäftsführer\s*:\s*([\s\S]{0,120})', full_text, re.IGNORECASE)
            if gf_block:
                block = (gf_block.group(1) or "").strip()
                # take first 2 lines max, stop before common next labels
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                if lines:
                    joined = " ".join(lines[:2])
                    joined = re.split(r'\b(IBAN|USt\.?-IdNr|HRB|Amtsgericht|T:|Tel\.?)\b', joined, flags=re.IGNORECASE)[0].strip()
                    if joined:
                        data["supplier_geschäftsführer"] = joined
    except Exception:
        pass

    # Amtsgericht
    try:
        amts_match = re.search(r'Amtsgericht\s*[:\s]+([^\n]+)', full_text, re.IGNORECASE)
        if amts_match:
            amts = (amts_match.group(0) or "").strip()
            # keep full "Amtsgericht Berlin-..." text for print format
            if amts:
                data["supplier_amtsgericht"] = amts
    except Exception:
        pass

    # HRB
    try:
        hrb_match = re.search(r'HRB\s*[:\s]+([A-Z0-9]+)', full_text, re.IGNORECASE)
        if hrb_match:
            hrb = (hrb_match.group(1) or "").strip()
            if hrb:
                data["supplier_hrb"] = hrb
    except Exception:
        pass

    # Confirmation & Payment fields (only present on some documents)
    try:
        due_match = re.search(r'Zu\s+begleichender\s+Betrag\s*:\s*€?\s*([\d,\.]+)', full_text, re.IGNORECASE)
        if due_match:
            amt = parse_decimal(due_match.group(1))
            if amt is not None:
                data["zu_begleichender_betrag"] = amt
    except Exception:
        pass

    try:
        # Example: "Am 02-11-2025 wurde an Sie ..."
        conf_date_match = re.search(r'Am\s+(\d{2}[-\.]\d{2}[-\.]\d{4})\s+wurde\s+an\s+Sie', full_text, re.IGNORECASE)
        if conf_date_match:
            data["confirmation_payment_date"] = parse_date(conf_date_match.group(1).replace(".", "-"))
    except Exception:
        pass

    try:
        if re.search(r'Bestätigungscode', full_text, re.IGNORECASE):
            # Grab the line/paragraph containing "Bestätigungscode" (short)
            snippet_match = re.search(r'(.{0,10}Bestätigungscode.{0,220})', full_text, re.IGNORECASE | re.DOTALL)
            if snippet_match:
                msg = (snippet_match.group(1) or "").replace("\n", " ").strip()
                msg = re.sub(r'\s+', ' ', msg)
                if msg:
                    data["confirmation_code_message"] = msg[:255]
    except Exception:
        pass
    
    # Stempelkarte (Stamp Card / Loyalty Program) extraction
    # Pattern: "davon mit Stempelkarte bezahlt **: 1 Bestellung im Wert von € 12,69"
    try:
        stamp_card_patterns = [
            r'davon mit Stempelkarte bezahlt\s*\*\*\s*:\s*(\d+)\s+Bestellung[^€]*€\s*([\d,\.]+)',  # With colon
            r'davon mit Stempelkarte bezahlt\s*\*\*\s+(\d+)\s+Bestellung[^€]*€\s*([\d,\.]+)',  # Without colon
            r'Stempelkarte bezahlt\s*\*\*\s*:\s*(\d+)\s+Bestellung[^€]*€\s*([\d,\.]+)',  # Alternative format
        ]
        
        for pattern in stamp_card_patterns:
            stamp_card_match = re.search(pattern, full_text, re.IGNORECASE)
            if stamp_card_match:
                try:
                    orders = int(stamp_card_match.group(1))
                    amount = parse_decimal(stamp_card_match.group(2))
                    if amount is not None:
                        data["stamp_card_orders"] = orders
                        data["stamp_card_amount"] = amount
                        break
                except (ValueError, IndexError):
                    continue
    except Exception:
        pass
    
    return data


def handle_wolt_netting_report(communication_doc, pdf_attachment):
    """Wolt netting raporunu ilgili Wolt Invoice kaydına ekle"""
    try:
        if PyPDF2 is None:
            logger.warning("PyPDF2 modülü yüklü değil")
            return
        
        file_doc = frappe.get_doc("File", pdf_attachment.name)
        file_path = file_doc.get_full_path()
        
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            full_text = "".join(page.extract_text() for page in pdf_reader.pages)
        
        # Rechnungsnummer bul (tablo başlığındaki "Gesamtbetrag" değerini almamak için filtrele)
        invoice_number = None
        for m in re.finditer(r'Rechnungsnummer\s*[:\-]?\s*([A-Z0-9\/\-]+)', full_text, re.IGNORECASE):
            candidate = (m.group(1) or "").strip()
            if candidate.lower() == "gesamtbetrag":
                continue
            invoice_number = candidate
            break
        
        # Eğer üstte bulunamadıysa, PDF içindeki DEU/.. formatını yakala (örn: DEU/25/HRB274170B/1/37)
        if not invoice_number:
            deu_matches = re.findall(r'DEU/\d{2}/[A-Z0-9]+(?:/\d+)+', full_text, flags=re.IGNORECASE)
            if deu_matches:
                invoice_number = deu_matches[0].strip()
        
        # Normalizasyon
        if invoice_number:
            invoice_number = invoice_number.upper()
        
        if not invoice_number:
            logger.warning(f"Netting raporunda Rechnungsnummer bulunamadı: {pdf_attachment.file_name}")
            return
        
        existing_invoice = frappe.db.exists(DOCTYPE_WOLT_INVOICE, {"invoice_number": invoice_number})
        if not existing_invoice:
            logger.warning(f"Netting raporu için Wolt Invoice bulunamadı (Rechnungsnummer: {invoice_number})")
            return
        
        logger.info(f"Netting raporu Wolt Invoice'a eklenecek (Rechnungsnummer: {invoice_number})")
        
        # PDF'i yeni alana attach et
        attach_pdf_to_invoice(pdf_attachment, invoice_number, DOCTYPE_WOLT_INVOICE, FIELD_NETTING_REPORT_PDF)
        
        # Raw text ve parse edilmiş alanları sakla
        update_values = {"netting_raw_text": full_text}
        
        parsed_fields = extract_netting_fields(full_text)
        if parsed_fields:
            update_values["netting_parsed_json"] = json.dumps(parsed_fields, ensure_ascii=True)
            logger.info(f"Netting parsed fields: {parsed_fields}")
            
            # Ayrı alanlara yaz (görünür özet)
            mapping = {
                "merchant_invoice_number": "netting_merchant_invoice",
                "merchant_net": "netting_merchant_net",
                "merchant_vat": "netting_merchant_vat",
                "merchant_gross": "netting_merchant_gross",
                "wolt_invoice_number": "netting_wolt_invoice",
                "wolt_net": "netting_wolt_net",
                "wolt_vat": "netting_wolt_vat",
                "wolt_gross": "netting_wolt_gross",
                "net_payout": "netting_net_payout",
            }
            for src, target in mapping.items():
                if src in parsed_fields and parsed_fields[src] is not None:
                    update_values[target] = parsed_fields[src]
        frappe.db.set_value("Wolt Invoice", invoice_number, update_values)
        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error(
            title="Wolt Netting Report Processing Error",
            message=f"PDF: {pdf_attachment.file_name}\nError: {str(e)}\n{frappe.get_traceback()}"
        )


def extract_netting_fields(full_text: str) -> dict:
    """
    Netting raporundan temel rakamları çıkarır:
    - merchant_invoice_number / net / vat / gross
    - wolt_invoice_number / net / vat / gross
    - net_payout
    Döndürdüğü değerler parse edilebilenler; bulunamazsa alan boş kalır.
    """
    if not full_text:
        return {}
    
    result = {}
    
    # Tüm satırları al
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
    
    # DEU/... içeren satırları sırayla yakala; ilkini merchant, ikincisini wolt varsay
    invoice_rows = []
    row_pattern = re.compile(r'(DEU/[A-Z0-9\/]+).*?([-+]?\d[\d\.,]*).*?([-+]?\d[\d\.,]*).*?([-+]?\d[\d\.,]*)')
    for ln in lines:
        m = row_pattern.search(ln)
        if m:
            invoice_rows.append(m.groups())
    
    if invoice_rows:
        inv, net, vat, gross = invoice_rows[0]
        result["merchant_invoice_number"] = inv
        result["merchant_net"] = parse_decimal(net)
        result["merchant_vat"] = parse_decimal(vat)
        result["merchant_gross"] = parse_decimal(gross)
    if len(invoice_rows) > 1:
        inv, net, vat, gross = invoice_rows[1]
        result["wolt_invoice_number"] = inv
        result["wolt_net"] = parse_decimal(net)
        result["wolt_vat"] = parse_decimal(vat)
        result["wolt_gross"] = parse_decimal(gross)
    
    # Net payout (Nettoauszahlung)
    payout_match = re.search(r'Nettoauszahlung\s+([\d\.,]+)', full_text, re.IGNORECASE)
    if payout_match:
        result["net_payout"] = parse_decimal(payout_match.group(1))
    else:
        # Yedek: "Nettoauszahlung" satırında negatif/pozitif miktarları tara
        payout_line = next((ln for ln in lines if "nettoauszahlung" in ln.lower()), None)
        if payout_line:
            amt_match = re.search(r'[-+]?\d[\d\.,]*', payout_line)
            if amt_match:
                result["net_payout"] = parse_decimal(amt_match.group(0))
    
    return {k: v for k, v in result.items() if v is not None}


def extract_wolt_fields(full_text: str) -> dict:
    """Wolt fatura alanlarını çıkar"""
    data = {"platform": "wolt"}
    clean_text = (full_text or "").replace("|", " ")
    
    # Rechnungsnummer extraction - Wolt faturaları için özel format
    # Format: "Rechnungsnummer DEU/25/HRB274170B/1/35" veya "Rechnungsnummer: DEU/25/HRB274170B/1/35"
    rechnung_match = re.search(r'Rechnungsnummer[\s:]+([A-Z]{3}/\d{2}/[A-Z0-9]+(?:/\d+)+)', full_text, re.IGNORECASE)
    if rechnung_match:
        data["invoice_number"] = rechnung_match.group(1).strip()
        logger.info(f"Wolt Rechnungsnummer bulundu: {data['invoice_number']}")
    
    supplier_match = re.search(r'Bill To\s+(.*?)Leistungszeitraum', full_text, re.DOTALL)
    if supplier_match:
        block = supplier_match.group(1)
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines:
            data["supplier_name"] = lines[0]
        address_lines = lines[1:]
        if address_lines:
            data["supplier_address"] = " ".join(address_lines)
    else:
        data["supplier_name"] = "Wolt Enterprises Deutschland GmbH"
    
    supplier_vat_match = re.search(r'USt\.-ID:\s*(DE\d+)', full_text)
    if supplier_vat_match:
        data["supplier_vat"] = supplier_vat_match.group(1)
    
    invoice_date_match = re.search(r'Rechnungsdatum\s+(\d{2}\.\d{2}\.\d{4})', full_text)
    if invoice_date_match:
        data["invoice_date"] = parse_date(invoice_date_match.group(1))
    
    period_match = re.search(r'Leistungszeitraum\s+(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})', full_text)
    if period_match:
        data["period_start"] = parse_date(period_match.group(1))
        data["period_end"] = parse_date(period_match.group(2))
    
    restaurant_match = re.search(r'Restaurant\s+([^\n]+)', full_text)
    if restaurant_match:
        data["restaurant_name"] = restaurant_match.group(1).strip()
    
    business_id_match = re.search(r'Geschäfts-ID:\s*([A-Z0-9 ]+)', full_text)
    if business_id_match:
        data["customer_number"] = business_id_match.group(1).strip()
    
    goods_matches = re.findall(r'Summe verkaufte Waren\s+([\-\d,\.]+)\s+(7\.00|19\.00)\s+([\-\d,\.]+)\s+([\-\d,\.]+)', clean_text)
    for net, rate, vat, gross in goods_matches:
        parsed = (
            parse_decimal(net),
            parse_decimal(vat),
            parse_decimal(gross),
        )
        if rate.startswith("7"):
            data["goods_net_7"], data["goods_vat_7"], data["goods_gross_7"] = parsed
        else:
            data["goods_net_19"], data["goods_vat_19"], data["goods_gross_19"] = parsed
    
    goods_total_match = re.search(r'Zwischensumme aller verkauften Waren \(A\)\s+([\-\d,\.]+)\s+([\-\d,\.]+)\s+([\-\d,\.]+)', clean_text)
    if goods_total_match:
        data["goods_net_total"] = parse_decimal(goods_total_match.group(1))
        data["goods_vat_total"] = parse_decimal(goods_total_match.group(2))
        data["goods_gross_total"] = parse_decimal(goods_total_match.group(3))
    
    distribution_match = re.search(r'Zwischensumme Wolt Vertrieb \(B\)\s+([\-\d,\.]+)\s+([\-\d,\.]+)\s+([\-\d,\.]+)', clean_text)
    if distribution_match:
        data["distribution_net_total"] = parse_decimal(distribution_match.group(1))
        data["distribution_vat_total"] = parse_decimal(distribution_match.group(2))
        data["distribution_gross_total"] = parse_decimal(distribution_match.group(3))
    
    netprice_matches = re.findall(
        r'Summe Nettopreis \(A\s*-\s*B\) mit Umsatzsteuer\s+(7\.00|19\.00)\s*%[\s|]+([\-\d,\.]+)[\s|]+(?:7\.00|19\.00)[\s|]+([\-\d,\.]+)[\s|]+([\-\d,\.]+)',
        clean_text
    )
    for rate, net, vat, gross in netprice_matches:
        values = (
            parse_decimal(net),
            parse_decimal(vat),
            parse_decimal(gross),
        )
        if rate.startswith("7"):
            data["netprice_net_7"], data["netprice_vat_7"], data["netprice_gross_7"] = values
        else:
            data["netprice_net_19"], data["netprice_vat_19"], data["netprice_gross_19"] = values
    
    if any(key in data for key in ("netprice_net_7", "netprice_net_19")):
        data["netprice_net_total"] = (data.get("netprice_net_7") or 0) + (data.get("netprice_net_19") or 0)
        data["netprice_vat_total"] = (data.get("netprice_vat_7") or 0) + (data.get("netprice_vat_19") or 0)
        data["netprice_gross_total"] = (data.get("netprice_gross_7") or 0) + (data.get("netprice_gross_19") or 0)
    
    end_amount_match = re.search(r'Endbetrag\s+([\-\d,\.]+)\s+([\-\d,\.]+)\s+([\-\d,\.]+)', clean_text)
    if end_amount_match:
        data["end_amount_net"] = parse_decimal(end_amount_match.group(1))
        data["end_amount_vat"] = parse_decimal(end_amount_match.group(2))
        data["end_amount_gross"] = parse_decimal(end_amount_match.group(3))
        data["total_amount"] = data.get("end_amount_gross")
    
    return data


def extract_uber_eats_fields(full_text: str) -> dict:
    """UberEats fatura alanlarını çıkar"""
    data = {"platform": "uber_eats"}
    clean_text = (full_text or "").replace("|", " ")
    
    # Rechnungsnummer extraction - UberEats formatı: UBER_DEU-FIGGGCEE-01-2025-0000001
    rechnung_match = re.search(r'Rechnungsnummer:\s*([A-Z0-9_\-]+)', full_text, re.IGNORECASE)
    if rechnung_match:
        data["invoice_number"] = rechnung_match.group(1).strip()
        logger.info(f"UberEats Rechnungsnummer bulundu: {data['invoice_number']}")
    
    # Rechnungsdatum
    invoice_date_match = re.search(r'Rechnungsdatum:\s*(\d{2}\.\d{2}\.\d{4})', full_text)
    if invoice_date_match:
        data["invoice_date"] = parse_date(invoice_date_match.group(1))
    
    # Steuerdatum
    tax_date_match = re.search(r'Steuerdatum\s+(\d{2}\.\d{2}\.\d{4})', full_text)
    if tax_date_match:
        data["tax_date"] = parse_date(tax_date_match.group(1))
    
    # Zeitraum
    period_match = re.search(r'Zeitraum:\s*(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})', full_text)
    if period_match:
        data["period_start"] = parse_date(period_match.group(1))
        data["period_end"] = parse_date(period_match.group(2))
    else:
        # Alternatif format: "vom 11.11.2025 bis zum 16.11.2025"
        period_match2 = re.search(r'vom\s+(\d{2}\.\d{2}\.\d{4})\s+bis\s+(?:zum\s+)?(\d{2}\.\d{2}\.\d{4})', full_text)
        if period_match2:
            data["period_start"] = parse_date(period_match2.group(1))
            data["period_end"] = parse_date(period_match2.group(2))
    
    # Customer company (CC CULINARY COLLECTIVE GmbH)
    customer_company_match = re.search(r'CC CULINARY COLLECTIVE GmbH', full_text, re.IGNORECASE)
    if customer_company_match:
        data["customer_company"] = "CC CULINARY COLLECTIVE GmbH"
    
    # Restaurant name
    # Önce "Restaurant:" etiketi ile arama
    restaurant_match = re.search(r'Restaurant:\s*([^\n]+)', full_text)
    if restaurant_match:
        data["restaurant_name"] = restaurant_match.group(1).strip()
    else:
        # Alternatif: "Burger Boost - CC Culinary Collective (Weseler Straße)" formatı
        # "Rechnung" bölümünde veya "Umsatzbericht" bölümünde olabilir
        restaurant_match2 = re.search(r'Burger Boost\s*-\s*CC Culinary Collective\s*\(([^\)]+)\)', full_text, re.IGNORECASE | re.DOTALL)
        if restaurant_match2:
            location = restaurant_match2.group(1).strip()
            data["restaurant_name"] = f"Burger Boost - CC Culinary Collective ({location})"
        else:
            # Daha genel pattern: "Burger Boost - CC Culinary Collective" (parantez olmadan)
            restaurant_match3 = re.search(r'(Burger Boost\s*-\s*CC Culinary Collective[^\n]*)', full_text, re.IGNORECASE)
            if restaurant_match3:
                data["restaurant_name"] = restaurant_match3.group(1).strip()
    
    # Restaurant address (Hohenzollerndamm 58,14199,Berlin, Germany)
    # "Rechnung" bölümünden sonraki adres bilgisi
    # Format: "Hohenzollerndamm 58,14199,Berlin\nGermany" veya "Hohenzollerndamm 58,14199,Berlin, Germany"
    address_match = re.search(r'Hohenzollerndamm\s+(\d+)[,\s]+(\d+)[,\s]+([A-Za-z]+)[,\s]*([A-Za-z]+)?', full_text, re.IGNORECASE | re.MULTILINE)
    if address_match:
        street = address_match.group(1)
        postal = address_match.group(2)
        city = address_match.group(3)
        country = address_match.group(4) or "Germany"
        data["restaurant_address"] = f"Hohenzollerndamm {street}, {postal}, {city}, {country}"
    else:
        # Alternatif: "CC CULINARY COLLECTIVE GmbH" sonrasındaki adres satırları
        address_match2 = re.search(r'CC CULINARY COLLECTIVE GmbH\s+([^\n]+)\s+([^\n]+)', full_text, re.IGNORECASE | re.MULTILINE)
        if address_match2:
            line1 = address_match2.group(1).strip()
            line2 = address_match2.group(2).strip()
            data["restaurant_address"] = f"{line1}, {line2}"
    
    # Handelsregisternummer (HRB 274170)
    hrb_match = re.search(r'Handelsregisternummer:\s*([A-Z0-9\s]+)', full_text, re.IGNORECASE)
    if hrb_match:
        data["business_id"] = hrb_match.group(1).strip()
    
    # USt-IdNr. (DE361596531) - Müşteri USt-ID
    customer_vat_match = re.search(r'USt-IdNr\.:\s*(DE\d+)', full_text, re.IGNORECASE)
    if customer_vat_match:
        data["customer_vat"] = customer_vat_match.group(1).strip()
    
    # St-Nr. (127/249/52915) - Vergi numarası
    tax_number_match = re.search(r'St-Nr\.:\s*([\d\/]+)', full_text, re.IGNORECASE)
    if tax_number_match:
        data["tax_number"] = tax_number_match.group(1).strip()
    
    # Total orders
    orders_match = re.search(r'(\d+)\s+Bestellungen im Gesamtwert', full_text)
    if orders_match:
        data["total_orders"] = int(orders_match.group(1))
    
    # Total order value
    order_value_match = re.search(r'Bestellungen im Gesamtwert von:\s*€\s*([\d,\.]+)', full_text)
    if order_value_match:
        data["total_order_value"] = parse_decimal(order_value_match.group(1))
    
    # Gross revenue after discounts
    gross_revenue_match = re.search(r'Bruttoumsatz nach Rabatten\s*€\s*([\d,\.]+)', full_text)
    if gross_revenue_match:
        data["gross_revenue_after_discounts"] = parse_decimal(gross_revenue_match.group(1))
    
    # Commission own delivery
    commission_own_match = re.search(r'Provision, eigene Lieferung.*?€\s*([\d,\.]+)', full_text)
    if commission_own_match:
        data["commission_own_delivery"] = parse_decimal(commission_own_match.group(1))
    
    # Commission pickup
    commission_pickup_match = re.search(r'Provision, Abholung.*?€\s*([\d,\.]+)', full_text)
    if commission_pickup_match:
        data["commission_pickup"] = parse_decimal(commission_pickup_match.group(1))
    
    # Uber Eats fee
    uber_fee_match = re.search(r'Uber Eats Gebühr\s*€\s*([\d,\.]+)', full_text)
    if uber_fee_match:
        data["uber_eats_fee"] = parse_decimal(uber_fee_match.group(1))
    
    # VAT 19%
    vat_match = re.search(r'MwSt\.\s*\(19%[^€]*€\s*([\d,\.]+)', full_text)
    if vat_match:
        data["vat_19_percent"] = parse_decimal(vat_match.group(1))
    
    # Cash collected
    cash_match = re.search(r'Eingenommenes Bargeld\s*€\s*([\d,\.]+)', full_text)
    if cash_match:
        data["cash_collected"] = parse_decimal(cash_match.group(1))
    
    # Total payout
    payout_match = re.search(r'Gesamtauszahlung\s*€\s*([\d,\.]+)', full_text)
    if payout_match:
        data["total_payout"] = parse_decimal(payout_match.group(1))
    
    # Net amount
    net_match = re.search(r'Gesamtnettobetrag\s*([\d,\.]+)\s*€', full_text)
    if net_match:
        data["net_amount"] = parse_decimal(net_match.group(1))
    
    # VAT amount
    vat_amount_match = re.search(r'Gesamtbetrag USt 19%\s*([\d,\.]+)\s*€', full_text)
    if vat_amount_match:
        data["vat_amount"] = parse_decimal(vat_amount_match.group(1))
    
    # Total amount
    total_match = re.search(r'Gesamtbetrag\s*([\d,\.]+)\s*€', full_text)
    if total_match:
        data["total_amount"] = parse_decimal(total_match.group(1))
    
    return data


def create_uber_eats_invoice_doc(communication_doc, pdf_attachment, extracted_data):
    """UberEats Invoice kaydı oluştur"""
    invoice_number = extracted_data.get("invoice_number")
    
    # Duplicate kontrolü: Sadece invoice_number (Rechnungsnummer) ile kontrol
    if _check_invoice_exists(DOCTYPE_UBER_EATS_INVOICE, invoice_number):
        return None
    
    invoice = frappe.new_doc(DOCTYPE_UBER_EATS_INVOICE)
    invoice.update({
        "invoice_number": invoice_number or generate_temp_invoice_number(),
        "invoice_date": extracted_data.get("invoice_date") or frappe.utils.today(),
        "tax_date": extracted_data.get("tax_date"),
        "period_start": extracted_data.get("period_start"),
        "period_end": extracted_data.get("period_end"),
        "status": FIELD_STATUS_DRAFT,
        "supplier_name": extracted_data.get("supplier_name") or "Uber Eats Germany GmbH",
        "supplier_vat": extracted_data.get("supplier_vat"),
        "supplier_address": extracted_data.get("supplier_address"),
        "restaurant_name": extracted_data.get("restaurant_name"),
        "customer_company": extracted_data.get("customer_company"),
        "restaurant_address": extracted_data.get("restaurant_address"),
        "business_id": extracted_data.get("business_id"),
        "customer_vat": extracted_data.get("customer_vat"),
        "tax_number": extracted_data.get("tax_number"),
        "total_orders": extracted_data.get("total_orders") or 0,
        "total_order_value": extracted_data.get("total_order_value") or 0,
        "gross_revenue_after_discounts": extracted_data.get("gross_revenue_after_discounts") or 0,
        "commission_own_delivery": extracted_data.get("commission_own_delivery") or 0,
        "commission_pickup": extracted_data.get("commission_pickup") or 0,
        "uber_eats_fee": extracted_data.get("uber_eats_fee") or 0,
        "vat_19_percent": extracted_data.get("vat_19_percent") or 0,
        "cash_collected": extracted_data.get("cash_collected") or 0,
        "total_payout": extracted_data.get("total_payout") or 0,
        "net_amount": extracted_data.get("net_amount") or 0,
        "vat_amount": extracted_data.get("vat_amount") or 0,
        "total_amount": extracted_data.get("total_amount") or 0,
        "email_subject": communication_doc.subject,
        "email_from": communication_doc.sender,
        "received_date": communication_doc.creation,
        "processed_date": frappe.utils.now(),
        "extraction_confidence": extracted_data.get("confidence", DEFAULT_EXTRACTION_CONFIDENCE),
        "raw_text": extracted_data.get("raw_text", "")
    })
    
    # name (ID) field'ını invoice_number (Rechnungsnummer) ile aynı yap
    invoice.name = invoice_number or generate_temp_invoice_number()
    
    invoice.insert(ignore_permissions=True, ignore_mandatory=True)
    attach_pdf_to_invoice(pdf_attachment, invoice.name, DOCTYPE_UBER_EATS_INVOICE)
    notify_invoice_created(DOCTYPE_UBER_EATS_INVOICE, invoice.name, invoice.invoice_number, communication_doc.subject)
    
    return invoice


def parse_decimal(value: str | None):
    """String değeri decimal'e çevir"""
    if value is None:
        return None
    clean = value.strip()
    if not clean:
        return None
    clean = clean.replace("€", "").replace("%", "").replace("−", "-").replace(" ", "")
    
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    else:
        clean = clean.replace(",", ".")
    
    try:
        return float(clean)
    except ValueError:
        return None


def attach_pdf_to_invoice(pdf_attachment, invoice_name, target_doctype, target_field=FIELD_PDF_FILE):
    """PDF'i Invoice kaydına attach et"""
    try:
        file_doc = frappe.get_doc("File", pdf_attachment.name)
        file_content = file_doc.get_content()
        
        new_file = frappe.get_doc({
            "doctype": "File",
            "file_name": file_doc.file_name,
            "attached_to_doctype": target_doctype,
            "attached_to_name": invoice_name,
            "attached_to_field": target_field,
            "is_private": 0,
            "content": file_content,
            "folder": "Home/Attachments"
        })
        new_file.flags.ignore_permissions = True
        new_file.insert()
        
        frappe.db.set_value(target_doctype, invoice_name, target_field, new_file.file_url)
        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error(
            title="PDF Attachment Error",
            message=f"Error: {str(e)}\n{frappe.get_traceback()}"
        )


def generate_temp_invoice_number():
    """Geçici fatura numarası oluştur"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"TEMP-{timestamp}"


def parse_date(date_str):
    """Çeşitli tarih formatlarını parse et"""
    formats = [
        "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%m/%d/%Y", "%d.%m.%y", "%d/%m/%y",
    ]
    
    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str.strip(), fmt)
            return parsed_date.strftime("%Y-%m-%d")
        except:
            continue
    
    return frappe.utils.today()


def notify_invoice_created(doctype, docname, invoice_number, email_subject):
    """Fatura oluşturulduğunda kullanıcıya bildirim göster"""
    try:
        from frappe.utils.data import get_url_to_form
        
        invoice_link = get_url_to_form(doctype, docname)
        platform_name = "Lieferando" if "Lieferando" in doctype else "Wolt"
        
        message = f"""
        <b>{platform_name} Faturası Oluşturuldu</b><br><br>
        Fatura No: <b>{invoice_number or 'N/A'}</b><br>
        Email: {email_subject[:50]}{'...' if len(email_subject) > 50 else ''}<br><br>
        <a href='{invoice_link}'><b>Faturayı Görüntüle</b></a>
        """
        
        frappe.publish_realtime(
            "msgprint",
            {
                "message": message,
                "alert": True,
                "indicator": "green",
                "title": f"{platform_name} Faturası Oluşturuldu"
            },
            after_commit=True
        )
        
    except Exception as e:
        logger.error(f"Bildirim gönderme hatası: {str(e)}")


def _get_active_system_users():
    """Get list of active system users"""
    active_users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": USER_TYPE_SYSTEM},
        fields=["name"]
    )
    return [user.name for user in active_users]


def _get_session_stats():
    """Session bazlı istatistikleri al"""
    session_key = "invoice_processing_stats"
    if not hasattr(frappe.local, session_key):
        setattr(frappe.local, session_key, {
            "total_detected": 0,
            "already_processed": 0,
            "newly_processed": 0,
            "errors": 0,
            "invoices_created": [],
            "emails_processed": []
        })
    return getattr(frappe.local, session_key)


def _update_session_stats(stats):
    """Session istatistiklerini güncelle"""
    session_stats = _get_session_stats()
    session_stats["total_detected"] += stats.get("total_detected", 0)
    session_stats["already_processed"] += stats.get("already_processed", 0)
    session_stats["newly_processed"] += stats.get("newly_processed", 0)
    session_stats["errors"] += stats.get("errors", 0)
    session_stats["invoices_created"].extend(stats.get("invoices_created", []))
    if stats.get("total_detected", 0) > 0 or stats.get("already_processed", 0) > 0:
        session_stats["emails_processed"].append(stats)


def show_summary_notification(stats, email_subject, is_final=False):
    """Email işleme özetini göster - hem realtime hem de Notification Log olarak"""
    try:
        from frappe.utils.data import get_url_to_form
        from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
        
        
        try:
            _update_session_stats(stats)
        except Exception as e:
            logger.warning(f"Session stats hatası: {str(e)}")
        
        total_detected = stats.get("total_detected", 0)
        already_processed = stats.get("already_processed", 0)
        newly_processed = stats.get("newly_processed", 0)
        errors = stats.get("errors", 0)
        invoices_created = stats.get("invoices_created", [])
        
        logger.info(f"Bildirim gönderiliyor. Stats: total={total_detected}, new={newly_processed}, already={already_processed}, errors={errors}")
        
        if total_detected == 0 and already_processed == 0:
            logger.info("Bildirim gönderilmedi - istatistik yok")
            return
        
        message_parts = []
        message_parts.append(f"📧 <b>Email İşleme Özeti</b><br>")
        message_parts.append(f"<b>Email:</b> {email_subject[:60]}{'...' if len(email_subject) > 60 else ''}<br><br>")
        
        if total_detected > 0:
            message_parts.append(f"✅ <b>Yakalanan Fatura:</b> {total_detected}<br>")
        
        if already_processed > 0:
            message_parts.append(f"⚠️ <b>Daha Önce İşlenmiş:</b> {already_processed}<br>")
        
        if newly_processed > 0:
            message_parts.append(f"🆕 <b>Yeni İşlenen:</b> {newly_processed}<br>")
        
        if errors > 0:
            message_parts.append(f"❌ <b>Hata:</b> {errors}<br>")
        
        if invoices_created:
            message_parts.append(f"<br><b>Oluşturulan Faturalar:</b><br>")
            for inv in invoices_created[:5]:
                platform = "Lieferando" if "Lieferando" in inv["doctype"] else "Wolt"
                invoice_link = get_url_to_form(inv["doctype"], inv["name"])
                message_parts.append(f"• <a href='{invoice_link}'>{platform} - {inv['invoice_number']}</a><br>")
            
            if len(invoices_created) > 5:
                message_parts.append(f"... ve {len(invoices_created) - 5} fatura daha<br>")
        
        message = "".join(message_parts)
        
        if errors > 0:
            indicator = "red"
        elif already_processed > 0 and newly_processed == 0:
            indicator = "orange"
        else:
            indicator = "green"
        
        # Realtime bildirim (anlık popup) - her zaman gönder
        try:
            # Tüm aktif kullanıcılara bildirim gönder
            user_list = _get_active_system_users()
            
            if not user_list:
                logger.warning("Aktif kullanıcı bulunamadı")
            else:
                
                # Her kullanıcıya bildirim gönder
                for user in user_list:
                    try:
                        frappe.publish_realtime(
                            "show_alert",
                            {
                                "message": message,
                                "alert": True,
                                "indicator": indicator,
                                "title": "Fatura İşleme Özeti"
                            },
                            user=user,
                            after_commit=True
                        )
                    except Exception as e:
                        logger.error(f"Kullanıcı {user} için bildirim hatası: {str(e)}")
                
                logger.info(f"Realtime bildirim gönderildi - {len(user_list)} kullanıcıya")
        except Exception as e:
            logger.error(f"Realtime bildirim hatası: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
        # Notification Log kaydı oluştur (kalıcı bildirim)
        try:
            subject_text = f"Fatura İşleme: {newly_processed} yeni, {already_processed} tekrar"
            if errors > 0:
                subject_text += f", {errors} hata"
            
            notification_doc = {
                "type": "Alert",
                "document_type": "Communication",
                "subject": subject_text,
                "email_content": message,
            }
            
            user_emails = _get_active_system_users()
            
            if user_emails:
                enqueue_create_notification(user_emails, notification_doc)
                logger.info(f"Notification Log gönderildi - {len(user_emails)} kullanıcıya")
            else:
                logger.warning("Notification Log gönderilmedi - aktif kullanıcı bulunamadı")
        except Exception as e:
            logger.error(f"Notification Log gönderme hatası: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
        # Final özet için toplu bildirim gönder
        if is_final:
            session_stats = _get_session_stats()
            _send_final_summary(session_stats)
            if hasattr(frappe.local, "invoice_processing_stats"):
                delattr(frappe.local, "invoice_processing_stats")
        
    except Exception as e:
        logger.error(f"Özet bildirimi gönderme hatası: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def _send_final_summary(session_stats):
    """Tüm email'ler işlendikten sonra toplu özet gönder"""
    try:
        from frappe.utils.data import get_url_to_form
        from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
        
        total_detected = session_stats.get("total_detected", 0)
        already_processed = session_stats.get("already_processed", 0)
        newly_processed = session_stats.get("newly_processed", 0)
        errors = session_stats.get("errors", 0)
        all_invoices = session_stats.get("invoices_created", [])
        emails_count = len(session_stats.get("emails_processed", []))
        
        if total_detected == 0 and already_processed == 0:
            return
        
        message_parts = []
        message_parts.append(f"<b>📧 Toplu Email İşleme Özeti</b><br><br>")
        message_parts.append(f"<b>İşlenen Email Sayısı:</b> {emails_count}<br><br>")
        message_parts.append(f"✅ <b>Toplam Yakalanan Fatura:</b> {total_detected}<br>")
        message_parts.append(f"🆕 <b>Yeni İşlenen:</b> {newly_processed}<br>")
        message_parts.append(f"⚠️ <b>Daha Önce İşlenmiş:</b> {already_processed}<br>")
        
        if errors > 0:
            message_parts.append(f"❌ <b>Hata:</b> {errors}<br>")
        
        if all_invoices:
            message_parts.append(f"<br><b>Oluşturulan Faturalar ({len(all_invoices)}):</b><br>")
            for inv in all_invoices[:10]:
                platform = "Lieferando" if "Lieferando" in inv["doctype"] else "Wolt"
                invoice_link = get_url_to_form(inv["doctype"], inv["name"])
                message_parts.append(f"• <a href='{invoice_link}'>{platform} - {inv['invoice_number']}</a><br>")
            
            if len(all_invoices) > 10:
                message_parts.append(f"... ve {len(all_invoices) - 10} fatura daha<br>")
        
        message = "".join(message_parts)
        
        if errors > 0:
            indicator = "red"
        elif already_processed > 0 and newly_processed == 0:
            indicator = "orange"
        else:
            indicator = "green"
        
        # Toplu özet bildirimi
        frappe.publish_realtime(
            "msgprint",
            {
                "message": message,
                "alert": True,
                "indicator": indicator,
                "title": "Fatura İşleme - Toplu Özet"
            },
            after_commit=True
        )
        
        subject_text = f"Fatura İşleme Özeti: {emails_count} email, {newly_processed} yeni fatura"
        if errors > 0:
            subject_text += f", {errors} hata"
        
        notification_doc = {
            "type": "Alert",
            "document_type": "Communication",
            "subject": subject_text,
            "email_content": message,
        }
        
        user_emails = _get_active_system_users()
        
        if user_emails:
            enqueue_create_notification(user_emails, notification_doc)
        
    except Exception as e:
        logger.error(f"Toplu özet bildirimi gönderme hatası: {str(e)}")


@frappe.whitelist()
def generate_and_attach_analysis_pdf(analysis_name):
    """
    Lieferando Invoice Analysis için print format'a göre PDF oluştur ve attach et
    "Yazdır ve PDF olarak kaydet" butonu ile aynı süreci kullanır
    
    Args:
        analysis_name: Lieferando Invoice Analysis doküman adı
        
    Returns:
        dict: {"success": bool, "message": str, "file_name": str}
    """
    try:
        from invoice.api.constants import DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS
        from frappe.utils.print_format import validate_print_permission
        from frappe.translate import print_language
        
        # Analysis dokümanını kontrol et
        if not frappe.db.exists(DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS, analysis_name):
            frappe.throw(_("Lieferando Invoice Analysis bulunamadı: {0}").format(analysis_name))

        analysis_doc = frappe.get_doc(DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS, analysis_name)
        # Özel, wkhtmltopdf-dostu HTML/CSS kullanan print format
        # (tablolar ve basit stillerle Lieferando PDF'ine yakın çıktı verir)
        print_format = "Lieferando Invoice Analysis Format 2"

        # Print permission kontrolü (download_pdf endpoint'i ile aynı)
        validate_print_permission(analysis_doc)

        # PDF oluştur - download_pdf endpoint'i ile AYNI süreç
        # download_pdf endpoint'i: frappe.utils.print_format.download_pdf
        # Bu endpoint frappe.get_print kullanır; pdf_generator parametresi
        # geçirilmediği için Frappe varsayılan wkhtmltopdf motorunu kullanır.
        with print_language(None):
            pdf_data = frappe.get_print(
                doctype=DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS,
                name=analysis_name,
                print_format=print_format,
                doc=analysis_doc,
                as_pdf=True,
                no_letterhead=1,
            )
        
        # Dosya adı oluştur (download_pdf ile aynı format)
        file_name = "{name}.pdf".format(name=analysis_name.replace(" ", "-").replace("/", "-"))
        
        # Eski PDF dosyasını kontrol et ve sil (varsa)
        old_files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS,
                "attached_to_name": analysis_name,
                "file_name": file_name
            },
            fields=["name"]
        )
        for old_file in old_files:
            try:
                frappe.delete_doc("File", old_file.name, ignore_permissions=True)
            except Exception:
                pass
        
        # File dokümanı oluştur ve attach et
        file_doc = frappe.new_doc("File")
        file_doc.file_name = file_name
        file_doc.content = pdf_data
        file_doc.attached_to_doctype = DOCTYPE_LIEFERANDO_INVOICE_ANALYSIS
        file_doc.attached_to_name = analysis_name
        file_doc.is_private = 0
        file_doc.flags.ignore_permissions = True
        file_doc.insert()
        frappe.db.commit()
        
        return {
            "success": True,
            "message": _("PDF başarıyla oluşturuldu ve eklendi"),
            "file_name": file_name,
            "file_url": file_doc.file_url
        }
        
    except Exception as e:
        frappe.log_error(
            title="PDF Oluşturma Hatası",
            message=f"Analysis: {analysis_name}\nError: {str(e)}\n{frappe.get_traceback()}"
        )
        return {
            "success": False,
            "message": _("PDF oluşturulurken hata oluştu: {0}").format(str(e))
        }
