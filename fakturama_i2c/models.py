"""Data models.

Two layers on purpose:

* ``Raw*``  - what the LLM returns. Every field is a string copied *verbatim* from the OCR
  text, so each one can be grounded (found again in the OCR tokens). The LLM never does
  arithmetic or format conversion.
* typed     - ``OrderExtraction`` and friends, produced by ``extraction.normalize`` from the raw
  model. Money/percent/quantity are ``Decimal``, dates are ``date``. This is what the
  workflow consumes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- raw (LLM output)


class _Raw(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawAddress(_Raw):
    name: str = Field(description="First line of the address block (company / site name), verbatim")
    street: str = Field(description="Street and house number, verbatim")
    zip: str = Field(description="Postal code, verbatim")
    city: str = Field(description="City, verbatim")
    country: str = Field(description="Country, verbatim")


class RawItem(_Raw):
    position: str = Field(description="Row number '#', verbatim")
    sku: str
    description: str
    quantity: str
    unit: str = Field(description="Unit column, e.g. 'pcs'; empty string if absent")
    unit_net: str = Field(description="Unit net price, verbatim (no currency symbol)")
    discount: str = Field(description="Discount column, verbatim incl. '%'")
    vat: str = Field(description="VAT column, verbatim incl. '%'")
    line_net: str = Field(description="Line net total (source total), verbatim")


class RawOrder(_Raw):
    external_reference: str
    order_date: str
    customer_id: str
    currency: str
    company: str
    contact_name: str = Field(description="Full contact name, verbatim")
    customer_alias: str
    email: str
    phone: str
    billing_address: RawAddress
    delivery_address: RawAddress
    payment_method: str
    paid_status: str
    payment_date: str = Field(description="Payment date verbatim, empty string if none")
    items: list[RawItem]
    net_total: str = Field(description="Net total, verbatim; may include currency code")
    vat_total: str
    gross_total: str


# --------------------------------------------------------------------------- typed (domain)


class PaidStatus(str, Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"


class Address(BaseModel):
    name: str
    street: str
    zip: str
    city: str
    country: str

    def same_location(self, other: Address) -> bool:
        """Billing == delivery in the sense of PDF 2.8 (the postal address, not the label)."""
        key = lambda a: (a.street.casefold(), a.zip, a.city.casefold(), a.country.casefold())  # noqa: E731
        return key(self) == key(other)


class Customer(BaseModel):
    company: str
    first_name: str
    last_name: str
    alias: str
    email: str
    phone: str
    source_customer_id: str = Field(description="Informational only - PDF 2.6 keeps Fakturama's own ID")


class Payment(BaseModel):
    method: str
    status: PaidStatus
    date: date | None


class LineItem(BaseModel):
    position: int
    sku: str
    description: str
    quantity: Decimal
    unit: str
    unit_net: Decimal
    discount_pct: Decimal
    vat_pct: Decimal
    line_net: Decimal  # the "source total" of the row


class Totals(BaseModel):
    net: Decimal
    vat: Decimal
    gross: Decimal


class OrderExtraction(BaseModel):
    external_reference: str
    order_date: date
    currency: str
    customer: Customer
    billing_address: Address
    delivery_address: Address
    payment: Payment
    items: list[LineItem]
    totals: Totals

    @property
    def billing_equals_delivery(self) -> bool:
        return self.billing_address.same_location(self.delivery_address)
