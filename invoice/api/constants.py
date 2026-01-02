"""
Invoice API Constants
Magic numbers ve hardcoded değerler burada tanımlanır
"""

# Fee Rates
DEFAULT_ADMIN_FEE_RATE = 0.64
DEFAULT_CULINARY_ACCOUNT_FEE = 0.35
DEFAULT_ADDITIONAL_SERVICE_FEE_RATE = 1.95

# VAT Rates
VAT_RATE_19 = 19
VAT_RATE_7 = 7

# Service Fee Rates
SERVICE_FEE_OWN_DELIVERY = 12
SERVICE_FEE_DELIVERY = 30

# Default Confidence
DEFAULT_EXTRACTION_CONFIDENCE = 60

# Company Names
SUPPLIER_NAME_DEFAULT = "yd.yourdelivery GmbH"
WOLT_ENTERPRISES_NAME = "Wolt Enterprises Deutschland GmbH"
CULINARY_COLLECTIVE_NAME = "CC CULINARY COLLECTIVE GmbH"

# DocType Names
DOCTYPE_LIEFERANDO_INVOICE = "Lieferando Invoice"
DOCTYPE_WOLT_INVOICE = "Wolt Invoice"
DOCTYPE_UBER_EATS_INVOICE = "Uber Eats Invoice"
DOCTYPE_COMMUNICATION = "Communication"
DOCTYPE_FILE = "File"
DOCTYPE_USER = "User"

# Field Names
FIELD_PDF_FILE = "pdf_file"
FIELD_NETTING_REPORT_PDF = "netting_report_pdf"
FIELD_INVOICE_NUMBER = "invoice_number"
FIELD_STATUS_DRAFT = "Draft"

# Platform Names
PLATFORM_LIEFERANDO = "lieferando"
PLATFORM_WOLT = "wolt"
PLATFORM_UBER_EATS = "uber_eats"
PLATFORM_UNKNOWN = "unknown"

PLATFORM_NAME_LIEFERANDO = "Lieferando"
PLATFORM_NAME_WOLT = "Wolt"
PLATFORM_NAME_UBER_EATS = "Uber Eats"

# Email Keywords
EMAIL_KEYWORD_INVOICE = "invoice"
EMAIL_KEYWORD_FATURA = "fatura"
EMAIL_KEYWORD_RECHNUNG = "rechnung"
EMAIL_KEYWORD_FACTURE = "facture"
EMAIL_KEYWORD_BILL = "bill"
EMAIL_KEYWORD_UBER_EATS_REPORT = "ihre neue aktivitätsübersicht"
EMAIL_KEYWORD_WOLT_PAYOUT_REPORT = "wolt payout report"

# Communication Types
COMMUNICATION_TYPE = "Communication"
SENT_OR_RECEIVED_RECEIVED = "Received"

# User Types
USER_TYPE_SYSTEM = "System User"

# Notification Types
NOTIFICATION_TYPE_ALERT = "Alert"
NOTIFICATION_TITLE_INVOICE_PROCESSING = "Fatura İşleme Özeti"
NOTIFICATION_TITLE_BATCH_SUMMARY = "Fatura İşleme - Toplu Özet"

# Realtime Event Types
REALTIME_EVENT_SHOW_ALERT = "show_alert"
REALTIME_EVENT_MSGPRINT = "msgprint"

# Session Keys
SESSION_KEY_INVOICE_STATS = "invoice_processing_stats"

# ============================================================================
# EMAIL TYPE CONSTANTS
# ============================================================================
EMAIL_TYPE_INVOICE = "invoice"
EMAIL_TYPE_UBER_EATS_REPORT = "uber_eats_report"
EMAIL_TYPE_WOLT_PAYOUT_REPORT = "wolt_payout_report"

# ============================================================================
# LOG MESSAGE CONSTANTS
# ============================================================================
LOG_EMAIL_PROCESSING_STARTED = "Email işleme başladı"
LOG_INVOICE_ALREADY_PROCESSED = "Fatura zaten işlenmiş"
LOG_NEW_INVOICE_DETECTED = "Yeni fatura tespit edildi"
LOG_INVOICE_NUMBER_NOT_FOUND = "Invoice number bulunamadı, geçici numara kullanılacak"
LOG_EMAIL_SKIPPED_NOT_INVOICE = "Email atlandı - fatura değil"
LOG_EMAIL_PROCESSING_COMPLETED = "Email işleme tamamlandı"
