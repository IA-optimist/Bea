"""
HexStrike Cache Router — Flask Blueprint for /api/cache endpoints.

Extrait depuis hexstrike_server.py. Monté via app.register_blueprint(cache_bp).
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from flask import Blueprint, request, jsonify

from hex_cache import cache

logger = logging.getLogger("hexstrike_server")

cache_bp = Blueprint("cache", __name__, url_prefix="/api/cache")



@cache_bp.route("/stats", methods=["GET"])
def cache_stats():
    """Get cache statistics"""
    return jsonify(cache.get_stats())


@cache_bp.route("/clear", methods=["POST"])
def clear_cache():
    """Clear the cache"""
    cache.cache.clear()
    cache.stats = {"hits": 0, "misses": 0, "evictions": 0}
    logger.info("🧹 Cache cleared")
    return jsonify({"success": True, "message": "Cache cleared"})


__all__ = ["cache_bp"]
