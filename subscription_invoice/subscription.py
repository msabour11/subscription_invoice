from erpnext.accounts.doctype.subscription.subscription import Subscription
import frappe
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.data import (
    add_days,
    add_months,
    add_to_date,
    cint,
    date_diff,
    flt,
    get_last_day,
    get_link_to_form,
    getdate,
    nowdate,
)
from datetime import date

from erpnext import get_default_company, get_default_cost_center
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    get_accounting_dimensions,
)
from erpnext.accounts.doctype.subscription_plan.subscription_plan import get_plan_rate
from erpnext.accounts.party import get_party_account_currency
from datetime import datetime

DateTimeLikeObject = str | date


class SubscriptionInvoice(Subscription):

    # @frappe.whitelist()
    # def generate_invoices_to_today(self) -> None:
    #     """
    #     Generates invoices from the beginning of the subscription to today
    #     at monthly intervals if no invoices have been generated for that period.
    #     """
    #     start_date = getdate(self.start_date)
    #     today = getdate(nowdate())
    #     current_date = start_date

    # @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@222 create one each two month

    @frappe.whitelist()
    def generate_invoices_to_today(self) -> None:
        """
        Generates invoices from the beginning of the subscription to today
        at monthly intervals if no invoices have been generated for that period.
        """
        start_date = getdate(self.start_date)
        today = getdate(nowdate())
        current_date = start_date

        while current_date <= today:
            if not self.is_invoice_generated_for_date(current_date):
                self.generate_invoice(
                    from_date=current_date, to_date=add_months(current_date, 1)
                )
            current_date = add_months(current_date, 1)

    def is_invoice_generated_for_date(self, date: DateTimeLikeObject) -> bool:
        """
        Checks if an invoice has been generated for the given date.
        """
        invoices = frappe.get_all(
            self.invoice_document_type,
            filters={
                "subscription": self.name,
                "from_date": ("<=", date),
                "to_date": (">=", date),
            },
            pluck="name",
        )
        return bool(invoices)

    @frappe.whitelist()
    def create_invoice1(
        self,
        from_date: DateTimeLikeObject | None = None,
        to_date: DateTimeLikeObject | None = None,
        posting_date: DateTimeLikeObject | None = None,
    ) -> Document:
        """
        Creates a `Invoice`, submits it and returns it
        """
        # set the start date to the beginning of the subscription
        start_date = getdate(self.start_date)
        # Set the end date to today's date
        end_date = date.today()

        # get all existing invoices for the subscription
        existing_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"subscription": self.name},
            fields=["posting_date"],
        )

        invoices_month = {
            getdate(invoice.posting_date).strftime("%Y-%m")
            for invoice in existing_invoices
        }
        print("posting date is", existing_invoices)

        # Initialize the invoice date to the start date
        invoice_date = start_date

        # Iterate from the start date to today's date with a monthly interval
        while invoice_date < end_date:
            invoice_month = invoice_date.strftime("%Y-%m")
            if invoice_month not in invoices_month:
                to_date = get_last_day(invoice_date)
                # Generate invoice if not already existing
                self._create_single_invoice(invoice_date, to_date)

            # Move to the next month
            invoice_date = add_months(invoice_date, 1)

        # generate the current invoice as per existing logic
        return self._create_single_invoice(from_date, to_date)

    def _create_single_invoice(
        self,
        from_date: DateTimeLikeObject | None = None,
        to_date: DateTimeLikeObject | None = None,
    ) -> Document:
        """
        Helper method to create a single invoice
        """
        company = self.get("company") or get_default_company()
        if not company:
            frappe.throw(
                _(
                    "Company is mandatory for generating an invoice. Please set a default company in Global Defaults."
                )
            )

        invoice = frappe.new_doc(self.invoice_document_type)
        invoice.company = company
        invoice.set_posting_time = 1

        invoice.posting_date = from_date or self.current_invoice_start
        invoice.cost_center = self.cost_center

        if self.invoice_document_type == "Sales Invoice":
            invoice.customer = self.party
        else:
            invoice.supplier = self.party
            if frappe.db.get_value("Supplier", self.party, "tax_withholding_category"):
                invoice.apply_tds = 1

        # Add party currency to invoice
        invoice.currency = get_party_account_currency(
            self.party_type, self.party, self.company
        )

        # Add dimensions in invoice for subscription:
        accounting_dimensions = get_accounting_dimensions()

        for dimension in accounting_dimensions:
            if self.get(dimension):
                invoice.update({dimension: self.get(dimension)})

        # Subscription is better suited for service items. I won't update `update_stock`
        # for that reason
        items_list = self.get_items_from_plans(self.plans, is_prorate())

        for item in items_list:
            item["cost_center"] = self.cost_center
            invoice.append("items", item)

        # Taxes
        tax_template = ""

        if self.invoice_document_type == "Sales Invoice" and self.sales_tax_template:
            tax_template = self.sales_tax_template
        if (
            self.invoice_document_type == "Purchase Invoice"
            and self.purchase_tax_template
        ):
            tax_template = self.purchase_tax_template

        if tax_template:
            invoice.taxes_and_charges = tax_template
            invoice.set_taxes()

        # Due date
        if self.days_until_due:
            invoice.append(
                "payment_schedule",
                {
                    "due_date": add_days(
                        invoice.posting_date, cint(self.days_until_due)
                    ),
                    "invoice_portion": 100,
                },
            )

        # Discounts
        if self.is_trialling():
            invoice.additional_discount_percentage = 100
        else:
            if self.additional_discount_percentage:
                invoice.additional_discount_percentage = (
                    self.additional_discount_percentage
                )

            if self.additional_discount_amount:
                invoice.discount_amount = self.additional_discount_amount

            if self.additional_discount_percentage or self.additional_discount_amount:
                discount_on = self.apply_additional_discount
                invoice.apply_discount_on = (
                    discount_on if discount_on else "Grand Total"
                )

        # Subscription period
        invoice.subscription = self.name
        invoice.from_date = from_date or self.current_invoice_start
        invoice.to_date = to_date or self.current_invoice_end

        invoice.flags.ignore_mandatory = True

        invoice.set_missing_values()
        invoice.save()

        if self.submit_invoice:
            invoice.submit()


# #         return invoice
def is_prorate() -> int:
    return cint(frappe.db.get_single_value("Subscription Settings", "prorate"))
