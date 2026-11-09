"""invoice-aging-doctor: aging report for an invoice export.

Reads a JSON invoice export and produces an aging report: buckets
Current, 1-30, 31-60, 61-90, and 90+ days past due, per-customer
totals, grand totals, and overdue count and amount.

Input format: a JSON list of invoice objects, or an object with an
"invoices" list. Each invoice needs:

    id (or invoice_id): string or number, required
    customer: string, required
    issue_date: ISO date YYYY-MM-DD, required
    due_date: ISO date YYYY-MM-DD, required
    amount: number or numeric string, required, zero or positive
    paid_amount: optional number or numeric string, zero or positive
    status: optional string, for example "open", "paid", "void"

Rules:

* Money uses Decimal and is rounded to cents, so 0.1 plus 0.2 style
  float errors never leak into a report.
* Balance is amount minus paid_amount. An invoice with status "paid"
  and no paid_amount counts as fully paid (balance zero).
* Invoices with status "void", "cancelled", or "canceled" are
  excluded from the aging buckets and counted as excluded.
* Fully paid invoices (balance zero) are counted as paid and are
  excluded from the buckets.
* Bucket by days past due on the reference date: due date on or
  after the reference date is Current (0 or fewer days past due),
  1 to 30 days is "1-30", 31 to 60 is "31-60", 61 to 90 is "61-90",
  and more than 90 days is "90+".
* Overdue means any bucket other than Current.
* With --check, exit 1 when any invoice is more than 90 days past
  due, or when a --overdue-threshold is given and the total overdue
  amount is greater than that threshold. Otherwise exit 0.
* Exit 2 means bad input: missing file, invalid JSON, wrong shape,
  or an invoice that fails validation. The error goes to stderr.

Usage:

    python3 invoice_aging_doctor.py examples/sample.json
    python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05
    python3 invoice_aging_doctor.py examples/sample.json --json
    python3 invoice_aging_doctor.py examples/sample.json --check
    python3 invoice_aging_doctor.py examples/sample.json --customer "Acme Corp"
    python3 invoice_aging_doctor.py examples/sample.json --bucket "90+"
    cat examples/sample.json | python3 invoice_aging_doctor.py -
"""

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

__version__ = "1.0.0"

BUCKETS = ["Current", "1-30", "31-60", "61-90", "90+"]
CENT = Decimal("0.01")
PAID_STATUSES = {"paid", "settled"}
EXCLUDED_STATUSES = {"void", "cancelled", "canceled"}


class InputError(ValueError):
    """Raised for any bad input that should exit 2."""


def parse_iso_date(value, field, label):
    if not isinstance(value, str):
        raise InputError(f"{label}: {field} must be an ISO date string, got {value!r}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise InputError(f"{label}: {field} is not a valid ISO date YYYY-MM-DD: {value!r}")
    if parsed.isoformat() != value:
        raise InputError(f"{label}: {field} is not a valid ISO date YYYY-MM-DD: {value!r}")
    return parsed


def parse_money(value, field, label):
    if isinstance(value, bool):
        raise InputError(f"{label}: {field} must be a number, got {value!r}")
    if isinstance(value, (int, float)):
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise InputError(f"{label}: {field} is not a valid amount: {value!r}")
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise InputError(f"{label}: {field} must not be empty")
        try:
            amount = Decimal(text)
        except InvalidOperation:
            raise InputError(f"{label}: {field} is not a valid amount: {value!r}")
    else:
        raise InputError(f"{label}: {field} must be a number, got {value!r}")
    amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if amount < 0:
        raise InputError(f"{label}: {field} must not be negative: {value!r}")
    return amount


def bucket_for(days_past_due):
    if days_past_due <= 0:
        return "Current"
    if days_past_due <= 30:
        return "1-30"
    if days_past_due <= 60:
        return "31-60"
    if days_past_due <= 90:
        return "61-90"
    return "90+"


def normalize_invoice(raw, index):
    label = f"invoice {index}"
    if not isinstance(raw, dict):
        raise InputError(f"{label}: each invoice must be an object, got {type(raw).__name__}")
    invoice_id = raw.get("id", raw.get("invoice_id", raw.get("invoiceId")))
    if invoice_id is None or (isinstance(invoice_id, str) and not invoice_id.strip()):
        raise InputError(f"{label}: missing required field 'id'")
    label = f"invoice {invoice_id}"
    customer = raw.get("customer")
    if not isinstance(customer, str) or not customer.strip():
        raise InputError(f"{label}: missing or empty required field 'customer'")
    if "issue_date" not in raw:
        raise InputError(f"{label}: missing required field 'issue_date'")
    if "due_date" not in raw:
        raise InputError(f"{label}: missing required field 'due_date'")
    issue = parse_iso_date(raw["issue_date"], "issue_date", label)
    due = parse_iso_date(raw["due_date"], "due_date", label)
    if "amount" not in raw:
        raise InputError(f"{label}: missing required field 'amount'")
    amount = parse_money(raw["amount"], "amount", label)
    status = raw.get("status")
    status_norm = status.strip().lower() if isinstance(status, str) else ""
    if status is not None and not isinstance(status, str):
        raise InputError(f"{label}: status must be a string, got {status!r}")
    if "paid_amount" in raw and raw["paid_amount"] is not None:
        paid = parse_money(raw["paid_amount"], "paid_amount", label)
    elif status_norm in PAID_STATUSES:
        paid = amount
    else:
        paid = Decimal("0.00")
    if paid > amount:
        raise InputError(f"{label}: paid_amount {paid} exceeds amount {amount}")
    return {
        "id": str(invoice_id),
        "customer": customer.strip(),
        "issue_date": issue,
        "due_date": due,
        "amount": amount,
        "paid_amount": paid,
        "balance": amount - paid,
        "status": status_norm,
    }


def load_invoices(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON: {exc}")
    if isinstance(data, dict):
        if "invoices" not in data:
            raise InputError("JSON object must contain an 'invoices' list")
        raw_list = data["invoices"]
    elif isinstance(data, list):
        raw_list = data
    else:
        raise InputError("JSON top level must be a list of invoices or an object with an 'invoices' list")
    if not isinstance(raw_list, list):
        raise InputError("'invoices' must be a list")
    return [normalize_invoice(raw, index) for index, raw in enumerate(raw_list)]


def build_report(invoices, reference):
    buckets = {name: {"count": 0, "amount": Decimal("0.00")} for name in BUCKETS}
    customers = {}
    rows = []
    total_invoices = len(invoices)
    paid_count = 0
    excluded_count = 0
    for inv in invoices:
        if inv["status"] in EXCLUDED_STATUSES:
            excluded_count += 1
            continue
        if inv["balance"] <= 0:
            paid_count += 1
            continue
        days = (reference - inv["due_date"]).days
        bucket = bucket_for(days)
        buckets[bucket]["count"] += 1
        buckets[bucket]["amount"] += inv["balance"]
        entry = customers.setdefault(
            inv["customer"],
            {"buckets": {name: {"count": 0, "amount": Decimal("0.00")} for name in BUCKETS},
             "total_count": 0, "total_amount": Decimal("0.00")},
        )
        entry["buckets"][bucket]["count"] += 1
        entry["buckets"][bucket]["amount"] += inv["balance"]
        entry["total_count"] += 1
        entry["total_amount"] += inv["balance"]
        rows.append({
            "id": inv["id"],
            "customer": inv["customer"],
            "due_date": inv["due_date"].isoformat(),
            "days_past_due": days,
            "bucket": bucket,
            "balance": inv["balance"],
        })
    overdue_count = sum(buckets[name]["count"] for name in BUCKETS if name != "Current")
    overdue_amount = sum((buckets[name]["amount"] for name in BUCKETS if name != "Current"),
                         Decimal("0.00"))
    grand_total = sum((buckets[name]["amount"] for name in BUCKETS), Decimal("0.00"))
    open_count = sum(buckets[name]["count"] for name in BUCKETS)
    return {
        "reference_date": reference.isoformat(),
        "total_invoices": total_invoices,
        "open_count": open_count,
        "paid_count": paid_count,
        "excluded_count": excluded_count,
        "buckets": buckets,
        "customers": customers,
        "rows": rows,
        "overdue_count": overdue_count,
        "overdue_amount": overdue_amount,
        "grand_total": grand_total,
    }


def money_str(amount):
    return f"{amount:.2f}"


def format_text(report):
    lines = []
    lines.append(f"Aging report as of {report['reference_date']}")
    lines.append("")
    lines.append(f"{'Bucket':<10} {'Count':>6} {'Amount':>12}")
    for name in BUCKETS:
        entry = report["buckets"][name]
        lines.append(f"{name:<10} {entry['count']:>6} {money_str(entry['amount']):>12}")
    lines.append(f"{'Total':<10} {report['open_count']:>6} {money_str(report['grand_total']):>12}")
    lines.append("")
    lines.append(f"Overdue: {report['overdue_count']} invoice(s), {money_str(report['overdue_amount'])}")
    lines.append(f"Invoices: {report['total_invoices']} total, "
                 f"{report['open_count']} open, {report['paid_count']} paid, "
                 f"{report['excluded_count']} excluded")
    if report["customers"]:
        lines.append("")
        lines.append("Per-customer totals:")
        lines.append(f"{'Customer':<20} {'Count':>6} {'Amount':>12}")
        for customer in sorted(report["customers"]):
            entry = report["customers"][customer]
            lines.append(f"{customer:<20} {entry['total_count']:>6} {money_str(entry['total_amount']):>12}")
    return "\n".join(lines) + "\n"


def report_to_json(report):
    def bucket_json(entry):
        return {"count": entry["count"], "amount": money_str(entry["amount"])}
    return {
        "reference_date": report["reference_date"],
        "total_invoices": report["total_invoices"],
        "open_count": report["open_count"],
        "paid_count": report["paid_count"],
        "excluded_count": report["excluded_count"],
        "buckets": {name: bucket_json(report["buckets"][name]) for name in BUCKETS},
        "customers": {
            customer: {
                "count": entry["total_count"],
                "amount": money_str(entry["total_amount"]),
                "buckets": {name: bucket_json(entry["buckets"][name]) for name in BUCKETS},
            }
            for customer, entry in sorted(report["customers"].items())
        },
        "overdue_count": report["overdue_count"],
        "overdue_amount": money_str(report["overdue_amount"]),
        "grand_total": money_str(report["grand_total"]),
        "invoices": [
            {
                "id": row["id"],
                "customer": row["customer"],
                "due_date": row["due_date"],
                "days_past_due": row["days_past_due"],
                "bucket": row["bucket"],
                "balance": money_str(row["balance"]),
            }
            for row in report["rows"]
        ],
    }


def check_failed(report, overdue_threshold):
    has_90plus = report["buckets"]["90+"]["count"] > 0
    over_threshold = (
        overdue_threshold is not None and report["overdue_amount"] > overdue_threshold
    )
    return has_90plus or over_threshold


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="invoice-aging-doctor",
        description="Build an invoice aging report from a JSON invoice export.",
    )
    parser.add_argument("input", nargs="?", default=None,
                        help="JSON file path, or '-' / omitted for stdin")
    parser.add_argument("--as-of", default=None,
                        help="Reference date YYYY-MM-DD (default: today)")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 if any invoice is over 90 days past due, "
                             "or if total overdue exceeds --overdue-threshold")
    parser.add_argument("--overdue-threshold", default=None,
                        help="Overdue amount threshold for --check, for example 1000.00")
    parser.add_argument("--customer", default=None,
                        help="Only include invoices for this customer (case-insensitive substring)")
    parser.add_argument("--bucket", default=None,
                        help="Only include invoices in this bucket: Current, 1-30, 31-60, 61-90, 90+")
    args = parser.parse_args(argv)
    if args.as_of is not None:
        try:
            args.reference = parse_iso_date(args.as_of, "--as-of", "reference date")
        except InputError as exc:
            parser.error(str(exc))
    else:
        args.reference = date.today()
    if args.bucket is not None:
        wanted = args.bucket.strip()
        match = next((name for name in BUCKETS if name.lower() == wanted.lower()), None)
        if match is None:
            parser.error(f"invalid --bucket {args.bucket!r}, expected one of: {', '.join(BUCKETS)}")
        args.bucket = match
    if args.overdue_threshold is not None:
        try:
            args.threshold = parse_money(args.overdue_threshold, "--overdue-threshold", "threshold")
        except InputError as exc:
            parser.error(str(exc))
    else:
        args.threshold = None
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.input is None or args.input == "-":
            text = sys.stdin.read()
        else:
            try:
                with open(args.input, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except OSError as exc:
                print(f"error: cannot read {args.input}: {exc.strerror or exc}", file=sys.stderr)
                return 2
        invoices = load_invoices(text)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.customer is not None:
        needle = args.customer.strip().lower()
        invoices = [inv for inv in invoices if needle in inv["customer"].lower()]
    report = build_report(invoices, args.reference)
    if args.bucket is not None:
        report["rows"] = [row for row in report["rows"] if row["bucket"] == args.bucket]
        report["buckets"] = {
            name: (report["buckets"][name] if name == args.bucket
                   else {"count": 0, "amount": Decimal("0.00")})
            for name in BUCKETS
        }
        report["customers"] = {
            customer: {
                "buckets": {
                    name: (entry["buckets"][name] if name == args.bucket
                           else {"count": 0, "amount": Decimal("0.00")})
                    for name in BUCKETS
                },
                "total_count": entry["buckets"][args.bucket]["count"],
                "total_amount": entry["buckets"][args.bucket]["amount"],
            }
            for customer, entry in report["customers"].items()
            if entry["buckets"][args.bucket]["count"] > 0
        }
        report["open_count"] = report["buckets"][args.bucket]["count"]
        report["grand_total"] = report["buckets"][args.bucket]["amount"]
        report["total_invoices"] = report["open_count"]
        report["paid_count"] = 0
        report["excluded_count"] = 0
        if args.bucket == "Current":
            report["overdue_count"] = 0
            report["overdue_amount"] = Decimal("0.00")
        else:
            report["overdue_count"] = report["open_count"]
            report["overdue_amount"] = report["grand_total"]
    if args.json:
        print(json.dumps(report_to_json(report), indent=2))
    else:
        print(format_text(report), end="")
    if args.check:
        # The check must look at the full unfiltered aging picture,
        # not at a filtered view, so recompute from the raw set.
        full = build_report(
            [inv for inv in load_invoices(text)
             if args.customer is None or args.customer.strip().lower() in inv["customer"].lower()],
            args.reference,
        ) if args.bucket is not None else report
        if check_failed(full, args.threshold):
            if not args.json:
                reasons = []
                if full["buckets"]["90+"]["count"] > 0:
                    reasons.append(f"{full['buckets']['90+']['count']} invoice(s) over 90 days past due")
                if args.threshold is not None and full["overdue_amount"] > args.threshold:
                    reasons.append(
                        f"overdue total {money_str(full['overdue_amount'])} exceeds threshold "
                        f"{money_str(args.threshold)}")
                print("CHECK FAILED: " + "; ".join(reasons))
            return 1
        if not args.json:
            print("CHECK PASSED: no invoice over 90 days past due"
                  + ("" if args.threshold is None
                     else f" and overdue total within threshold {money_str(args.threshold)}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
