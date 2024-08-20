import frappe
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
from typing import Dict, List, Optional, Union


class SubscriptionInvoice(Subscription):
    def create_past_missing_invoices(
        self,
        from_date: Optional[Union[str, datetime.date]] = None,
        to_date: Optional[Union[str, datetime.date]] = None,
        posting_date: Optional[Union[str, datetime.date]] = None,
    ) -> Document:

        company = self.get("company") or get_default_company()
        if not company:
            frappe.throw(
                _(
                    "Company is mandatory when generating invoice. Please set default company in Global Defaults."
                )
            )

        invoice = frappe.new_doc(self.invoice_document_type)
        invoice.company = company
        invoice.set_posting_time = 1

        if self.generate_invoice_at == "Beginning of the current subscription period":
            invoice.posting_date = from_date or self.current_invoice_start
        elif self.generate_invoice_at == "Days before the current subscription period":
            invoice.posting_date = posting_date or add_days(
                from_date or self.current_invoice_start, -self.number_of_days
            )
        else:
            invoice.posting_date = to_date or self.current_invoice_end

        invoice.cost_center = self.cost_center

        if self.invoice_document_type == "Sales Invoice":
            invoice.customer = self.party
        else:
            invoice.supplier = self.party
            if frappe.db.get_value("Supplier", self.party, "tax_withholding_category"):
                invoice.apply_tds = 1

        invoice.currency = get_party_account_currency(
            self.party_type, self.party, self.company
        )

        accounting_dimensions = get_accounting_dimensions()
        for dimension in accounting_dimensions:
            if self.get(dimension):
                invoice.update({dimension: self.get(dimension)})

        items_list = self.get_items_from_plans(self.plans, is_prorate())
        for item in items_list:
            item["cost_center"] = self.cost_center
            invoice.append("items", item)

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

        # Adjust the current invoice start and end dates based on the latest invoice
        if from_date and to_date:
            self.current_invoice_start = from_date
            self.current_invoice_end = to_date

        invoice.subscription = self.name
        invoice.from_date = from_date or self.current_invoice_start
        invoice.to_date = to_date or self.current_invoice_end

        invoice.flags.ignore_mandatory = True

        invoice.set_missing_values()
        invoice.save()

        if self.submit_invoice:
            invoice.submit()

        return invoice

    @frappe.whitelist()
    def fetch_past_subscription_invoices(self):
        """fetch and create any missing invoices for the subscription"""
        name1 = "ACC-SUB-2024-00028"

        ## get existing invoices for the subscription
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"subscription": self.name},
            fields=["posting_date"],
        )

        # Create a list of (month, year) for existing invoices
        invoices_month = [getdate(x.posting_date).month for x in invoices]
        invoices_year = [getdate(x.posting_date).year for x in invoices]

        # Initialize start date of subscription and current dates
        start_date = getdate(self.start_date)
        current_date = getdate(nowdate())
        result = 0

        # Loop through each month from the start date to the current date
        while start_date < current_date:
            next_to_date = start_date
            # If  invoice does not exist for a particular month and year, create one
            if not (
                start_date.month in invoices_month and start_date.year in invoices_year
            ):
                result += 1
                # increase current date by month to get invoice to date
                next_to_date = add_to_date(start_date, months=1)
                self.create_past_missing_invoices(
                    from_date=start_date, to_date=next_to_date
                )
                print(f"invoice created from date {start_date} to date {next_to_date}")

            # Move to the next month
            start_date = add_to_date(start_date, months=1)


# @frappe.whitelist(allow_guest=True)
# def is_invoice_exist():
#     start_date = getdate("01-01-2024")
#     current_date = getdate(nowdate())

#     while start_date < current_date:
#         pass

#     return type(current_date)


def is_prorate() -> int:
    return cint(frappe.db.get_single_value("Subscription Settings", "prorate"))
