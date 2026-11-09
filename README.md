# invoice-aging-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/invoice-aging-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/invoice-aging-doctor/issues)

A zero-dependency Python CLI that turns an invoice export JSON into
an aging report, offline. It buckets open invoices by days past due,
totals them per customer and overall, and doubles as a CI gate with
`--check`.

An aging report is usually built in a spreadsheet by hand, and a
copy-paste error there quietly moves money into the wrong bucket.
This tool reads the export, does the bucket math with Decimal cents
arithmetic, and prints the same report every time.

## Install

Requires Python 3.10 or newer. No dependencies beyond the standard library.

```bash
pip install invoice-aging-doctor
```

Or run it straight from the source checkout:

```bash
python3 invoice_aging_doctor.py examples/sample.json
```

It also runs as a module:

```bash
python3 -m invoice_aging_doctor examples/sample.json
```

## Input format

A JSON list of invoice objects, or an object with an `invoices` list.
Each invoice needs `id` (or `invoice_id`), `customer`, `issue_date`,
`due_date`, and `amount`. Dates are ISO `YYYY-MM-DD`. Amounts are
numbers or numeric strings. Optional fields are `paid_amount` and
`status`.

```json
[
  {"id": "INV-001", "customer": "Acme Corp", "issue_date": "2026-10-01", "due_date": "2026-11-05", "amount": 1000.0},
  {"id": "INV-003", "customer": "Beta LLC", "issue_date": "2026-08-01", "due_date": "2026-09-06", "amount": 750.0, "paid_amount": 250.0},
  {"id": "INV-006", "customer": "Gamma Inc", "issue_date": "2026-09-15", "due_date": "2026-10-15", "amount": 400.0, "status": "paid"}
]
```

Balance is amount minus paid_amount. An invoice with status `paid`
and no paid_amount counts as fully paid. Fully paid invoices are
counted as paid and excluded from the buckets. Invoices with status
`void`, `cancelled`, or `canceled` are excluded and counted as
excluded. Everything else with a positive balance is open and aged.

## Buckets

Days past due is the reference date minus the due date. The reference
date defaults to today and can be set with `--as-of`.

| Bucket | Days past due |
| --- | --- |
| Current | 0 or fewer (not yet due, or due today) |
| 1-30 | 1 to 30 |
| 31-60 | 31 to 60 |
| 61-90 | 61 to 90 |
| 90+ | More than 90 |

Overdue means any bucket other than Current.

## Usage

Build a report (reference date defaults to today):

```bash
python3 invoice_aging_doctor.py examples/sample.json
```

Pin the reference date so the report is reproducible:

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05
```

Read from stdin (omit the argument, or pass `-`):

```bash
cat examples/sample.json | python3 invoice_aging_doctor.py - --as-of 2026-11-05
```

Gate a job on it (exit 1 if any invoice is over 90 days past due,
or if total overdue exceeds `--overdue-threshold`, else exit 0):

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --check
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --check --overdue-threshold 1000.00
```

Emit JSON instead of text:

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --json
```

Filter to one customer (case-insensitive substring match):

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --customer "Beta LLC"
```

Filter to one bucket:

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --bucket "90+"
```

## Captured output: the sample report

The sample file has 7 invoices: 6 open and 1 paid. One invoice is
due on the reference date, one is 15 days past due, one is 60 days
past due after a partial payment, one is exactly 90 days past due,
one is 121 days past due, and one is not due until December.

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05
```

Captured output:

```
Aging report as of 2026-11-05

Bucket      Count       Amount
Current         2      1250.00
1-30            1       500.00
31-60           1       500.00
61-90           1      2000.00
90+             1       300.00
Total           6      4550.00

Overdue: 4 invoice(s), 3300.00
Invoices: 7 total, 6 open, 1 paid, 0 excluded

Per-customer totals:
Customer              Count       Amount
Acme Corp                 3      1750.00
Beta LLC                  2      2500.00
Gamma Inc                 1       300.00
```

## Captured output: --check

The sample has one invoice over 90 days past due, so the gate fails:

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --check
```

Captured output (exit code 1, report above plus this last line):

```
CHECK FAILED: 1 invoice(s) over 90 days past due
```

With a threshold, both reasons are reported when both apply:

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --check --overdue-threshold 1000.00
```

Captured output (exit code 1, last line only shown here):

```
CHECK FAILED: 1 invoice(s) over 90 days past due; overdue total 3300.00 exceeds threshold 1000.00
```

With an early reference date, nothing is overdue and the gate passes:

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-06-01 --check
```

Captured output (exit code 0, last line only shown here):

```
CHECK PASSED: no invoice over 90 days past due
```

Note: `--check` looks at the full aging picture, so a `--bucket`
filter does not hide a 90+ failure. A `--customer` filter does narrow
the check to that customer.

## Captured output: --customer

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --customer "Beta LLC"
```

Captured output:

```
Aging report as of 2026-11-05

Bucket      Count       Amount
Current         0         0.00
1-30            0         0.00
31-60           1       500.00
61-90           1      2000.00
90+             0         0.00
Total           2      2500.00

Overdue: 2 invoice(s), 2500.00
Invoices: 2 total, 2 open, 0 paid, 0 excluded

Per-customer totals:
Customer              Count       Amount
Beta LLC                  2      2500.00
```

## Captured output: --bucket

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --bucket "90+"
```

Captured output:

```
Aging report as of 2026-11-05

Bucket      Count       Amount
Current         0         0.00
1-30            0         0.00
31-60           0         0.00
61-90           0         0.00
90+             1       300.00
Total           1       300.00

Overdue: 1 invoice(s), 300.00
Invoices: 1 total, 1 open, 0 paid, 0 excluded

Per-customer totals:
Customer              Count       Amount
Gamma Inc                 1       300.00
```

## Captured output: --json

```bash
python3 invoice_aging_doctor.py examples/sample.json --as-of 2026-11-05 --json
```

Captured output:

```
{
  "reference_date": "2026-11-05",
  "total_invoices": 7,
  "open_count": 6,
  "paid_count": 1,
  "excluded_count": 0,
  "buckets": {
    "Current": {
      "count": 2,
      "amount": "1250.00"
    },
    "1-30": {
      "count": 1,
      "amount": "500.00"
    },
    "31-60": {
      "count": 1,
      "amount": "500.00"
    },
    "61-90": {
      "count": 1,
      "amount": "2000.00"
    },
    "90+": {
      "count": 1,
      "amount": "300.00"
    }
  },
  "customers": {
    "Acme Corp": {
      "count": 3,
      "amount": "1750.00",
      "buckets": {
        "Current": {
          "count": 2,
          "amount": "1250.00"
        },
        "1-30": {
          "count": 1,
          "amount": "500.00"
        },
        "31-60": {
          "count": 0,
          "amount": "0.00"
        },
        "61-90": {
          "count": 0,
          "amount": "0.00"
        },
        "90+": {
          "count": 0,
          "amount": "0.00"
        }
      }
    },
    "Beta LLC": {
      "count": 2,
      "amount": "2500.00",
      "buckets": {
        "Current": {
          "count": 0,
          "amount": "0.00"
        },
        "1-30": {
          "count": 0,
          "amount": "0.00"
        },
        "31-60": {
          "count": 1,
          "amount": "500.00"
        },
        "61-90": {
          "count": 1,
          "amount": "2000.00"
        },
        "90+": {
          "count": 0,
          "amount": "0.00"
        }
      }
    },
    "Gamma Inc": {
      "count": 1,
      "amount": "300.00",
      "buckets": {
        "Current": {
          "count": 0,
          "amount": "0.00"
        },
        "1-30": {
          "count": 0,
          "amount": "0.00"
        },
        "31-60": {
          "count": 0,
          "amount": "0.00"
        },
        "61-90": {
          "count": 0,
          "amount": "0.00"
        },
        "90+": {
          "count": 1,
          "amount": "300.00"
        }
      }
    }
  },
  "overdue_count": 4,
  "overdue_amount": "3300.00",
  "grand_total": "4550.00",
  "invoices": [
    {
      "id": "INV-001",
      "customer": "Acme Corp",
      "due_date": "2026-11-05",
      "days_past_due": 0,
      "bucket": "Current",
      "balance": "1000.00"
    },
    {
      "id": "INV-002",
      "customer": "Acme Corp",
      "due_date": "2026-10-21",
      "days_past_due": 15,
      "bucket": "1-30",
      "balance": "500.00"
    },
    {
      "id": "INV-003",
      "customer": "Beta LLC",
      "due_date": "2026-09-06",
      "days_past_due": 60,
      "bucket": "31-60",
      "balance": "500.00"
    },
    {
      "id": "INV-004",
      "customer": "Beta LLC",
      "due_date": "2026-08-07",
      "days_past_due": 90,
      "bucket": "61-90",
      "balance": "2000.00"
    },
    {
      "id": "INV-005",
      "customer": "Gamma Inc",
      "due_date": "2026-07-07",
      "days_past_due": 121,
      "bucket": "90+",
      "balance": "300.00"
    },
    {
      "id": "INV-007",
      "customer": "Acme Corp",
      "due_date": "2026-12-05",
      "days_past_due": -30,
      "bucket": "Current",
      "balance": "250.00"
    }
  ]
}
```

## Captured output: bad input

`examples/invalid.json` has a due date that is not an ISO date:

```bash
python3 invoice_aging_doctor.py examples/invalid.json --as-of 2026-11-05
```

Captured output on stderr (exit code 2):

```
error: invoice INV-100: due_date is not a valid ISO date YYYY-MM-DD: 'not-a-date'
```

## Options

| Flag | Meaning |
| --- | --- |
| `input` | JSON file path, or `-` / omitted for stdin |
| `--as-of` | Reference date YYYY-MM-DD (default: today) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any invoice is over 90 days past due, or if total overdue exceeds `--overdue-threshold`; else exit 0 |
| `--overdue-threshold` | Overdue amount threshold for `--check`, for example 1000.00 |
| `--customer` | Only include invoices for this customer (case-insensitive substring) |
| `--bucket` | Only include invoices in this bucket: Current, 1-30, 31-60, 61-90, 90+ |

Exit codes: 0 for a report (or a passed check), 1 for a failed
`--check`, 2 for bad input (missing file, invalid JSON, wrong shape,
or an invoice that fails validation). Bad input errors go to stderr.

## Edge cases

* Boundary days land in the earlier bucket: exactly 30 days past due
  is 1-30, exactly 60 is 31-60, exactly 90 is 61-90. Only day 91 and
  later is 90+.
* An invoice due today is Current, not overdue. An invoice due in
  the future is also Current, with negative days past due in JSON.
* Money is Decimal rounded to cents, so amounts like 0.10 and 0.20
  add up to exactly 0.30.
* A paid_amount larger than the amount is an error, not a negative
  balance. Negative amounts are errors too.
* Dates must be exactly YYYY-MM-DD. `11/05/2026` and `2026-13-01`
  are rejected with the invoice id in the message.
* Duplicate invoice ids are not rejected, but they are not merged.
  Each row is aged on its own balance.
* With `--bucket`, the displayed report contains only that bucket,
  and its totals describe that bucket only.

## Tests

```bash
python3 -m pytest tests/ -q
python3 -m unittest discover -s tests -v
```

28 tests, all passing: bucket boundaries, the sample buckets and
per-customer totals, Decimal cents math, partial payments, paid and
void statuses, the `invoices` object wrapper, validation errors for
missing fields, bad dates, negative amounts, paid over amount,
invalid JSON, and wrong top level shape, plus CLI tests for text
and JSON output, `--check` pass and fail, the overdue threshold,
`--customer` and `--bucket` filters, stdin, module run, and exit
code 2 for bad input and bad bucket values.

## License

MIT. See [LICENSE](LICENSE).
