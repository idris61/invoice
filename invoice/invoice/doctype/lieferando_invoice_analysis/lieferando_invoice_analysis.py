# Copyright (c) 2025, invoice and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt
from invoice.api.constants import (
	SERVICE_FEE_OWN_DELIVERY,
	SERVICE_FEE_DELIVERY,
	DEFAULT_CULINARY_ACCOUNT_FEE
)


class LieferandoInvoiceAnalysis(Document):
	def before_insert(self):
		"""Validate required fields before insert"""
		if not self.lieferando_invoice:
			frappe.throw(
				"Lieferando Faturası alanı zorunludur. Lütfen bir Lieferando Faturası seçin.",
				title="Eksik Alanlar"
			)
	
	def before_save(self):
		"""Validate required fields before save"""
		if not self.lieferando_invoice:
			frappe.throw(
				"Lieferando Faturası alanı zorunludur. Lütfen bir Lieferando Faturası seçin.",
				title="Eksik Alanlar"
			)
	
	def validate(self):
		"""Load data from Lieferando Invoice and calculate all amounts"""
		# Validate that lieferando_invoice is selected
		if not self.lieferando_invoice:
			frappe.throw(
				"Lieferando Faturası alanı zorunludur. Lütfen bir Lieferando Faturası seçin.",
				title="Eksik Alanlar"
			)
		
		self.load_from_invoice()
		self.validate_data()
		self.calculate_all_amounts()
	
	def before_print(self, print_settings=None):
		"""Parse invoice_data_json for print format use"""
		invoice_data_json = getattr(self, 'invoice_data_json', None)
		if invoice_data_json:
			try:
				self.invoice_data = frappe.parse_json(invoice_data_json)
			except Exception as e:
				frappe.log_error(
					title="Invoice Data JSON Parse Error",
					message=f"Error parsing invoice_data_json: {str(e)}"
				)
				self.invoice_data = {}
		else:
			self.invoice_data = {}
	
	def load_from_invoice(self):
		"""Load data from linked Lieferando Invoice"""
		if not self.lieferando_invoice:
			frappe.throw(
				"Lieferando Invoice not selected. Please select a Lieferando Invoice.",
				title="Missing Information"
			)
		
		if not frappe.db.exists("Lieferando Invoice", self.lieferando_invoice):
			frappe.throw(
				f"Lieferando Invoice '{self.lieferando_invoice}' not found.",
				title="Invoice Not Found"
			)
		
		try:
			invoice = frappe.get_doc("Lieferando Invoice", self.lieferando_invoice)
		except frappe.DoesNotExistError:
			frappe.throw(
				f"Lieferando Invoice '{self.lieferando_invoice}' not found in database.",
				title="Invoice Access Error"
			)
		except Exception as e:
			frappe.log_error(
				title="Lieferando Invoice Load Error",
				message=f"Error loading invoice: {self.lieferando_invoice}\nError: {str(e)}"
			)
			frappe.throw(
				f"Error loading Lieferando Invoice: {str(e)}",
				title="Invoice Load Error"
			)
		
		try:
			self.restaurant_name = invoice.restaurant_name or ""
			self.customer_number = invoice.customer_number or ""
			self.customer_tax_number = getattr(invoice, 'customer_tax_number', None) or ""
			self.invoice_number = invoice.invoice_number or ""
			self.period_start = invoice.period_start
			self.period_end = invoice.period_end
		except AttributeError as e:
			frappe.log_error(
				title="General Information Load Error",
				message=f"Error loading general information: {str(e)}"
			)
			frappe.throw(
				f"Error loading general information: {str(e)}",
				title="Data Load Error"
			)
		
		try:
			self.total_revenue = flt(invoice.total_revenue) or 0
			self.total_orders = invoice.total_orders or 0
			self.online_paid_amount = flt(invoice.online_paid_amount) or 0
			# Load online_paid_orders from invoice
			# invoice.online_paid_orders should contain the value extracted from PDF
			self.online_paid_orders = invoice.online_paid_orders or 0
		except (AttributeError, ValueError) as e:
			frappe.log_error(
				title="Revenue and Orders Load Error",
				message=f"Error loading revenue/orders: {str(e)}"
			)
			frappe.throw(
				f"Error loading revenue and orders: {str(e)}",
				title="Data Load Error"
			)
		
		try:
			self.chargeback_orders = getattr(invoice, 'chargeback_orders', None) or 0
			self.chargeback_amount = flt(getattr(invoice, 'chargeback_amount', None)) or 0
		except (AttributeError, ValueError) as e:
			frappe.log_error(
				title="Chargeback Load Error",
				message=f"Error loading chargeback: {str(e)}"
			)
			self.chargeback_orders = 0
			self.chargeback_amount = 0
		
		self.net_revenue = flt(self.total_revenue) - flt(self.chargeback_amount)
		
		try:
			self.cash_paid_amount = flt(getattr(invoice, 'cash_paid_amount', None)) or 0
			self.cash_paid_orders = getattr(invoice, 'cash_paid_orders', None) or 0
			self.cash_service_fee_amount = flt(getattr(invoice, 'cash_service_fee_amount', None)) or 0
		except (AttributeError, ValueError) as e:
			frappe.log_error(
				title="Cash Payment Load Error",
				message=f"Error loading cash payment: {str(e)}"
			)
			self.cash_paid_amount = 0
			self.cash_paid_orders = 0
			self.cash_service_fee_amount = 0
		
		try:
			self.tips_amount = flt(getattr(invoice, 'tips_amount', None)) or 0
		except (AttributeError, ValueError) as e:
			frappe.logger().warning(f"Error loading tips: {str(e)}")
			self.tips_amount = 0
		
		try:
			self.stamp_card_amount = flt(getattr(invoice, 'stamp_card_amount', None)) or 0
		except (AttributeError, ValueError) as e:
			frappe.logger().warning(f"Error loading stamp card amount: {str(e)}")
			self.stamp_card_amount = 0
		
		try:
			# Always get from original invoice (PDF extracted value)
			# This is a cumulative balance, not just this period's online payments + tips
			self.pending_online_payments_g = flt(getattr(invoice, 'ausstehende_onlinebezahlungen_betrag', None)) or 0
		except (AttributeError, ValueError) as e:
			frappe.log_error(
				title="Pending Payments Load Error",
				message=f"Error loading pending payments: {str(e)}"
			)
			frappe.throw(
				"Pending online payments (G) could not be loaded.",
				title="Pending Payments Error"
			)
		
		current_rate = flt(self.service_fee_rate) or 0
		invoice_rate = flt(invoice.service_fee_rate) or 0
		
		if not current_rate and invoice_rate:
			self.service_fee_rate = invoice_rate
		elif current_rate:
			frappe.logger().info(
				f"Service fee rate preserved: {current_rate}% "
				f"(Invoice value: {invoice_rate}%)"
			)
		
		# Store complete invoice data as JSON for print format use
		try:
			invoice_dict = invoice.as_dict(convert_dates_to_str=True)
			self.invoice_data_json = frappe.as_json(invoice_dict, indent=2)
		except Exception as e:
			frappe.log_error(
				title="Invoice JSON Export Error",
				message=f"Error converting invoice to JSON: {str(e)}"
			)
			# Non-critical error, continue without JSON data
			self.invoice_data_json = ""
	
	def validate_data(self):
		"""Validate loaded data for negative values and logical consistency"""
		errors = []
		warnings = []
		
		if flt(self.total_revenue) < 0:
			errors.append(f"Total Revenue cannot be negative: {self.total_revenue}")
		
		if flt(self.online_paid_amount) < 0:
			errors.append(f"Online Paid Amount cannot be negative: {self.online_paid_amount}")
		
		if flt(self.cash_paid_amount) < 0:
			errors.append(f"Cash Paid Amount cannot be negative: {self.cash_paid_amount}")
		
		if flt(self.pending_online_payments_g) < 0:
			errors.append(f"Pending Online Payments (G) cannot be negative: {self.pending_online_payments_g}")
		
		if flt(self.tips_amount) < 0:
			errors.append(f"Tips amount cannot be negative: {self.tips_amount}")
		
		if flt(self.chargeback_amount) < 0:
			errors.append(f"Chargeback Amount cannot be negative: {self.chargeback_amount}")
		
		if (self.chargeback_orders or 0) < 0:
			errors.append(f"Chargeback Orders cannot be negative: {self.chargeback_orders}")
		
		net_revenue = flt(self.total_revenue) - flt(self.chargeback_amount)
		if net_revenue < 0:
			warnings.append(
				f"Net Revenue ({net_revenue}) is negative. "
				f"Chargeback Amount ({self.chargeback_amount}) is greater than Total Revenue ({self.total_revenue})."
			)
		
		if (self.total_orders or 0) < 0:
			errors.append(f"Total Orders cannot be negative: {self.total_orders}")
		
		if (self.online_paid_orders or 0) < 0:
			errors.append(f"Online Paid Orders cannot be negative: {self.online_paid_orders}")
		
		if (self.cash_paid_orders or 0) < 0:
			errors.append(f"Cash Paid Orders cannot be negative: {self.cash_paid_orders}")
		
		if not flt(self.service_fee_rate) and self.lieferando_invoice:
			try:
				invoice = frappe.get_doc("Lieferando Invoice", self.lieferando_invoice)
				if not flt(invoice.service_fee_rate):
					errors.append("Service Fee Rate (service_fee_rate) not specified. Please enter manually.")
			except:
				errors.append("Service Fee Rate (service_fee_rate) not specified and could not be loaded from invoice. Please enter manually.")
		
		if flt(self.service_fee_rate) < 0:
			errors.append(f"Service Fee Rate cannot be negative: {self.service_fee_rate}%")
		
		if flt(self.service_fee_rate) > 100:
			errors.append(f"Service Fee Rate cannot be greater than 100%: {self.service_fee_rate}%")
		
		if flt(self.online_paid_amount) > flt(self.total_revenue):
			warnings.append(
				f"Online Paid Amount ({self.online_paid_amount}) is greater than Total Revenue ({self.total_revenue})."
			)
		
		if (self.online_paid_orders or 0) > (self.total_orders or 0):
			warnings.append(
				f"Online Paid Orders ({self.online_paid_orders}) is greater than Total Orders ({self.total_orders})."
			)
		
		if flt(self.cash_paid_amount) > 0 and (self.cash_paid_orders or 0) == 0:
			warnings.append(
				f"Cash Paid Amount ({self.cash_paid_amount}) exists but order count is 0."
			)
		
		if flt(self.total_revenue) == 0 and (self.total_orders or 0) > 0:
			warnings.append(
				f"Total Revenue is 0 but order count is {self.total_orders}."
			)
		
		if warnings:
			for warning in warnings:
				frappe.logger().warning(
					f"Lieferando Invoice Analysis Validation Warning ({self.name or 'New'}): {warning}"
				)
		
		if errors:
			error_message = "Data validation errors:\n" + "\n".join(f"• {error}" for error in errors)
			frappe.log_error(
				title="Lieferando Invoice Analysis Validation Error",
				message=f"Invoice: {self.lieferando_invoice}\n{error_message}"
			)
			frappe.throw(error_message, title="Data Validation Error")
	
	def calculate_all_amounts(self):
		"""Calculate all amounts for commission and payments"""
		if not self.lieferando_invoice:
			# This should not happen as validate() checks this, but add safety check
			frappe.throw(
				"Lieferando Faturası seçilmediği için hesaplamalar yapılamıyor.",
				title="Eksik Alanlar"
			)
		
		try:
			invoice = frappe.get_doc("Lieferando Invoice", self.lieferando_invoice)
		except Exception as e:
			frappe.log_error(
				title="Calculation: Invoice Load Error",
				message=f"Error loading invoice: {str(e)}"
			)
			raise
		
		total_revenue = flt(self.total_revenue) or 0
		net_revenue = flt(self.net_revenue) or 0
		online_orders_count = flt(self.online_paid_orders) or 0
		chargeback_orders_count = flt(self.chargeback_orders) or 0
		cash_paid_amount = flt(self.cash_paid_amount) or 0
		pending_payments = flt(self.pending_online_payments_g) or 0
		
		# admin_fee_rate should be extracted from PDF and stored in invoice
		# If not available, log warning but continue with 0 (will result in management_fee = 0)
		admin_fee_rate = flt(invoice.admin_fee_rate)
		if not admin_fee_rate or admin_fee_rate <= 0:
			frappe.logger().warning(
				f"Admin Fee Rate (admin_fee_rate) is missing or invalid in Lieferando Invoice '{invoice.name}'. "
				f"Management fee will be calculated as 0. Please ensure the PDF is properly parsed."
			)
			admin_fee_rate = 0
		# tax_rate should be extracted from PDF and stored in invoice
		# If not available, log warning but continue with default 19%
		tax_rate = flt(invoice.tax_rate)
		if not tax_rate or tax_rate <= 0:
			frappe.logger().warning(
				f"Tax Rate (tax_rate) is missing or invalid in Lieferando Invoice '{invoice.name}'. "
				f"Using default 19%. Please ensure the PDF is properly parsed."
			)
			tax_rate = 19.0
		lieferando_service_fee_rate = flt(self.service_fee_rate) or flt(invoice.service_fee_rate) or 0
		
		# Reference commission rate logic (from constants)
		# Always set a reference rate, even if lieferando_service_fee_rate is 0 or None
		if not lieferando_service_fee_rate or lieferando_service_fee_rate <= SERVICE_FEE_OWN_DELIVERY:
			reference_service_fee_rate = SERVICE_FEE_OWN_DELIVERY
		elif lieferando_service_fee_rate <= SERVICE_FEE_DELIVERY:
			reference_service_fee_rate = SERVICE_FEE_DELIVERY
		else:
			frappe.log_error(
				title="Unexpected Commission Rate",
				message=f"Commission rate greater than {SERVICE_FEE_DELIVERY}%: {lieferando_service_fee_rate}%"
			)
			reference_service_fee_rate = SERVICE_FEE_DELIVERY
		
		# Lieferando Commission Calculation
		service_fee_amount = total_revenue * (lieferando_service_fee_rate / 100) if lieferando_service_fee_rate else 0
		# Management fee: exclude chargeback orders (iade edilen siparişler)
		effective_online_orders = max(0, online_orders_count - chargeback_orders_count)
		management_fee_amount = effective_online_orders * admin_fee_rate
		# Use cash_service_fee_amount from invoice if available
		# This should be extracted from PDF, not calculated
		cash_service_fee_from_invoice = flt(getattr(invoice, 'cash_service_fee_amount', None)) or 0
		if cash_service_fee_from_invoice > 0:
			additional_service_fee_amount = cash_service_fee_from_invoice
		else:
			# If cash_service_fee_amount is not available and cash_paid_amount > 0, 
			# log warning but continue with 0
			if cash_paid_amount > 0:
				frappe.logger().warning(
					f"Cash Service Fee Amount (cash_service_fee_amount) is missing in Lieferando Invoice '{invoice.name}' "
					f"but cash_paid_amount is {cash_paid_amount}. "
					f"Additional service fee will be 0. Please ensure the PDF is properly parsed."
				)
			additional_service_fee_amount = 0
		
		# Culinary Account Fee (editable, default from constants)
		# Preserve user's input (including 0), only use default if field is empty/None
		if self.culinary_account_fee is not None and self.culinary_account_fee != '':
			culinary_account_fee = flt(self.culinary_account_fee)
		else:
			culinary_account_fee = DEFAULT_CULINARY_ACCOUNT_FEE
		
		subtotal_c = service_fee_amount + management_fee_amount + additional_service_fee_amount
		vat_amount_d = subtotal_c * (tax_rate / 100)
		total_invoice_amount_e = subtotal_c + vat_amount_d
		
		# Reference calculations (for restaurant payment baseline)
		# Include culinary_account_fee in reference_subtotal so it's part of Zwischensumme
		reference_service_fee = total_revenue * (reference_service_fee_rate / 100) if reference_service_fee_rate else 0
		reference_subtotal = reference_service_fee + management_fee_amount + additional_service_fee_amount + culinary_account_fee
		reference_vat = reference_subtotal * (tax_rate / 100)
		reference_total_invoice = reference_subtotal + reference_vat
		
		# Culinary Commission Calculation
		culinary_service_fee_rate = reference_service_fee_rate - lieferando_service_fee_rate
		if culinary_service_fee_rate < 0:
			culinary_service_fee_rate = 0
		
		culinary_service_fee_amount = total_revenue * (culinary_service_fee_rate / 100) if culinary_service_fee_rate > 0 else 0
		culinary_service_fee_vat = culinary_service_fee_amount * (tax_rate / 100) if culinary_service_fee_amount > 0 else 0
		culinary_total_commission = culinary_service_fee_amount + culinary_service_fee_vat
		
		# Culinary Commission Profit = Total Commission + Account Fee
		culinary_commission_profit = culinary_total_commission + culinary_account_fee
		
		# Payment to Restaurant = Pending Online Payments - Total Invoice Amount - Culinary Commission (Profit)
		payment_to_restaurant_h = pending_payments - total_invoice_amount_e - culinary_commission_profit
		
		if payment_to_restaurant_h < 0:
			frappe.logger().warning(
				f"Payment to Restaurant is negative: {payment_to_restaurant_h}. "
				f"G: {pending_payments}, E: {total_invoice_amount_e}, Culinary: {culinary_commission_profit}"
			)
		
		# Set calculated fields
		self.service_fee_amount = flt(service_fee_amount, 2)
		self.management_fee = flt(management_fee_amount, 2)
		self.additional_service_fee = flt(additional_service_fee_amount, 2)
		self.subtotal_c = flt(subtotal_c, 2)
		self.vat_amount_d = flt(vat_amount_d, 2)
		self.total_invoice_amount_e = flt(total_invoice_amount_e, 2)
		
		# Reference values for print format (default commission rate)
		self.reference_service_fee_rate = flt(reference_service_fee_rate, 2)
		self.reference_service_fee_amount = flt(reference_service_fee, 2)
		self.reference_subtotal = flt(reference_subtotal, 2)
		self.reference_vat_amount = flt(reference_vat, 2)
		self.reference_total_invoice_amount = flt(reference_total_invoice, 2)
		
		self.culinary_service_fee_rate = flt(culinary_service_fee_rate, 2)
		self.culinary_service_fee_amount = flt(culinary_service_fee_amount, 2)
		self.culinary_service_fee_vat = flt(culinary_service_fee_vat, 2)
		self.culinary_total_commission = flt(culinary_total_commission, 2)
		# Only set culinary_account_fee if it was empty/None, otherwise preserve user's input
		if self.culinary_account_fee is None or self.culinary_account_fee == '':
			self.culinary_account_fee = flt(culinary_account_fee, 2)
		else:
			# Keep user's value (even if 0), just ensure it's properly formatted
			self.culinary_account_fee = flt(self.culinary_account_fee, 2)
		self.culinary_commission_profit = flt(culinary_commission_profit, 2)
		
		self.payment_to_restaurant_h = flt(payment_to_restaurant_h, 2)



