"""Tests for core.security.url_guard.validate_outbound_url."""
from __future__ import annotations

import pytest

from core.security.url_guard import validate_outbound_url


class TestValidUrls:
    def test_accepts_https(self):
        assert validate_outbound_url("https://example.com") == "https://example.com"

    def test_accepts_http(self):
        assert validate_outbound_url("http://example.com") == "http://example.com"

    def test_strips_whitespace(self):
        result = validate_outbound_url("  https://example.com  ")
        assert result == "https://example.com"

    def test_accepts_https_with_path(self):
        assert validate_outbound_url("https://example.com/api/v1/missions") == "https://example.com/api/v1/missions"

    def test_accepts_https_with_port(self):
        assert validate_outbound_url("https://example.com:8443/api") == "https://example.com:8443/api"


class TestInvalidUrls:
    def test_refuses_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_outbound_url("")

    def test_refuses_whitespace_only(self):
        with pytest.raises(ValueError, match="empty"):
            validate_outbound_url("   ")

    def test_refuses_file_scheme(self):
        with pytest.raises(ValueError, match="not allowed|blocked"):
            validate_outbound_url("file:///etc/passwd")

    def test_refuses_ftp_scheme(self):
        with pytest.raises(ValueError, match="not allowed|blocked"):
            validate_outbound_url("ftp://example.com/file")

    def test_refuses_data_scheme(self):
        with pytest.raises(ValueError, match="not allowed|blocked"):
            validate_outbound_url("data:text/html,<script>alert(1)</script>")

    def test_refuses_javascript_scheme(self):
        with pytest.raises(ValueError, match="not allowed|blocked"):
            validate_outbound_url("javascript:alert(1)")

    def test_refuses_no_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_outbound_url("example.com/path")

    def test_refuses_no_host(self):
        with pytest.raises(ValueError, match="host"):
            validate_outbound_url("https:///path")


class TestLocalhostBlocking:
    def test_refuses_localhost_by_default(self):
        with pytest.raises(ValueError, match="localhost"):
            validate_outbound_url("http://localhost:8000/health")

    def test_refuses_127_by_default(self):
        with pytest.raises(ValueError, match="localhost"):
            validate_outbound_url("http://127.0.0.1:8000/health")

    def test_accepts_localhost_with_flag(self):
        result = validate_outbound_url("http://localhost:8000/health", allow_localhost=True)
        assert result == "http://localhost:8000/health"

    def test_accepts_127_with_flag(self):
        result = validate_outbound_url("http://127.0.0.1:8000/health", allow_localhost=True)
        assert result == "http://127.0.0.1:8000/health"


class TestMetadataBlocking:
    def test_refuses_aws_metadata(self):
        with pytest.raises(ValueError, match="metadata"):
            validate_outbound_url("http://169.254.169.254/latest/meta-data/")

    def test_refuses_gcp_metadata(self):
        with pytest.raises(ValueError, match="metadata"):
            validate_outbound_url("http://metadata.google.internal/computeMetadata/v1/")

    def test_refuses_metadata_even_with_localhost_flag(self):
        """Metadata endpoints must be blocked even when allow_localhost=True."""
        with pytest.raises(ValueError, match="metadata"):
            validate_outbound_url("http://169.254.169.254/latest/meta-data/", allow_localhost=True)


class TestAllowedHosts:
    def test_whitelist_accepts_allowed(self):
        result = validate_outbound_url(
            "https://api.example.com/v1",
            allowed_hosts={"api.example.com"},
        )
        assert result == "https://api.example.com/v1"

    def test_whitelist_rejects_unlisted(self):
        with pytest.raises(ValueError, match="not in the allowed"):
            validate_outbound_url(
                "https://evil.com/v1",
                allowed_hosts={"api.example.com"},
            )
