"""
agent_runtime/results.py - Result helpers and built-in safe handlers.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from agent_runtime.actions import ActionRequest, ActionResult, redact_text


def not_implemented_handler(request: ActionRequest) -> ActionResult:
    """Stub handler for actions registered but not yet wired to a real backend."""
    return ActionResult.error_result(
        request.action_id,
        f"action '{request.action_type.value}' handler not implemented - wire a real backend",
    )


def write_report_handler(request: ActionRequest) -> ActionResult:
    path = request.payload.get("path")
    content = request.payload.get("content", "")
    if not path:
        return ActionResult.blocked(request.action_id, "WRITE_REPORT requires payload.path")
    target = Path(str(path)).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(redact_text(str(content)) or "", encoding="utf-8")
    return ActionResult.success(
        request.action_id,
        {"path": str(target), "bytes": target.stat().st_size},
        artifacts=[str(target)],
    )


def apply_patch_handler(request: ActionRequest) -> ActionResult:
    patch = str(request.payload.get("patch", ""))
    target_raw = request.payload.get("target") or request.payload.get("path")
    if not target_raw:
        return ActionResult.blocked(request.action_id, "APPLY_PATCH requires payload.target")
    if not patch.strip():
        return ActionResult.blocked(request.action_id, "empty patch blocked")
    if len(patch.encode("utf-8")) > 200_000:
        return ActionResult.blocked(request.action_id, "patch too large")

    target = Path(str(target_raw)).resolve()
    workspace = target.parent
    parsed = _parse_single_update_patch(patch)
    if parsed is None:
        return ActionResult.error_result(request.action_id, "unsupported or malformed patch")
    patch_path, old_text, new_text = parsed
    if Path(patch_path).is_absolute() or ".." in Path(patch_path).parts:
        return ActionResult.blocked(request.action_id, "patch path traversal blocked")

    file_path = (workspace / patch_path).resolve()
    if file_path != target:
        return ActionResult.blocked(request.action_id, "patch target does not match payload.target")
    if not file_path.exists():
        return ActionResult.error_result(request.action_id, f"target file not found: {file_path}")

    before = file_path.read_text(encoding="utf-8")
    if old_text not in before:
        return ActionResult.error_result(request.action_id, "patch context not found")
    after = before.replace(old_text, new_text, 1)
    before_hash = hashlib.sha256(before.encode("utf-8")).hexdigest()
    after_hash = hashlib.sha256(after.encode("utf-8")).hexdigest()
    file_path.write_text(after, encoding="utf-8")
    return ActionResult.success(
        request.action_id,
        {
            "diff_summary": {
                "changed_files": [str(file_path)],
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "lines_removed": old_text.count("\n"),
                "lines_added": new_text.count("\n"),
            }
        },
        artifacts=[str(file_path)],
    )


def _parse_single_update_patch(patch: str) -> tuple[str, str, str] | None:
    lines = patch.splitlines()
    update_file: str | None = None
    old_lines: list[str] = []
    new_lines: list[str] = []
    in_hunk = False
    for line in lines:
        if line.startswith("*** Update File: "):
            update_file = line.removeprefix("*** Update File: ").strip()
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if line.startswith("*** End Patch"):
            break
        if not in_hunk:
            continue
        if line.startswith("-"):
            old_lines.append(line[1:])
        elif line.startswith("+"):
            new_lines.append(line[1:])
        elif line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
    if not update_file or not old_lines:
        return None
    return update_file, "\n".join(old_lines) + "\n", "\n".join(new_lines) + "\n"
