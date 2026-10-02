"""Plain-language captions for each PDF step, used by --narrate (recordings / demos)."""

from __future__ import annotations

# Longest matching prefix wins, so "2.10.1" beats "2.10".
CAPTIONS: dict[str, str] = {
    "1.1-1.2": "Extract the order image: PaddleOCR reads the text, the LLM maps it to fields, every value is checked against the OCR text and the totals are recomputed",
    "R": "Resume: continue from what is already saved in Fakturama - never a second Order",
    "0": "Safety check: is there already a document with this External Reference?",
    "1.3": "Open a New Order from the toolbar",
    "1.4": "Keep the order number Fakturama proposes",
    "1.5": "Type the Order Date from the image (segment by segment)",
    "1.6": "Enter the External Reference as Cust.Ref.",
    "1.7": "Price mode Net, VAT mode With VAT",
    "2.1-2.3": "Look for the Debtor from the Order: upper address icon, search company, exact match on Company, First Name, Name, ZIP, City",
    "2.4": "Debtor selected - check Invoice and Delivery address against the image",
    "2.10.1": "Payment method: search Data > terms of payment for an exact match",
    "2.10.2": "Payment method exists - open it and check its payment code is the required one",
    "2.10.3": "Payment method missing - create it (required payment code, 0 days)",
    "2.10.6": "Save the payment method once",
    "2.5": "No exact Debtor - create one: New Contact (the Order stays open)",
    "2.6": "Debtor identity: Company, First Name, Last Name",
    "2.7": "Main address: street, ZIP, city, country, e-mail, phone",
    "2.8": "Address roles: billing = Invoice address, warehouse = Delivery address",
    "2.9": "Miscellaneous: alias, discount 0 %, Net",
    "2.10": "Select the payment method on the Debtor",
    "2.11": "Save the Debtor once",
    "2.12": "Back to the same Order - search the Debtor again and select it",
    "2.13": "Check the new Debtor's addresses on the Order",
    "3.2-3.3": "Product: upper product icon, search the exact SKU",
    "3.4": "Product missing - first make sure the VAT rate exists (Data > VATs)",
    "3.5": "Reuse VAT only if name, value and E-Invoice code S all match",
    "3.6": "Create the VAT rate",
    "3.7": "New product (the Order stays open)",
    "3.8": "Product fields: SKU, name, gross price = net x (1 + VAT), VAT, cost 0, stock 0",
    "3.11": "Save the Product once",
    "3.12": "Back to the Order - select the new Product",
    "3.13": "Set the quantity",
    "3.14": "Confirm unit price and VAT rate of the line",
    "3.15": "Set the line discount",
    "3.16": "Verify line price = qty x unit price x (1 - discount)",
    "4.1": "Verify addresses and every line against the image",
    "4.2": "Order discount 0 %, free shipping",
    "4.3": "Verify Total Net, VAT and Total against the image",
    "4.4": "Save the Order once",
    "4.5": "Data > Documents: the Order row with reference, date, state open, total",
    "4.6-4.7": "Create the linked Invoice from the Order's follow-up area",
    "5.1": "Invoice: keep its number and dates, check everything copied from the Order",
    "5.2": "Invoice payment method = the one on the image (not available -> stop for manual review)",
    "5.3": "Paid status from the image: tick paid, payment date, full amount",
    "5.4": "Save the Invoice once",
    "5.5": "Data > Documents: Invoice paid, Order still open",
    "5.6": "Verify the stored payment fields",
    "5.7": "Done - no Delivery, Correction or Dunning",
}


# Plain section titles for the overlay/console (no PDF step numbers on screen).
SECTIONS: dict[str, str] = {
    "1.1": "Reading the order image",
    "R": "Resuming after manual review",
    "0": "Safety check",
    "1": "New Order",
    "2.10": "Payment method",
    "2": "Customer",
    "3.4": "VAT rate", "3.5": "VAT rate", "3.6": "VAT rate",
    "3": "Products",
    "4.6": "Linked Invoice", "4.7": "Linked Invoice",
    "4": "Complete the Order",
    "5": "Invoice payment",
}
STATUS_TEXT = {"found": "found", "missing": "not found - creating it", "manual_review": "stopped for manual review",
               "failed": "failed", "ok": "done"}


def section_for(step: str) -> str:
    key = max((k for k in SECTIONS if step.startswith(k)), key=len, default=None)
    return SECTIONS[key] if key else "Automation"


def caption_for(step: str) -> str:
    key = max((k for k in CAPTIONS if step.startswith(k)), key=len, default=None)
    return CAPTIONS[key] if key else step


class Narrator:
    """Hooked into Evidence: shows each step on the overlay + console, then waits ``pace`` s."""

    def __init__(self, pace: float = 1.5, overlay: bool = True):
        import time

        from ..ui.overlay import Overlay

        self._sleep = time.sleep
        self.pace = pace
        self.overlay = Overlay() if overlay else None

    def begin(self, step: str) -> None:
        title, caption = section_for(step), caption_for(step)  # no PDF step numbers on screen
        print(f"\n\033[1;36m▶ {title}\033[0m  {caption}", flush=True)
        if self.overlay:
            self.overlay.show(title, caption)

    def result(self, step: str, status: str, summary: str = "") -> None:
        colour = {"ok": "32", "found": "32", "missing": "33", "manual_review": "35", "failed": "31"}.get(status, "37")
        print(f"   \033[{colour}m{status.upper()}\033[0m {summary}".rstrip(), flush=True)
        if status in ("missing", "found", "manual_review", "failed") and self.overlay and summary:
            self.overlay.show(f"{section_for(step)} - {STATUS_TEXT.get(status, status)}", summary)
        if status not in ("found", "missing"):
            self._sleep(self.pace)

    def close(self) -> None:
        if self.overlay:
            self.overlay.close()


def summarize(step: str, status: str, details: dict) -> str:
    """One short human sentence for match/verification records."""
    if "rows" in details and "match" in step:
        n = len(details.get("rows") or [])
        what = {"found": "exact match -> select it", "missing": "no exact match -> create it",
                "ambiguous": "conflicting rows -> stop"}.get(status, status)
        return f"{n} row(s) in the list: {what}"
    if "added" in details:
        return f"selector picked the single hit and added line {details['added']}"
    if "shown" in details and isinstance(details["shown"], dict) and "net" in details["shown"]:
        t = details["shown"]
        return f"Net {t['net']}  VAT {t['vat']}  Total {t['total']}"
    if "price" in details and "expected" in details:
        return f"line price {details['price']} (expected {details['expected']})"
    if "reason" in details:
        return str(details["reason"])
    if "error" in details:
        return str(details["error"])
    return ""
