# Invoice App - Otomatik Fatura İşleme ve Analiz Sistemi

[![Frappe Framework](https://img.shields.io/badge/Frappe-15.0+-blue.svg)](https://frappeframework.com)
[![Python](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Invoice App**, üç farklı yemek dağıtım platformundan (Lieferando, Wolt, Uber Eats) gelen fatura e-postalarını otomatik olarak işleyen, PDF'lerden veri çıkaran, AI ile doğrulayan ve detaylı analiz yapan bir **Frappe/ERPNext** uygulamasıdır.

---

## 📋 İçindekiler

- [Genel Bakış](#-genel-bakış)
- [Özellikler](#-özellikler)
- [Desteklenen Platformlar](#-desteklenen-platformlar)
- [Kurulum](#-kurulum)
- [Kullanım](#-kullanım)
- [DocType'lar](#-doctypelar)
- [API ve Modüller](#-api-ve-modüller)
- [İş Akışları](#-iş-akışları)
- [Print Format'lar](#-print-formatlar)
- [Teknik Detaylar](#-teknik-detaylar)
- [Katkıda Bulunma](#-katkıda-bulunma)
- [Lisans](#-lisans)

---

## 🎯 Genel Bakış

Invoice App, restoran işletmelerinin yemek dağıtım platformlarından gelen faturaları otomatik olarak işlemesini, analiz etmesini ve yönetmesini sağlar. Sistem şu ana işlevleri yerine getirir:

- ✅ **Otomatik Email İşleme**: Gelen email'lerden PDF'leri tespit eder ve işler
- ✅ **Çoklu Platform Desteği**: Lieferando, Wolt, Uber Eats
- ✅ **PDF Veri Çıkarma**: PyPDF2 ile text extraction ve regex pattern matching
- ✅ **AI Doğrulama**: OpenAI GPT-4o ile fatura doğrulama
- ✅ **Duplicate Kontrolü**: Invoice number bazlı tekrar kontrolü
- ✅ **Scheduled Tasks**: Her 5 dakikada bir email sync
- ✅ **Realtime Bildirimler**: Kullanıcıya anlık bildirimler
- ✅ **Batch İşlemler**: Toplu AI validation
- ✅ **Detaylı Analiz**: Komisyon hesaplamaları ve ödeme analizleri
- ✅ **Print Format'lar**: Profesyonel fatura görüntüleme

---

## ✨ Özellikler

### 1. Otomatik Email İşleme
- Gmail entegrasyonu ile otomatik email senkronizasyonu
- PDF attachment'ları otomatik tespit ve indirme
- Platform bazlı email filtreleme
- Duplicate kontrolü (invoice number bazlı)

### 2. PDF Veri Çıkarma
- PyPDF2 ile text extraction
- Regex pattern matching ile veri çıkarma
- Multi-page PDF desteği
- Confidence scoring sistemi

### 3. AI Doğrulama
- OpenAI GPT-4o entegrasyonu
- PDF içeriği ile veritabanı verilerinin karşılaştırılması
- Tekil ve toplu doğrulama desteği
- Confidence score hesaplama

### 4. Komisyon Hesaplamaları
- Lieferando komisyon hesaplamaları
- Referans komisyon oranları (12% ve 30%)
- Yönetim ücretleri (€0.64 per order)
- Culinary komisyon hesaplamaları
- KDV hesaplamaları (%19)

### 5. Analiz ve Raporlama
- Lieferando Invoice Analysis DocType
- Detaylı komisyon analizleri
- Ödeme hesaplamaları
- Net ciro analizleri
- Bekleyen ödemeler takibi

### 6. Print Format'lar
- Profesyonel fatura görüntüleme
- Dinamik veri gösterimi
- Custom CSS styling
- Multi-page desteği

---

## 🏢 Desteklenen Platformlar

### 1. Lieferando (Takeaway.com / YourDelivery)
- **Tedarikçi**: yd.yourdelivery GmbH
- **Komisyon Oranları**: %12 (kendi teslimat) veya %30 (platform teslimatı)
- **Yönetim Ücreti**: €0.64 per online order
- **KDV**: %19
- **Özellikler**:
  - Sipariş detayları (order_items)
  - Bahşiş takibi (tip_items)
  - Cash payment service fees
  - Chargeback (iade) takibi

### 2. Wolt Enterprises Deutschland GmbH
- **Komisyon Yapısı**: Satılan mallar ve dağıtım ücretleri
- **KDV Oranları**: %7 ve %19
- **Özellikler**:
  - Netting report desteği
  - Detaylı KDV ayrımı
  - Nettopreis hesaplamaları

### 3. Uber Eats Germany GmbH
- **Komisyon Yapısı**: Kendi teslimat ve pickup komisyonları
- **KDV**: %19
- **Özellikler**:
  - Aktivitätsübersicht raporları
  - Nakit toplama takibi
  - Toplam ödeme hesaplamaları

---

## 🚀 Kurulum

### Gereksinimler
- Frappe Framework v15.0+
- Python 3.10+
- Bench CLI
- Gmail API credentials (email sync için)
- OpenAI API key (AI validation için)

### Adım 1: App'i İndirin

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/idris61/invoice.git
bench install-app invoice
```

### Adım 2: Gerekli Ayarları Yapın

#### Gmail API Ayarları
1. Gmail API credentials'ları oluşturun
2. `System Settings` > `Email Account` bölümünde email hesabını yapılandırın

#### OpenAI API Ayarları
1. OpenAI API key'inizi alın
2. Frappe'de `System Settings` > `Invoice Settings` bölümünde API key'i girin

### Adım 3: Scheduler'ı Aktif Edin

```bash
bench schedule restart
```

### Adım 4: Migration'ları Çalıştırın

```bash
bench migrate
```

---

## 📖 Kullanım

### 1. Email İşleme

Sistem otomatik olarak gelen email'leri işler. Manuel işlem için:

1. **Communication** DocType'ına gidin
2. Email'i seçin
3. PDF attachment'ı kontrol edin
4. Sistem otomatik olarak faturayı oluşturur

### 2. AI Doğrulama

#### Tekil Doğrulama
1. Invoice formunu açın
2. "Recheck with AI" butonuna tıklayın
3. Sonuçları kontrol edin

#### Toplu Doğrulama
1. Invoice list view'ına gidin
2. Birden fazla invoice seçin
3. "Batch AI Validation" butonuna tıklayın
4. Toplu sonuçları kontrol edin

### 3. Analiz ve Raporlama

#### Lieferando Invoice Analysis
1. **Lieferando Invoice Analysis** DocType'ını açın
2. Bir **Lieferando Invoice** seçin
3. Sistem otomatik olarak:
   - Komisyon hesaplamalarını yapar
   - Referans komisyon oranlarını uygular
   - Culinary komisyonlarını hesaplar
   - Ödeme tutarlarını hesaplar

### 4. Print Format Görüntüleme

1. Invoice formunu açın
2. "Print" butonuna tıklayın
3. Print format'ı seçin:
   - **Lieferando Invoice Format**: Standart fatura formatı
   - **Lieferando Invoice Analysis Format**: Analiz formatı

---

## 📄 DocType'lar

### 1. Lieferando Invoice
**En kapsamlı DocType** - 500+ satır Python kodu

#### Ana Alanlar
- **Temel Bilgiler**: invoice_number, invoice_date, period_start, period_end
- **Tedarikçi Bilgileri**: supplier_name, supplier_email, supplier_address
- **Müşteri Bilgileri**: customer_company, restaurant_name, restaurant_address
- **Sipariş İstatistikleri**: total_orders, total_revenue, online_paid_orders, cash_paid_orders
- **Ücretler**: service_fee_rate, service_fee_amount, admin_fee_rate, admin_fee_amount
- **Tutarlar**: subtotal, tax_amount, total_amount, outstanding_amount
- **Ödeme Bilgileri**: paid_online_payments, auszahlung_gesamt
- **AI Doğrulama**: ai_validation_status, ai_validation_confidence

#### Child Tables
- **Order Items**: Sipariş detayları (tarih, order_id, tutar, online/cash)
- **Tip Items**: Bahşiş detayları (tarih, tip_id, tutar)

### 2. Wolt Invoice
- Fatura ve dönem bilgileri
- Satılan mallar (7% ve 19% KDV ayrıntıları)
- Dağıtım ücretleri
- Netting report desteği

### 3. Uber Eats Invoice
- Fatura ve vergi tarihleri
- Restoran ve şirket bilgileri
- Sipariş ve gelir detayları
- Komisyonlar ve ücretler

### 4. Lieferando Invoice Analysis
**Analiz ve hesaplama DocType'ı**

#### Ana Özellikler
- Lieferando Invoice'dan veri yükleme
- Komisyon hesaplamaları
- Referans komisyon oranları
- Culinary komisyon hesaplamaları
- Ödeme hesaplamaları

#### Hesaplanan Alanlar
- `reference_service_fee_rate`: Referans komisyon oranı (%12 veya %30)
- `reference_subtotal`: Ara toplam (komisyonlar + ücretler + culinary account fee)
- `reference_vat_amount`: KDV tutarı
- `reference_total_invoice_amount`: Toplam fatura tutarı
- `culinary_service_fee_rate`: Culinary komisyon oranı
- `culinary_total_commission`: Culinary toplam komisyonu
- `payment_to_restaurant_h`: Restorana ödenecek tutar

---

## 🔧 API ve Modüller

### 1. `invoice/api/invoice_email_handler.py`
**Ana email işleme modülü** (~2000 satır)

#### Ana Fonksiyonlar
- `process_invoice_email()`: Email işleme entry point
- `detect_platform()`: Platform tespiti
- `extract_lieferando_data()`: Lieferando PDF extraction
- `extract_wolt_data()`: Wolt PDF extraction
- `extract_uber_eats_data()`: Uber Eats PDF extraction
- `create_invoice()`: Invoice oluşturma

### 2. `invoice/api/invoice_ai_validation.py`
**AI doğrulama modülü** (~250 satır)

#### Ana Fonksiyonlar
- `validate_invoice_with_ai()`: Tekil doğrulama
- `batch_validate_invoices()`: Toplu doğrulama
- `compare_pdf_with_doctype()`: PDF ve DocType karşılaştırma

### 3. `invoice/api/email_tasks.py`
**Scheduled tasks modülü** (~60 satır)

#### Ana Fonksiyonlar
- `sync_gmail_invoices()`: Gmail senkronizasyonu (her 5 dakika)

### 4. `invoice/api/constants.py`
**Sabitler ve konfigürasyon** (~100 satır)

#### Ana Sabitler
- `SERVICE_FEE_OWN_DELIVERY = 12`: Kendi teslimat komisyon oranı
- `SERVICE_FEE_DELIVERY = 30`: Platform teslimat komisyon oranı
- `DEFAULT_ADMIN_FEE_RATE = 0.64`: Varsayılan yönetim ücreti
- `DEFAULT_CULINARY_ACCOUNT_FEE = 0.35`: Varsayılan Culinary hesap ücreti

---

## 🔄 İş Akışları

### 1. Email İşleme Akışı

```
Email Gelişi (Communication)
    ↓
PDF Tespiti
    ↓
Platform Belirleme
    ↓
PDF Veri Çıkarma
    ↓
Duplicate Kontrolü
    ↓
Invoice Oluşturma
    ↓
PDF Attachment
    ↓
Bildirim Gönderme
```

### 2. AI Doğrulama Akışı

```
Invoice Seçimi
    ↓
PDF Text Extraction
    ↓
DocType Verilerini Toplama
    ↓
OpenAI API'ye Gönderme
    ↓
AI Karşılaştırma
    ↓
Sonuçları Kaydetme
    ↓
Form Yenileme
```

### 3. Analiz Hesaplama Akışı

```
Lieferando Invoice Seçimi
    ↓
Veri Yükleme
    ↓
Komisyon Hesaplamaları
    ↓
Referans Komisyon Hesaplama
    ↓
Culinary Komisyon Hesaplama
    ↓
Ödeme Hesaplama
    ↓
Sonuçları Kaydetme
```

---

## 🖨️ Print Format'lar

### 1. Lieferando Invoice Format
**Standart fatura formatı**

#### Sayfalar
1. **Rechnung (Fatura)**: Ana fatura sayfası
2. **Einzelauflistung (Detaylı Liste)**: Sipariş detayları
3. **Trinkgelder (Bahşişler)**: Bahşiş detayları (varsa)

#### Özellikler
- Dinamik veri gösterimi
- Profesyonel tasarım
- Multi-page desteği
- Custom CSS styling

### 2. Lieferando Invoice Analysis Format
**Analiz formatı**

#### Özellikler
- Referans komisyon oranları gösterimi
- Culinary komisyon detayları
- Detaylı hesaplama gösterimi
- Zwischensumme (ara toplam) hesaplamaları
- KDV hesaplamaları

#### Önemli Notlar
- **Culinary Kontogebühr**: Zwischensumme'ye dahil edilir
- **Chargeback'ler**: Online sipariş sayısı ve tutarından düşülür
- **KDV Oranı**: Dinamik olarak gösterilir (varsayılan %19)

---

## 🔍 Teknik Detaylar

### Mimari Yapı

```
apps/invoice/
├── invoice/
│   ├── hooks.py                          # Frappe hooks
│   ├── __init__.py                       # App version
│   ├── modules.txt                       # Modül listesi
│   ├── patches.txt                       # DB migration patches
│   ├── api/
│   │   ├── constants.py                  # Sabitler
│   │   ├── email_tasks.py                # Scheduler tasks
│   │   ├── invoice_ai_validation.py      # AI validation
│   │   └── invoice_email_handler.py      # Ana email handler
│   ├── invoice/
│   │   └── doctype/
│   │       ├── lieferando_invoice/       # Lieferando Invoice
│   │       ├── lieferando_invoice_analysis/  # Analysis DocType
│   │       ├── wolt_invoice/            # Wolt Invoice
│   │       ├── uber_eats_invoice/       # Uber Eats Invoice
│   │       └── [child_tables]/          # Child tables
│   └── config/
│       └── __init__.py
├── pyproject.toml                        # Python dependencies
└── README.md
```

### Hook Yapılandırması

```python
# Document Events
doc_events = {
    "Communication": {
        "after_insert": "invoice.api.invoice_email_handler.process_invoice_email",
        "on_update": "invoice.api.invoice_email_handler.process_invoice_email"
    }
}

# Scheduled Tasks
scheduler_events = {
    "all": [
        "invoice.api.email_tasks.sync_gmail_invoices"
    ]
}
```

### Bağımlılıklar

- `frappe`: Frappe Framework v15.0+
- `PyPDF2`: PDF text extraction
- `openai`: AI validation (opsiyonel)
- `regex`: Pattern matching

### Veritabanı Yapısı

- Her invoice DocType'unun kendi tablosu var
- `invoice_number` field'ı unique ve autoname olarak kullanılıyor
- Tüm invoice'lar submittable (onaylanabilir)
- Child tables ile ilişkisel veri yapısı

---

## 🤝 Katkıda Bulunma

Katkılarınızı bekliyoruz! Lütfen şu adımları izleyin:

1. Fork edin
2. Feature branch oluşturun (`git checkout -b feature/amazing-feature`)
3. Değişikliklerinizi commit edin (`git commit -m 'Add amazing feature'`)
4. Branch'inizi push edin (`git push origin feature/amazing-feature`)
5. Pull Request oluşturun

### Kod Standartları

Bu app `pre-commit` kullanır. Lütfen kurulum yapın:

```bash
cd apps/invoice
pre-commit install
```

Pre-commit şu araçları kullanır:
- **ruff**: Python linting ve formatting
- **eslint**: JavaScript linting
- **prettier**: Code formatting
- **pyupgrade**: Python version upgrades

---

## 📝 Lisans

Bu proje MIT lisansı altında lisanslanmıştır. Detaylar için [LICENSE](LICENSE) dosyasına bakın.

---

## 📧 İletişim

- **Email**: idris.gemici61@gmail.com
- **GitHub**: [@idris61](https://github.com/idris61)

---

## 🙏 Teşekkürler

- Frappe Framework ekibine
- Tüm katkıda bulunanlara
- OpenAI API'ye

---

**Not**: Bu app aktif olarak geliştirilmektedir. Sorun bildirimi ve özellik istekleri için GitHub Issues kullanabilirsiniz.
