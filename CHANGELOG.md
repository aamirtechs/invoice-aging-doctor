# Changelog

## 1.0.0 - 2026-11-05

Initial release.

* Reads a JSON invoice export (list, or object with an `invoices`
  list) with invoice id, customer, issue date, due date, amount, and
  optional paid amount or status.
* Aging buckets Current, 1-30, 31-60, 61-90, and 90+ days past due,
  based on a reference date (default today, or `--as-of`).
* Per-customer totals, grand totals, overdue count and amount, and
  open, paid, and excluded invoice counts.
* Decimal cents math for all amounts, so float errors never leak
  into a report.
* Text and `--json` output, `--check` CI gate (exit 1 on any invoice
  over 90 days past due, or on total overdue over
  `--overdue-threshold`), `--customer` and `--bucket` filters, and
  file or stdin input.
* Clear exit 2 errors on stderr for missing files, invalid JSON,
  wrong shape, and invoices that fail validation.
* Zero dependencies, Python 3.10 or newer.
