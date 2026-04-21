"""
connectors/filesystem_connector.py — Safe filesystem operations.

Actions:
  deploy_static_site: Copy built artifacts to deployment directory
  export_bundle: Create a ZIP/tar export of workspace artifacts
  list_outputs: List available output files
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from .base import ConnectorBase, ConnectorResult

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))


class FilesystemConnector(ConnectorBase):
    name = "filesystem"
    description = "Safe workspace filesystem operations"
    actions = ["deploy_static_site", "export_bundle", "list_outputs"]

    def execute(self, action: str, params: dict) -> ConnectorResult:
        result = ConnectorResult(connector=self.name, action=action)

        if action == "deploy_static_site":
            return self._deploy_static(params, result)
        elif action == "export_bundle":
            return self._export_bundle(params, result)
        elif action == "list_outputs":
            return self._list_outputs(params, result)
        else:
            result.error = f"Unknown action: {action}"
            return result

    def _deploy_static(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        source = params.get("source_dir", "")
        target = params.get("target_dir", "")

        if not source or not target:
            result.error = "source_dir and target_dir required"
            return result

        src = Path(source)
        tgt = _WORKSPACE / "sites" / target

        # Safety: must be under workspace
        try:
            tgt.resolve().relative_to(_WORKSPACE.resolve())
        except ValueError:
            result.error = "target_dir must be under workspace"
            return result

        if not src.exists():
            result.error = f"source_dir does not exist: {source}"
            return result

        try:
            tgt.mkdir(parents=True, exist_ok=True)
            copied = 0
            for item in src.iterdir():
                if item.is_file():
                    shutil.copy2(str(item), str(tgt / item.name))
                    copied += 1
                elif item.is_dir():
                    shutil.copytree(str(item), str(tgt / item.name), dirs_exist_ok=True)
                    copied += 1

            result.success = True
            result.output = {"target": str(tgt), "files_copied": copied}
        except Exception as e:
            result.error = str(e)[:200]

        return result

    def _export_bundle(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        source = params.get("source_dir", "")
        bundle_name = params.get("name", "export")

        if not source:
            result.error = "source_dir required"
            return result

        src = Path(source)
        if not src.exists():
            result.error = f"Source not found: {source}"
            return result

        export_dir = _WORKSPACE / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        output_path = export_dir / bundle_name

        try:
            shutil.make_archive(str(output_path), "zip", str(src))
            result.success = True
            result.output = {"bundle": str(output_path) + ".zip"}
        except Exception as e:
            result.error = str(e)[:200]

        return result

    def _list_outputs(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        search_dir = params.get("dir", str(_WORKSPACE / "builds"))
        p = Path(search_dir)
        if not p.exists():
            result.output = {"files": [], "count": 0}
            result.success = True
            return result

        files = []
        for item in sorted(p.iterdir()):
            files.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            })
        result.success = True
        result.output = {"files": files[:50], "count": len(files)}
        return result
