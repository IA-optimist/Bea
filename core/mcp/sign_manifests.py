"""Sign MCP tool manifests."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Add parent directory to path for imports.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.mcp.manifest_schema import ToolManifest


def sign_all_manifests(manifests_dir: Path) -> None:
    """Sign all manifest files in the given directory."""
    for manifest_file in manifests_dir.glob("*.json"):
        logger.info("mcp_manifest_sign_start", manifest=manifest_file.name)
        try:
            content = manifest_file.read_text(encoding="utf-8")
            manifest = ToolManifest.from_json(content)
            manifest.sign()
            manifest_file.write_text(manifest.to_json(), encoding="utf-8")
            logger.info("mcp_manifest_sign_success", manifest=manifest_file.name)
        except Exception as exc:
            logger.exception(
                "mcp_manifest_sign_failed",
                manifest=manifest_file.name,
                error=str(exc),
            )


if __name__ == "__main__":
    manifests_dir = Path(__file__).parent / "manifests"
    sign_all_manifests(manifests_dir)
    logger.info("mcp_manifest_sign_complete", manifests_dir=str(manifests_dir))
