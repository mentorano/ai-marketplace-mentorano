#!/usr/bin/env python3
"""Tests for plugins/clean-code/skills/clean-code/boundaries.py.

Every fixture is a scratch package written into a temporary directory, so a
test names the one boundary it breaks and nothing else.

Run:  python3 tests/test_boundaries.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "clean-code" / "skills" / "clean-code" / "boundaries.py"
RULES = (
    "upward",
    "cycles",
    "cyclic_modules",
    "core_outward",
    "framework_in_domain",
    "sql_in_api",
    "sql_sites",
    "http_in_services",
    "ports",
)


def load_boundaries():
    spec = importlib.util.spec_from_file_location("boundaries", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["boundaries"] = module
    spec.loader.exec_module(module)
    return module


boundaries = load_boundaries()


def write_package(tmp: Path, files: dict[str, str]) -> Path:
    """A package `app` under tmp with the given files and an __init__.py in every directory."""
    app = tmp / "app"
    for relative, body in files.items():
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    for directory in [app, *(child for child in app.rglob("*") if child.is_dir())]:
        (directory / "__init__.py").touch()
    return app


def tail(file: str) -> str:
    """The path under `app/`; outside the working directory the script prints absolute paths."""
    return file.split("/app/", 1)[1]


def layered(report) -> list[str]:
    """Every module.layer place except the root ones, which the __init__.py files always add."""
    return sorted(str(place) for place in report.modules if place.layer != "root")


def measure(files: dict[str, str], layout=None):
    """The report and its text for a scratch package; a Report stays valid after the package is gone."""
    layout = layout or boundaries.Layout()
    with tempfile.TemporaryDirectory() as tmp:
        app = write_package(Path(tmp), files)
        paths = boundaries.collect_files([app], changed=False, base="main")
        report = boundaries.build_report(boundaries.parse_sources(paths, layout), layout)
    return report, boundaries.render_text(report, show_all=False)


CLEAN = {
    "orders/api/orders.py": "from app.orders.services import order_service\n",
    "orders/services/order_service.py": "from app.orders.models.order import Order\n",
    "orders/models/order.py": "from sqlalchemy import Column\n",
    "billing/services/invoice_service.py": "from app.orders.models.order import Order\n",
    "core/config.py": "import os\n",
    "core/main.py": "from app.orders.api import orders\nfrom app.billing.services import invoice_service\n",
}


class CleanTreeTest(unittest.TestCase):
    def test_every_rule_is_zero_and_the_tree_is_still_counted(self):
        report, text = measure(CLEAN)
        rules = {key: value for key, value in report.summary.items() if key not in ("files", "row_files", "modules")}
        self.assertEqual(rules, dict.fromkeys(RULES, 0))
        # six files plus one __init__.py per directory; `app` itself is the fourth module
        self.assertIn("SUMMARY files=14 row_files=14 modules=4 upward=0 cycles=0", text)

    def test_main_py_is_the_composition_root_and_may_import_features(self):
        report, _ = measure(CLEAN)
        self.assertEqual(report.core_outward, [])


class UpwardImportTest(unittest.TestCase):
    def test_service_importing_api_is_one_upward_edge_with_both_files_printed(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "from app.orders.api.orders import router\n"
        report, text = measure(files)
        self.assertEqual(report.summary["upward"], 1)
        self.assertIn("UPWARD (services/models/domain -> api): 1", text)
        self.assertRegex(text, r"\n  \S*orders/services/order_service\.py:1 -> app\.orders\.api\.orders\n")

    def test_importing_the_api_package_by_name_is_upward_too(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "from app.orders import api\nfrom .. import api as api2\n"
        report, _ = measure(files)
        self.assertEqual([(e.line, e.target) for e in report.upward], [(1, "app.orders.api"), (2, "app.orders.api")])

    def test_one_statement_with_two_names_from_one_module_is_one_edge(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "from app.orders.models.order import Order, Line\n"
        report, _ = measure(files)
        self.assertEqual(len([e for e in report.edges if tail(e.file) == "orders/services/order_service.py"]), 1)


class CycleTest(unittest.TestCase):
    CYCLE = dict(CLEAN)
    CYCLE["orders/services/order_service.py"] = (
        "from app.billing.models.invoice import Invoice\nfrom app.billing.services import invoice_service\n"
    )
    CYCLE["billing/models/invoice.py"] = "x = 1\n"

    def test_two_modules_importing_each_other_are_one_cycle(self):
        report, _ = measure(self.CYCLE)
        self.assertEqual(report.summary["cycles"], 1)
        self.assertEqual(report.summary["cyclic_modules"], 2)
        self.assertEqual(report.cyclic_modules, ["billing", "orders"])

    def test_the_rarer_direction_is_printed_as_the_closing_edges(self):
        report, text = measure(self.CYCLE)
        cycle = report.cycles[0]
        self.assertEqual((cycle.forward, cycle.forward_count, cycle.backward_count), (("orders", "billing"), 2, 1))
        self.assertEqual([tail(e.file) for e in cycle.closing], ["billing/services/invoice_service.py"])
        self.assertIn("orders -> billing 2, billing -> orders 1; closing edges:", text)
        self.assertRegex(text, r"\n    \S*billing/services/invoice_service\.py:1 -> app\.orders\.models\.order\n")

    def test_a_tie_lists_both_directions(self):
        files = dict(self.CYCLE)
        files["orders/services/order_service.py"] = "from app.billing.models.invoice import Invoice\n"
        report, _ = measure(files)
        self.assertEqual(len(report.cycles[0].closing), 2)

    def test_a_cycle_through_three_modules_has_no_pair_but_three_cyclic_modules(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "from app.billing.models.invoice import Invoice\n"
        files["billing/services/invoice_service.py"] = "x = 1\n"
        files["billing/models/invoice.py"] = "from app.shipping.models.parcel import Parcel\n"
        files["shipping/models/parcel.py"] = "from app.orders.models.order import Order\n"
        report, _ = measure(files)
        self.assertEqual(report.summary["cycles"], 0)
        self.assertEqual(report.cyclic_modules, ["billing", "orders", "shipping"])

    def test_core_and_the_package_root_are_outside_the_cycle_graph(self):
        files = dict(CLEAN)
        files["core/middleware.py"] = "from app.orders.services import order_service\n"
        files["registry.py"] = "from app.orders.models.order import Order\n"
        files["orders/models/order.py"] = "from app.core.config import x\nfrom app import registry\n"
        report, _ = measure(files)
        self.assertEqual(report.summary["cycles"], 0)
        self.assertEqual(report.summary["core_outward"], 1)
        self.assertEqual(tail(report.core_outward[0].file), "core/middleware.py")


class SqlInApiTest(unittest.TestCase):
    def test_sites_are_statements_so_one_multiline_query_is_one_site(self):
        files = dict(CLEAN)
        files["orders/api/orders.py"] = (
            "from sqlalchemy import select, func\n"
            "async def count(db):\n"
            "    rows = await db.execute(\n"
            "        select(Order.id).where(Order.id > 1)\n"
            "    )\n"
            "    stmt = select(Order)\n"
            "    stmt = stmt.where(Order.id == 1)\n"
            "    total = (await db.execute(select(func.count()))).scalar_one()\n"
            "    return rows, stmt, total\n"
        )
        report, text = measure(files)
        self.assertEqual(report.summary["sql_in_api"], 1)
        self.assertEqual(report.summary["sql_sites"], 4)
        self.assertRegex(text, r"\n      4  \S*orders/api/orders\.py\n")

    def test_a_form_feed_does_not_shift_the_statement_lines(self):
        files = dict(CLEAN)
        files["orders/api/orders.py"] = "x = 1\n\x0c\ndef f(db):\n    return db.execute(q)\n"
        report, _ = measure(files)
        self.assertEqual(report.summary["sql_sites"], 1)

    def test_sql_outside_api_is_not_counted(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "stmt = select(Order).where(Order.id == 1)\n"
        report, _ = measure(files)
        self.assertEqual(report.summary["sql_in_api"], 0)


class FrameworkLeakTest(unittest.TestCase):
    def test_fastapi_in_a_service_is_http_in_services(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "from fastapi import HTTPException\n"
        report, text = measure(files)
        self.assertEqual(report.summary["http_in_services"], 1)
        self.assertRegex(text, r"orders/services/order_service\.py:1 imports fastapi\n")

    def test_http_exception_in_a_comment_is_not_an_import(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "# never raises HTTPException\nx = 1\n"
        report, _ = measure(files)
        self.assertEqual(report.summary["http_in_services"], 0)

    def test_sqlalchemy_under_shared_is_framework_in_domain(self):
        files = dict(CLEAN)
        files["shared/parsers/dates.py"] = "from sqlalchemy import text\n"
        report, text = measure(files)
        self.assertEqual(report.summary["framework_in_domain"], 1)
        self.assertRegex(text, r"shared/parsers/dates\.py:1 imports sqlalchemy\n")

    def test_a_parsers_layer_inside_a_feature_is_checked_too(self):
        files = dict(CLEAN)
        files["orders/parsers/dates.py"] = "from sqlalchemy import text\n"
        report, _ = measure(files)
        self.assertEqual(report.summary["framework_in_domain"], 1)

    def test_a_domain_layer_inside_a_feature_is_checked_too(self):
        files = dict(CLEAN)
        files["orders/domain/pricing.py"] = "from fastapi import Request\n"
        report, _ = measure(files)
        self.assertEqual(report.summary["framework_in_domain"], 1)


class PortsTest(unittest.TestCase):
    def test_protocol_and_abc_classes_under_services_are_ports(self):
        files = dict(CLEAN)
        files["core/services/email/sender.py"] = (
            "from typing import Protocol\nimport abc\n"
            "class EmailSender(Protocol):\n    pass\n"
            "class Storage(abc.ABC):\n    pass\n"
            "class Plain:\n    pass\n"
        )
        report, text = measure(files)
        self.assertEqual([(p.name, p.line) for p in report.ports], [("EmailSender", 3), ("Storage", 5)])
        self.assertRegex(text, r"core/services/email/sender\.py:3 EmailSender\n")


class PlacementTest(unittest.TestCase):
    def test_flat_layout_puts_every_file_in_the_package_module(self):
        files = {
            "api/users.py": "from app.services import user_service\n",
            "services/user_service.py": "from app.api.users import router\n",
        }
        report, _ = measure(files)
        self.assertEqual(layered(report), ["app.api", "app.services"])
        self.assertEqual(report.summary["upward"], 1)

    def test_a_directory_that_is_no_layer_is_root_not_dropped(self):
        report, _ = measure(CLEAN | {"orders/tasks/nightly.py": "x = 1\n"})
        nightly = [s.place for s in report.sources if s.path.name == "nightly.py"]
        self.assertEqual(nightly, [boundaries.Place("orders", "root")])

    def test_relative_imports_resolve_against_the_file_package(self):
        files = dict(CLEAN)
        files["orders/services/order_service.py"] = "from ..api import orders\nfrom . import helpers\n"
        files["orders/services/helpers.py"] = "x = 1\n"
        report, _ = measure(files)
        self.assertEqual([e.target for e in report.upward], ["app.orders.api"])

    def test_layers_flag_renames_the_layers(self):
        files = {
            "orders/routes/orders.py": "x = 1\n",
            "orders/logic/order_service.py": "from app.orders.routes.orders import router\n",
        }
        custom = boundaries.Layout(layers=frozenset({"routes", "logic"}))
        report, _ = measure(files, layout=custom)
        self.assertEqual(layered(report), ["orders.logic", "orders.routes"])
        self.assertEqual(report.summary["upward"], 0)


class ChangedRowsTest(unittest.TestCase):
    def test_changed_narrows_rows_but_not_cycles(self):
        files = dict(CycleTest.CYCLE)
        files["core/middleware.py"] = "from app.orders.services import order_service\n"
        with tempfile.TemporaryDirectory() as tmp:
            app = write_package(Path(tmp), files)
            paths = boundaries.collect_files([app], changed=False, base="main")
            sources = boundaries.parse_sources(paths, boundaries.Layout())
            changed = {(app / "billing" / "models" / "invoice.py").resolve()}
            report = boundaries.build_report(sources, boundaries.Layout(), changed)
        self.assertEqual(report.summary["row_files"], 1)
        self.assertEqual(report.summary["core_outward"], 0)
        self.assertEqual(report.summary["cycles"], 1)


class JsonTest(unittest.TestCase):
    def test_json_carries_rows_layout_and_summary(self):
        report, _ = measure(CycleTest.CYCLE)
        data = json.loads(boundaries.render_json(report))
        self.assertEqual(data["layout"]["layers"], ["api", "domain", "models", "parsers", "schemas", "services"])
        self.assertEqual(data["cycles"][0]["modules"], ["orders", "billing"])
        self.assertEqual(tail(data["cycles"][0]["closing"][0]["file"]), "billing/services/invoice_service.py")
        self.assertEqual(data["summary"]["cycles"], 1)
        self.assertIn({"from": "orders", "to": "billing", "imports": 2}, data["module_edges"])


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_measures_a_package_and_exits_zero_even_when_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = write_package(Path(tmp), CycleTest.CYCLE)
            proc = self.run_cli(str(app))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SUMMARY files=16 row_files=16 modules=4 upward=0 cycles=1", proc.stdout)

    def test_all_lists_modules_and_module_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = write_package(Path(tmp), CLEAN)
            proc = self.run_cli(str(app), "--all")
        self.assertIn("MODULES (files per module and layer)", proc.stdout)
        self.assertIn("billing -> orders", proc.stdout)

    def test_a_relative_path_inside_the_package_terminates(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = write_package(Path(tmp), CLEAN)
            proc = subprocess.run([sys.executable, str(SCRIPT), "."], cwd=app, capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SUMMARY files=14", proc.stdout)

    def test_a_package_without_init_files_is_reported_on_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            (app / "orders" / "services").mkdir(parents=True)
            (app / "orders" / "services" / "s.py").write_text("from app.orders.api import o\n")
            proc = self.run_cli(str(app))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("upward=0", proc.stdout)
        self.assertIn("__init__.py", proc.stderr)

    def test_two_packages_in_one_run_is_a_broken_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = write_package(Path(tmp), CLEAN)
            tests = Path(tmp) / "tests"
            tests.mkdir()
            (tests / "__init__.py").touch()
            (tests / "test_orders.py").write_text("import fastapi\n")
            proc = self.run_cli(str(app), str(tests))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("One package per run", proc.stderr)

    def test_typescript_is_a_broken_run_that_names_the_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.ts").write_text("export const x = 1;\n")
            proc = self.run_cli(tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("dependency-cruiser", proc.stderr)

    def test_unparsable_python_exits_two_with_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "broken.py").write_text("def broken(:\n")
            proc = self.run_cli(tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot parse", proc.stderr)

    def test_no_files_is_reported_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("no Python files to measure", proc.stdout)

    def test_empty_layers_flag_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp, "--layers", ",")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("comma-separated", proc.stderr)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
