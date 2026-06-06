"""Regression tests for extracting connector contracts from core.connectors._base."""
from pathlib import Path
import sys
import types


class _StructlogStub(types.SimpleNamespace):
    def get_logger(self, *_args, **_kwargs):
        return types.SimpleNamespace(
            debug=lambda *_a, **_k: None,
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )


def _install_structlog_stub():
    sys.modules.setdefault("structlog", _StructlogStub())


def test_connector_contracts_have_dedicated_module_with_base_compatibility():
    _install_structlog_stub()
    from core.connectors import _base
    from core.connectors import contracts

    assert _base.ConnectorSpec is contracts.ConnectorSpec
    assert _base.ConnectorResult is contracts.ConnectorResult

    source = Path("core/connectors/_base.py").read_text(encoding="utf-8")
    assert "class ConnectorSpec" not in source
    assert "class ConnectorResult" not in source


def test_connector_contract_serialization_stays_compatible():
    _install_structlog_stub()
    from core.connectors.contracts import ConnectorResult, ConnectorSpec

    result = ConnectorResult(success=True, data={"x": 1}, latency_ms=12.5, connector="demo")
    result_dict = result.to_dict()
    assert result_dict["ok"] is True
    assert result_dict["success"] is True
    assert result_dict["data"] == {"x": 1}
    assert result_dict["result"] == "{'x': 1}"
    assert result_dict["output"] == "{'x': 1}"

    spec = ConnectorSpec(
        name="demo",
        category="data",
        description="Demo connector",
        input_schema={"x": "int"},
        output_schema={"ok": "bool"},
    )
    spec_dict = spec.to_dict()
    assert spec_dict["name"] == "demo"
    assert spec_dict["retry_compatible"] is True
    assert spec_dict["failure_modes"] == []


def test_connector_runtime_has_dedicated_module_with_base_compatibility():
    _install_structlog_stub()
    from core.connectors import _base
    from core.connectors import runtime

    assert _base.execute_connector is runtime.execute_connector
    assert _base._sanitize_connector_params is runtime._sanitize_connector_params
    assert _base._audit_connector_execution is runtime._audit_connector_execution

    missing = runtime.execute_connector("missing", {})
    assert missing.success is False
    assert "not found" in missing.error

    clean, warnings = runtime._sanitize_connector_params("demo", {"body": "x" * 100_005})
    assert len(clean["body"]) == 100_000
    assert "truncated:body" in warnings

    source = Path("core/connectors/_base.py").read_text(encoding="utf-8")
    assert "def execute_connector" not in source
    assert "def _sanitize_connector_params" not in source
    assert "def _audit_connector_execution" not in source


def test_business_connectors_have_dedicated_module_with_base_compatibility():
    _install_structlog_stub()
    from core.connectors import _base
    from core.connectors import business

    exported = [
        "LEAD_MANAGER_SPEC",
        "lead_manager_connector",
        "CONTENT_MANAGER_SPEC",
        "content_manager_connector",
        "BUDGET_CONNECTOR_SPEC",
        "budget_connector",
        "WORKFLOW_TRIGGER_SPEC",
        "workflow_trigger_connector",
        "SCHEDULER_SPEC",
        "scheduler_connector",
        "WEB_SCRAPE_SPEC",
        "web_scrape_connector",
        "FILE_EXPORT_SPEC",
        "file_export_connector",
    ]
    for name in exported:
        assert getattr(_base, name) is getattr(business, name)

    assert _base.CONNECTOR_REGISTRY["lead_manager"]["execute"] is business.lead_manager_connector
    assert _base.CONNECTOR_REGISTRY["file_export"]["spec"] is business.FILE_EXPORT_SPEC

    source = Path("core/connectors/_base.py").read_text(encoding="utf-8")
    assert "def lead_manager_connector" not in source
    assert "def file_export_connector" not in source
    assert "LEAD_MANAGER_SPEC = ConnectorSpec" not in source
    assert "FILE_EXPORT_SPEC = ConnectorSpec" not in source
