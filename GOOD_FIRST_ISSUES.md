# Good first issues

Seeded issues for new contributors. File each one on GitHub with the
`good first issue` and `help wanted` labels.

## 1. Accept CSV invoice exports

Title: Accept a CSV invoice export in addition to JSON

Description: Many accounting tools export CSV, not JSON. Accept a
CSV file with the same fields (id, customer, issue_date, due_date,
amount, paid_amount, status) when the input file ends in `.csv`,
and produce exactly the same report as the JSON path. The JSON
behavior must not change.

Difficulty: easy

Acceptance criteria:

* A CSV sample with one invoice per bucket produces the same bucket
  totals as the equivalent JSON.
* A CSV row with a bad date exits 2 with the invoice id in the
  error, just like the JSON path.
* An empty CSV (header row only) produces a report with zero totals.
* A test covers the CSV path and the bad date case.
* The README documents the CSV columns and the `.csv` detection.

## 2. Add a --sort option for the invoice list in JSON output

Title: Add --sort to order JSON invoice rows by due date or balance

Description: The JSON `invoices` list currently follows input
order. Add `--sort due` (oldest due date first) and `--sort balance`
(largest balance first). The text report totals must not change,
only the row order in JSON output.

Difficulty: easy

Acceptance criteria:

* `--sort due` orders JSON invoice rows by due date ascending.
* `--sort balance` orders JSON invoice rows by balance descending.
* Without `--sort`, row order stays in input order.
* An invalid `--sort` value exits 2 with a clear message.
* Tests cover both sort orders and the unchanged default order.
* The README documents the new flag.

## 3. Warn on duplicate invoice ids

Title: Report duplicate invoice ids instead of aging them silently

Description: Duplicate ids are currently aged as separate rows,
which can double count an invoice that was exported twice. Add a
warning line in text output (and a `warnings` list in JSON output)
naming each duplicated id and how many times it appears, while still
producing the report. Do not change any totals in this issue.

Difficulty: medium

Acceptance criteria:

* An export with the same id twice produces a warning naming that id.
* An export with no duplicates produces no warning.
* The JSON output carries the warnings list, empty when there are none.
* Totals are unchanged by the warning.
* Tests cover the duplicate case and the no-duplicate case.
* The README documents the warning.

## 4. Add a per-customer overdue summary section

Title: Add an overdue-only per-customer section to text output

Description: Collectors work customer by customer, and the current
per-customer table mixes current and overdue amounts. Add a second
section after the per-customer totals that lists only customers with
overdue balances, showing their overdue count and overdue amount,
sorted by overdue amount descending. The existing sections must not
change.

Difficulty: medium

Acceptance criteria:

* A sample with overdue and current invoices shows only overdue
  customers in the new section, in descending overdue amount order.
* A sample with no overdue invoices shows the section with zero
  entries, or omits it with a clear note, and the choice is documented.
* Overdue counts and amounts match the bucket totals for those
  customers.
* Tests cover the ordering and the no-overdue case.
* The README documents the new section.
