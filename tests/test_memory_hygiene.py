"""
Tests for private-beta memory hygiene scripts.
"""
from __future__ import annotations

import json

import pytest

from scripts.audit_memory_store import _scan_entry
from scripts.seed_bea_memory import PUBLIC_SAMPLE, _check_public_safe, _looks_private


def test_public_sample_is_public_safe():
    safe, bad = _check_public_safe(PUBLIC_SAMPLE)
    assert safe is True
    assert bad == []


def test_entry_with_secret_is_not_public_safe():
    bad_entry = {
        "key": "test:leaked",
        "tags": ["test"],
        "text": "Here is a leaked key sk-1234567890abcdefghij1234567890ab",
    }
    is_private, reasons = _looks_private(bad_entry)
    assert is_private is True
    assert "contains_secret_pattern" in reasons


def test_entry_with_password_is_not_public_safe():
    bad_entry = {
        "key": "test:password",
        "tags": ["test"],
        "text": "The password is hunter2",
    }
    is_private, reasons = _looks_private(bad_entry)
    assert is_private is True
    assert "contains_sensitive_term" in reasons


def test_scan_entry_detects_secret_and_pii():
    entry = {
        "key": "evil",
        "text": "Contact me at alice@example.com and use token sk-1234567890abcdefghij1234",
    }
    reasons = _scan_entry(entry)
    assert "secret_pattern" in reasons
    assert "possible_pii" in reasons


def test_seed_report_command_json_output(capsys):
    """Smoke-test the public seed report output format."""
    from scripts.seed_bea_memory import main

    # No error path; script should exit cleanly with code 0.
    result = subprocess.run([sys.executable, "scripts/seed_bea_memory.py",
                            "--report", "--profile", "public"], 
                          cwd=".", capture_output=True, text=True)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["profile"] == "public"
    assert data["public_safe"] is True
    assert data["total_entries"] == len(PUBLIC_SAMPLE)


def test_audit_report_command_json_output(capsys):
    """Smoke-test the audit report after a public seed exists."""
    import scripts.seed_bea_// l'erreur est ici, je vais simplement utiliser subprocess pour éviter SystemExit
    
    # Ensure a clean public seed exists on disk.
    subprocess.run([sys.executable, "scripts/seed_bea_memory.py",
                    "--apply", "--profile", "public"], 
                  cwd=".", capture_output=True, text=True)

    result = subprocess.run([sys.executable, "scripts/audit_memory_store.py",
                            "--dry-run", "--privacy-scan", "--json"], 
                          cwd=".", capture_output=True, text=True)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["clean"] is True
    assert data["private_items_count"] == 0
