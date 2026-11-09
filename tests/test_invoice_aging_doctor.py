"""Tests for invoice_aging_doctor. Runnable with unittest or pytest."""

import json
import subprocess
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from invoice_aging_doctor import (
    InputError,
    bucket_for,
    build_report,
    check_failed,
    load_invoices,
    main,
)

REF = date(2026, 11, 5)


def invoice(**overrides):
    base = {
        "id": "INV-1",
        "customer": "Acme Corp",
        "issue_date": "2026-10-01",
        "due_date": "2026-11-05",
        "amount": "100.00",
    }
    base.update(overrides)
    return base


def report_for(raw_list, ref=REF):
    return build_report(load_invoices(json.dumps(raw_list)), ref)


class TestBuckets(unittest.TestCase):
    def test_bucket_boundaries(self):
        self.assertEqual(bucket_for(-5), "Current")
        self.assertEqual(bucket_for(0), "Current")
        self.assertEqual(bucket_for(1), "1-30")
        self.assertEqual(bucket_for(30), "1-30")
        self.assertEqual(bucket_for(31), "31-60")
        self.assertEqual(bucket_for(60), "31-60")
        self.assertEqual(bucket_for(61), "61-90")
        self.assertEqual(bucket_for(90), "61-90")
        self.assertEqual(bucket_for(91), "90+")

    def test_sample_buckets(self):
        sample = json.loads(
            (Path(__file__).resolve().parent.parent / "examples" / "sample.json").read_text()
        )
        report = build_report(load_invoices(json.dumps(sample)), REF)
        counts = {name: report["buckets"][name]["count"] for name in report["buckets"]}
        self.assertEqual(counts, {"Current": 2, "1-30": 1, "31-60": 1, "61-90": 1, "90+": 1})
        self.assertEqual(report["grand_total"], Decimal("4550.00"))
        self.assertEqual(report["overdue_count"], 4)
        self.assertEqual(report["overdue_amount"], Decimal("3300.00"))

    def test_per_customer_totals(self):
        sample = json.loads(
            (Path(__file__).resolve().parent.parent / "examples" / "sample.json").read_text()
        )
        report = build_report(load_invoices(json.dumps(sample)), REF)
        self.assertEqual(report["customers"]["Acme Corp"]["total_amount"], Decimal("1750.00"))
        self.assertEqual(report["customers"]["Beta LLC"]["total_amount"], Decimal("2500.00"))
        self.assertEqual(report["customers"]["Gamma Inc"]["total_amount"], Decimal("300.00"))


class TestMoneyAndStatus(unittest.TestCase):
    def test_decimal_cents_math(self):
        report = report_for([
            invoice(id="A", amount="0.10", due_date="2026-11-05"),
            invoice(id="B", amount="0.20", due_date="2026-11-05"),
        ])
        self.assertEqual(report["grand_total"], Decimal("0.30"))

    def test_partial_payment_reduces_balance(self):
        report = report_for([invoice(amount="750.00", paid_amount="250.00",
                                      due_date="2026-09-06")])
        self.assertEqual(report["buckets"]["31-60"]["amount"], Decimal("500.00"))

    def test_paid_status_without_paid_amount(self):
        report = report_for([invoice(status="paid")])
        self.assertEqual(report["open_count"], 0)
        self.assertEqual(report["paid_count"], 1)

    def test_void_excluded(self):
        report = report_for([invoice(status="void"), invoice(id="B")])
        self.assertEqual(report["excluded_count"], 1)
        self.assertEqual(report["open_count"], 1)

    def test_object_wrapper_with_invoices_key(self):
        report = build_report(load_invoices(json.dumps({"invoices": [invoice()]})), REF)
        self.assertEqual(report["open_count"], 1)


class TestValidation(unittest.TestCase):
    def test_missing_customer(self):
        bad = invoice()
        del bad["customer"]
        with self.assertRaises(InputError):
            load_invoices(json.dumps([bad]))

    def test_bad_date(self):
        with self.assertRaises(InputError):
            load_invoices(json.dumps([invoice(due_date="2026-13-01")]))

    def test_non_iso_date_rejected(self):
        with self.assertRaises(InputError):
            load_invoices(json.dumps([invoice(due_date="11/05/2026")]))

    def test_negative_amount(self):
        with self.assertRaises(InputError):
            load_invoices(json.dumps([invoice(amount="-5.00")]))

    def test_paid_exceeds_amount(self):
        with self.assertRaises(InputError):
            load_invoices(json.dumps([invoice(amount="100.00", paid_amount="150.00")]))

    def test_invalid_json(self):
        with self.assertRaises(InputError):
            load_invoices("{not json")

    def test_wrong_top_level(self):
        with self.assertRaises(InputError):
            load_invoices(json.dumps({"nope": []}))


class TestCli(unittest.TestCase):
    def run_cli(self, *args, stdin_data=None):
        cmd = [sys.executable, "invoice_aging_doctor.py", *args]
        cwd = Path(__file__).resolve().parent.parent
        return subprocess.run(cmd, cwd=cwd, input=stdin_data, text=True,
                              capture_output=True, check=False)

    def test_text_output_contains_totals(self):
        result = self.run_cli("examples/sample.json", "--as-of", "2026-11-05")
        self.assertEqual(result.returncode, 0)
        self.assertIn("4550.00", result.stdout)
        self.assertIn("Overdue: 4 invoice(s), 3300.00", result.stdout)

    def test_json_output_shape(self):
        result = self.run_cli("examples/sample.json", "--as-of", "2026-11-05", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["grand_total"], "4550.00")
        self.assertEqual(data["overdue_count"], 4)
        self.assertEqual(data["buckets"]["90+"]["count"], 1)

    def test_check_fails_on_90plus(self):
        result = self.run_cli("examples/sample.json", "--as-of", "2026-11-05", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("CHECK FAILED", result.stdout)

    def test_check_passes_with_early_reference(self):
        result = self.run_cli("examples/sample.json", "--as-of", "2026-06-01", "--check")
        self.assertEqual(result.returncode, 0)
        self.assertIn("CHECK PASSED", result.stdout)

    def test_overdue_threshold(self):
        result = self.run_cli("examples/sample.json", "--as-of", "2026-06-01", "--check",
                              "--overdue-threshold", "100.00")
        # At 2026-06-01 nothing is overdue, so the threshold does not trip.
        self.assertEqual(result.returncode, 0)

    def test_customer_filter(self):
        result = self.run_cli("examples/sample.json", "--as-of", "2026-11-05",
                              "--customer", "Beta LLC")
        self.assertEqual(result.returncode, 0)
        self.assertIn("2500.00", result.stdout)
        self.assertNotIn("Acme Corp", result.stdout)

    def test_bucket_filter(self):
        result = self.run_cli("examples/sample.json", "--as-of", "2026-11-05",
                              "--bucket", "90+")
        self.assertEqual(result.returncode, 0)
        self.assertIn("300.00", result.stdout)

    def test_stdin_input(self):
        sample = (Path(__file__).resolve().parent.parent / "examples" / "sample.json").read_text()
        result = self.run_cli("-", "--as-of", "2026-11-05", stdin_data=sample)
        self.assertEqual(result.returncode, 0)
        self.assertIn("4550.00", result.stdout)

    def test_module_run(self):
        cwd = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "-m", "invoice_aging_doctor", "examples/sample.json",
             "--as-of", "2026-11-05"],
            cwd=cwd, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("4550.00", result.stdout)

    def test_invalid_file_exits_2(self):
        result = self.run_cli("examples/invalid.json", "--as-of", "2026-11-05")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)

    def test_missing_file_exits_2(self):
        result = self.run_cli("examples/nope.json")
        self.assertEqual(result.returncode, 2)

    def test_bad_bucket_exits_2(self):
        result = self.run_cli("examples/sample.json", "--bucket", "bogus")
        self.assertEqual(result.returncode, 2)


class TestCheckLogic(unittest.TestCase):
    def test_check_failed_by_threshold_only(self):
        report = report_for([invoice(due_date="2026-10-21")], ref=REF)
        self.assertFalse(check_failed(report, None))
        self.assertTrue(check_failed(report, Decimal("50.00")))
        self.assertFalse(check_failed(report, Decimal("100.00")))


if __name__ == "__main__":
    unittest.main()
