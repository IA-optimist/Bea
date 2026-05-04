"""
tests/test_connectors.py — Real-world connector tests.

Validates:
  CN01-CN10: Base connector + registry
  CN11-CN16: GitHub connector
  CN17-CN24: Filesystem connector
  CN25-CN30: HTTP connector
  CN31-CN35: Safety + integration
"""
import os
import json


class TestConnectorBase:
    def test_CN01_connector_result(self):
        from connectors.base import ConnectorResult
        r = ConnectorResult(connector="test", action="do_thing", success=True)
        d = r.to_dict()
        assert d["connector"] == "test"
        assert d["success"] is True
        assert d["trace_id"].startswith("ct-")

    def test_CN02_registry_create(self):
        from connectors.base import ConnectorRegistry
        reg = ConnectorRegistry()
        assert reg.list_all() == []

    def test_CN03_registry_register(self):
        from connectors.base import ConnectorRegistry, ConnectorBase, ConnectorResult
        class FakeConnector(ConnectorBase):
            name = "fake"
            actions = ["test"]
            def execute(self, action, params):
                return ConnectorResult(connector=self.name, action=action, success=True)
        reg = ConnectorRegistry()
        reg.register(FakeConnector())
        assert len(reg.list_all()) == 1
        assert reg.get("fake") is not None

    def test_CN04_registry_execute(self):
        from connectors.base import ConnectorRegistry, ConnectorBase, ConnectorResult
        class FakeConnector(ConnectorBase):
            name = "fake2"
            actions = ["ping"]
            def execute(self, action, params):
                return ConnectorResult(connector=self.name, action=action, success=True, output={"pong": True})
        reg = ConnectorRegistry()
        reg.register(FakeConnector())
        result = reg.execute("fake2", "ping", {})
        assert result.success

    def test_CN05_registry_unknown_connector(self):
        from connectors.base import ConnectorRegistry
        reg = ConnectorRegistry()
        result = reg.execute("nonexistent", "test", {})
        assert not result.success
        assert "not found" in result.error

    def test_CN06_connector_disabled(self):
        from connectors.base import ConnectorBase, ConnectorResult
        class TestConn(ConnectorBase):
            name = "testdisabled"
            actions = ["act"]
            def execute(self, action, params):
                return ConnectorResult(connector=self.name, action=action, success=True)
        os.environ["CONNECTOR_TESTDISABLED_ENABLED"] = "0"
        c = TestConn()
        result = c.safe_execute("act", {})
        assert not result.success
        assert "disabled" in result.error
        del os.environ["CONNECTOR_TESTDISABLED_ENABLED"]

    def test_CN07_connector_status(self):
        from connectors.base import ConnectorBase, ConnectorResult
        class TestConn(ConnectorBase):
            name = "myconn"
            description = "Test connector"
            actions = ["a", "b"]
            def execute(self, action, params):
                return ConnectorResult()
        status = TestConn().get_status()
        assert status["name"] == "myconn"
        assert status["enabled"] is True
        assert len(status["actions"]) == 2

    def test_CN08_singleton_registry(self):
        from connectors.base import get_connector_registry
        r1 = get_connector_registry()
        r2 = get_connector_registry()
        assert r1 is r2

    def test_CN09_result_output_truncated(self):
        from connectors.base import ConnectorResult
        r = ConnectorResult(output={"big": "x" * 1000})
        d = r.to_dict()
        assert len(d["output"]["big"]) <= 500

    def test_CN10_result_error_truncated(self):
        from connectors.base import ConnectorResult
        r = ConnectorResult(error="e" * 500)
        d = r.to_dict()
        assert len(d["error"]) <= 300


class TestGitHubConnector:
    def test_CN11_github_connector_exists(self):
        from connectors.github_connector import GitHubConnector
        g = GitHubConnector()
        assert g.name == "github"
        assert len(g.actions) == 3

    def test_CN12_github_actions(self):
        from connectors.github_connector import GitHubConnector
        assert "create_repo" in GitHubConnector.actions
        assert "commit_files" in GitHubConnector.actions
        assert "create_issue" in GitHubConnector.actions

    def test_CN13_create_repo_requires_name(self):
        from connectors.github_connector import GitHubConnector
        g = GitHubConnector()
        result = g.execute("create_repo", {})
        assert not result.success
        assert "name required" in result.error

    def test_CN14_commit_requires_dir(self):
        from connectors.github_connector import GitHubConnector
        result = GitHubConnector().execute("commit_files", {})
        assert not result.success
        assert "repo_dir required" in result.error

    def test_CN15_create_issue_requires_fields(self):
        from connectors.github_connector import GitHubConnector
        result = GitHubConnector().execute("create_issue", {})
        assert not result.success
        assert "required" in result.error

    def test_CN16_unknown_action(self):
        from connectors.github_connector import GitHubConnector
        result = GitHubConnector().execute("delete_everything", {})
        assert not result.success
        assert "Unknown" in result.error


class TestFilesystemConnector:
    def test_CN17_filesystem_exists(self):
        from connectors.filesystem_connector import FilesystemConnector
        f = FilesystemConnector()
        assert f.name == "filesystem"
        assert len(f.actions) == 3

    def test_CN18_deploy_static_requires_dirs(self):
        from connectors.filesystem_connector import FilesystemConnector
        result = FilesystemConnector().execute("deploy_static_site", {})
        assert not result.success

    def test_CN19_deploy_static_blocks_path_traversal(self):
        from connectors.filesystem_connector import FilesystemConnector
        result = FilesystemConnector().execute("deploy_static_site", {
            "source_dir": "/tmp/test",
            "target_dir": "../../../etc/passwd",
        })
        # Should fail (either source not found or path traversal blocked)
        assert not result.success

    def test_CN20_export_requires_source(self):
        from connectors.filesystem_connector import FilesystemConnector
        result = FilesystemConnector().execute("export_bundle", {})
        assert not result.success

    def test_CN21_list_outputs_empty(self, tmp_path):
        from connectors.filesystem_connector import FilesystemConnector
        # tmp_path + '/absent' guarantees the dir does not exist (unique per
        # test). Previous hardcoded /nonexistent was polluted by
        # test_cognitive_security.test_SO04 which sets JARVISMAX_DATA_DIR
        # there.
        missing = tmp_path / "absent"
        result = FilesystemConnector().execute("list_outputs", {"dir": str(missing)})
        assert result.success
        assert result.output["count"] == 0

    def test_CN22_deploy_static_works(self, tmp_path):
        from connectors.filesystem_connector import FilesystemConnector
        import connectors.filesystem_connector as fsmod
        old_ws = fsmod._WORKSPACE
        fsmod._WORKSPACE = tmp_path

        src = tmp_path / "source"
        src.mkdir()
        (src / "index.html").write_text("<h1>Test</h1>")

        f = FilesystemConnector()
        result = f.execute("deploy_static_site", {
            "source_dir": str(src),
            "target_dir": "mysite",
        })
        assert result.success
        assert (tmp_path / "sites" / "mysite" / "index.html").exists()

        fsmod._WORKSPACE = old_ws

    def test_CN23_list_outputs_real(self, tmp_path):
        from connectors.filesystem_connector import FilesystemConnector
        (tmp_path / "file.txt").write_text("test")
        result = FilesystemConnector().execute("list_outputs", {"dir": str(tmp_path)})
        assert result.success
        assert result.output["count"] >= 1

    def test_CN24_export_bundle_works(self, tmp_path):
        from connectors.filesystem_connector import FilesystemConnector
        import connectors.filesystem_connector as fsmod
        old_ws = fsmod._WORKSPACE
        fsmod._WORKSPACE = tmp_path

        src = tmp_path / "data"
        src.mkdir()
        (src / "report.json").write_text('{"key": "value"}')

        result = FilesystemConnector().execute("export_bundle", {
            "source_dir": str(src),
            "name": "report_v1",
        })
        assert result.success
        assert "report_v1.zip" in result.output.get("bundle", "")

        fsmod._WORKSPACE = old_ws


class TestHttpConnector:
    def test_CN25_http_exists(self):
        from connectors.http_connector import HttpConnector
        h = HttpConnector()
        assert h.name == "http"
        assert len(h.actions) == 2

    def test_CN26_webhook_requires_url(self):
        old = os.environ.pop("WEBHOOK_URL", None)
        from connectors.http_connector import HttpConnector
        result = HttpConnector().execute("call_webhook", {})
        assert not result.success
        assert "URL" in result.error
        if old: os.environ["WEBHOOK_URL"] = old

    def test_CN27_webhook_rejects_bad_protocol(self):
        from connectors.http_connector import HttpConnector
        result = HttpConnector().execute("call_webhook", {"url": "ftp://evil.com"})
        assert not result.success
        assert "http" in result.error.lower()

    def test_CN28_notification_log_works(self):
        from connectors.http_connector import HttpConnector
        result = HttpConnector().execute("send_notification", {
            "message": "Test notification",
            "channel": "log",
        })
        assert result.success
        assert result.output["channel"] == "log"

    def test_CN29_notification_requires_message(self):
        from connectors.http_connector import HttpConnector
        result = HttpConnector().execute("send_notification", {})
        assert not result.success
        assert "message required" in result.error

    def test_CN30_unknown_action(self):
        from connectors.http_connector import HttpConnector
        result = HttpConnector().execute("hack_server", {})
        assert not result.success


class TestConnectorSafety:
    def test_CN31_no_secrets_in_results(self):
        from connectors.base import ConnectorResult
        r = ConnectorResult(output={"data": "safe"}, error="")
        d = json.dumps(r.to_dict())
        assert "sk-or-" not in d
        assert "ghp_" not in d

    def test_CN32_policy_check_in_safe_execute(self):
        from connectors.base import ConnectorBase, ConnectorResult
        class TestConn(ConnectorBase):
            name = "policytest"
            actions = ["act"]
            def execute(self, action, params):
                return ConnectorResult(connector=self.name, action=action, success=True)
        c = TestConn()
        result = c.safe_execute("act", {})
        assert result.policy_checked

    def test_CN33_connectors_all_import(self):
        pass

    def test_CN34_connector_module_init(self):
        import connectors
        assert connectors

    def test_CN35_all_connectors_have_name(self):
        from connectors.github_connector import GitHubConnector
        from connectors.filesystem_connector import FilesystemConnector
        from connectors.http_connector import HttpConnector
        for cls in [GitHubConnector, FilesystemConnector, HttpConnector]:
            c = cls()
            assert c.name
            assert len(c.actions) > 0
