// Copyright (c) 2025, invoice and contributors
// For license information, please see license.txt

frappe.ui.form.on('Lieferando Invoice Analysis', {
	onload: function(frm) {
		// Add CSS to make field values black and bold
		if (!$('#lieferando-invoice-analysis-custom-css').length) {
			$('<style id="lieferando-invoice-analysis-custom-css">')
				.text(`
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .form-control,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .form-control.read-only,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .frappe-control input,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .frappe-control input[readonly],
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .like-disabled-input,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .control-value,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .static-value,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .frappe-control[data-fieldtype="Currency"] .control-value,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .frappe-control[data-fieldtype="Data"] .control-value,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .frappe-control[data-fieldtype="Int"] .control-value,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .frappe-control[data-fieldtype="Date"] .control-value,
					.form-layout[data-doctype="Lieferando Invoice Analysis"] .frappe-control[data-fieldtype="Percent"] .control-value {
						color: #000000 !important;
						font-weight: 600 !important;
						opacity: 1 !important;
					}
				`)
				.appendTo('head');
		}
		
		// Yeni belge oluşturulduğunda culinary_account_fee default değerini 0.35 olarak ayarla
		// (Eğer 35 gelirse düzelt)
		if (frm.is_new() && (frm.doc.culinary_account_fee == 35 || frm.doc.culinary_account_fee == 35.0)) {
			frm.set_value("culinary_account_fee", 0.35);
		}
	},
	
	// Debounce timer'ları - duplicate save'leri önlemek için
	_save_timer: null,
	
	lieferando_invoice: function(frm) {
		if (frm.doc.lieferando_invoice && !frm.is_new()) {
			// Debounce: önceki timer'ı iptal et
			if (this._save_timer) {
				clearTimeout(this._save_timer);
			}
			// Yeni timer başlat
			this._save_timer = setTimeout(function() {
				frm.save();
			}, 300);
		}
	},
	
	service_fee_rate: function(frm) {
		if (frm.doc.service_fee_rate && frm.doc.lieferando_invoice && !frm.is_new()) {
			// Debounce: önceki timer'ı iptal et
			if (this._save_timer) {
				clearTimeout(this._save_timer);
			}
			// Yeni timer başlat
			this._save_timer = setTimeout(function() {
				frm.save();
			}, 300);
		}
	},
	
	culinary_account_fee: function(frm) {
		if (frm.doc.culinary_account_fee !== undefined && frm.doc.lieferando_invoice && !frm.is_new()) {
			// Debounce: önceki timer'ı iptal et
			if (this._save_timer) {
				clearTimeout(this._save_timer);
			}
			// Yeni timer başlat
			this._save_timer = setTimeout(function() {
				frm.save();
			}, 300);
		}
	}
});



