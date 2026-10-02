"""Every visible Fakturama string the automation relies on (English UI, Fakturama 2.1.x).

Only this module knows the wording; a German install would swap this file. Values were taken
from live UIA dumps (tools/dump_uia_tree.py), not from screenshots. Toolbar/list buttons are
matched by their tooltip, which SWT exposes as the UIA Name.
"""

# --------------------------------------------------------------------------- shell
TOOLBAR_NEW_ORDER = "Create: New Order"
TOOLBAR_SAVE = "Save the current contents"

NAV_DOCUMENTS = "Documents"
NAV_VATS = "VATs"
NAV_PAYMENTS = "terms of payment"
NAV_NEW_PRODUCT = "New product"
NAV_NEW_CONTACT = "New Contact"

LIST_CREATE_VAT = "Create a new tax rate"
LIST_CREATE_PAYMENT = "Create a new term of payment"

SEARCH = "Search:"
OK = "OK"
CANCEL = "Cancel"
NO_BUTTONS = ("No", "&No", "Don't Save")

# --------------------------------------------------------------------------- selector dialogs
DLG_SELECT_ADDRESS = "Select the address"
DLG_SELECT_PRODUCT = "Select a product"
ADDRESS_COLUMNS = ["No.", "First Name", "Name", "Company", "ZIP", "City"]
PRODUCT_COLUMNS = ["Item No.", "Name", "Description", "Price", "VAT"]

# --------------------------------------------------------------------------- document editors
EDITOR_NEW_ORDER = "New Order"
EDITOR_NEW_INVOICE = "New Invoice"
DOC_NO = "No."
DOC_DATE = "Date"
CUST_REF = "Cust.Ref."
VAT_MODE = "VAT"
VAT_MODE_WITH_VAT = "With VAT"
PRICE_MODE_NET = "Net"  # unnamed combo right of the Date field
ADDRESSES = "Addresses"
ITEMS = "Items"
TAB_INVOICE_ADDRESS = "Invoice address"
TAB_DELIVERY_ADDRESS = "Delivery address"
FOLLOWUP_INVOICE = "Invoice"
TOTAL_NET = ("Total Net", "Total Gross")  # caption follows the document price mode
DOC_DISCOUNT = "Discount"
SHIPPING = "Shipping"
SHIPPING_FREE = "Free of shipping costs"
DOC_VAT = "VAT"
DOC_TOTAL = "Total"
ITEM_COLUMNS = ["Pos.", "Qty.", "Item No.", "Picture", "Name", "Description", "VAT", "U.Price", "Discount", "Price"]

# Invoice payment strip (bottom-left of the invoice editor)
PAID_CHECKBOX = "paid"
PAID_AT = "at"  # payment date, shown once 'paid' is ticked
PAID_VALUE = "Value"
SERVICE_DATE = "Service date"
ORDER_DATE = "Order Date"
STATE_PAID = "paid"
STATE_OPEN = "open"  # Orders
STATE_UNPAID = "unpaid"  # Invoices without payment

# --------------------------------------------------------------------------- debtor editor
EDITOR_NEW_DEBTOR = "New Debtor"
CUSTOMER_ID = "Customer ID"
COMPANY = "Company"
SALUTATION = "Salutation"
SALUTATION_NONE = "---"
FIRST_LAST_NAME = "First Name Last Name"
TAB_ADDRESSES = "Addresses"
TAB_MISC = "Miscellaneous"
TAB_MAIN_ADDRESS = "Main address"
ADD_ADDRESS = "+"
ADDITIONAL_NAME = "additional name"
STREET = "Street"
ZIP_CITY = "ZIP - City"
COUNTRY = "Country"
EMAIL = "E-Mail"
TELEPHONE = "Telephone"
ADDRESS_TYPE = "address type"
ROLE_INVOICE = "Invoice address"
ROLE_DELIVERY = "Delivery address"
ALIAS = "Alias name"
DEBTOR_PAYMENT = "Payment"
DEBTOR_DISCOUNT = "Discount"
NET_OR_GROSS = "Net or Gross"
NET = "Net"

# --------------------------------------------------------------------------- terms of payment
EDITOR_NEW_PAYMENT = "New Term of Payment"
PAYMENT_COLUMNS = ["Standard", "Name", "Description", "Discount", "Disc. Days", "Net Days"]
NAME = "Name"
DESCRIPTION = "Description"
ACCOUNT = "Account"
# Fakturama 2.1 ships this label untranslated ('!editorPaymentPaymentcode!'), so match loosely.
PAYMENT_CODE_PATTERN = r"payment\s*code"
CASH_DISCOUNT = "Cash discount"
DISCOUNT_DAYS = "Discount Days"
NET_DAYS = "Net Days"
# PDF 2.10.4 mapping: extracted payment method -> payment-code dropdown entry
PAYMENT_CODE_MAP = {
    "bank transfer": "Credit transfer",
    "credit card": "Credit card",
    "sepa direct debit": "SEPA direct debit",
}

# --------------------------------------------------------------------------- VATs
EDITOR_NEW_VAT = "New TAX Rate"
VAT_COLUMNS = ["Standard", "Name", "Description", "Value"]
VAT_CODE = "VAT code (E-Invoice)"
VAT_CODE_STANDARD_PATTERN = r"^\s*S\b"
VAT_VALUE = "Value"

# --------------------------------------------------------------------------- products
PRODUCT_ITEM_NUMBER = "Item Number"
PRODUCT_NAME = "Name"
PRODUCT_DESCRIPTION = "Description"
PRODUCT_PRICE_GROSS = "Price (gross)"
PRODUCT_COST_PRICE = "cost price (net)"
PRODUCT_VAT = "VAT"
PRODUCT_STOCK = "Stock"

# --------------------------------------------------------------------------- documents list
DOCUMENT_COLUMNS = ["Document", "Date", "Name", "Cust.Ref.", "State", "Total"]

# Document numbers as Fakturama formats them by default (Preferences > Number Range > Format).
ORDER_NUMBER_PATTERN = r"^P[O0]\d+"  # O/0 confusion tolerated
# Fakturama's warning when a follow-up already exists ("... already a follow-up ... (INV000001) ...")
FOLLOWUP_EXISTS_PATTERN = r"already a follow-up"
