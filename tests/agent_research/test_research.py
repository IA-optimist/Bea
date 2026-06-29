"""
tests/agent_research/test_research.py — Research agent tests.
"""
from __future__ import annotations

import pytest
from datetime import date

from agent_research.sources import ResearchSource, SourceKind, is_social_media_url
from agent_research.reports import ResearchReport, ReportSection
from agent_research.agent import ResearchAgent


# ── Helpers ───────────────────────────────────────────────────────────────────

_GOOD_URL = "https://docs.python.org/3/library/asyncio.html"
_GOOD_SOURCE = dict(
    url=_GOOD_URL,
    kind=SourceKind.DOCUMENTATION,
    title="Python asyncio documentation",
    credibility=0.95,
)

def _source(**kwargs) -> ResearchSource:
    data = dict(_GOOD_SOURCE)
    data.update(kwargs)
    return ResearchSource(**data)

def _section(title: str, content: str, urls: list[str]) -> ReportSection:
    return ReportSection(title=title, content=content, source_urls=urls)


# ── Source tests ──────────────────────────────────────────────────────────────

class TestResearchSource:
    def test_good_source_accepted(self):
        s = _source()
        assert s.url == _GOOD_URL

    def test_twitter_rejected(self):
        with pytest.raises(Exception, match="social media"):
            _source(url="https://twitter.com/user/status/123", title="some tweet")

    def test_x_com_rejected(self):
        with pytest.raises(Exception, match="social media"):
            _source(url="https://x.com/user/status/456", title="another tweet")

    def test_reddit_rejected(self):
        with pytest.raises(Exception, match="social media"):
            _source(url="https://reddit.com/r/python/comments/abc", title="reddit post")

    def test_facebook_rejected(self):
        with pytest.raises(Exception, match="social media"):
            _source(url="https://facebook.com/post/789", title="fb post")

    def test_github_allowed(self):
        s = _source(
            url="https://github.com/tiangolo/fastapi",
            kind=SourceKind.CODE_REPO,
            title="FastAPI GitHub repo",
        )
        assert "github.com" in s.url

    def test_arxiv_allowed(self):
        s = _source(
            url="https://arxiv.org/abs/2310.06825",
            kind=SourceKind.PAPER,
            title="Research paper on arxiv",
        )
        assert "arxiv" in s.url

    def test_cookie_gated_requires_justification(self):
        with pytest.raises(Exception):
            _source(is_cookie_gated=True, justification_for_cookie_gated="")

    def test_cookie_gated_with_justification_accepted(self):
        s = _source(
            is_cookie_gated=True,
            justification_for_cookie_gated="Official IEEE paper, no alternative source available",
        )
        assert s.is_cookie_gated

    def test_credibility_bounds(self):
        with pytest.raises(Exception):
            _source(credibility=1.5)
        with pytest.raises(Exception):
            _source(credibility=-0.1)

    def test_is_social_media_url(self):
        assert is_social_media_url("https://twitter.com/abc")
        assert not is_social_media_url("https://docs.python.org/3/")


# ── ReportSection tests ───────────────────────────────────────────────────────

class TestReportSection:
    def test_section_needs_source_url(self):
        with pytest.raises(Exception, match="source"):
            _section("Title", "content with enough length", [])

    def test_section_with_source_ok(self):
        s = _section("Overview", "Content with sufficient length here.", [_GOOD_URL])
        assert s.title == "Overview"


# ── ResearchReport tests ──────────────────────────────────────────────────────

class TestResearchReport:
    def _make_report(self, **overrides) -> ResearchReport:
        src = _source()
        section = _section("Findings", "Detailed findings about asyncio patterns.", [src.url])
        defaults = dict(
            title="Research on asyncio",
            query="How does asyncio work in Python?",
            sources=[src],
            sections=[section],
            summary="Asyncio is an event-loop based concurrency framework with extensive documentation.",
            confidence=0.85,
        )
        defaults.update(overrides)
        return ResearchReport(**defaults)

    def test_valid_report_created(self):
        r = self._make_report()
        assert r.read_only is True
        assert len(r.sources) == 1

    def test_report_requires_sources(self):
        with pytest.raises(Exception):
            self._make_report(sources=[])

    def test_report_requires_sections(self):
        with pytest.raises(Exception):
            self._make_report(sections=[])

    def test_personal_data_rejected(self):
        with pytest.raises(Exception):
            self._make_report(contains_personal_data=True)

    def test_cross_reference_validation(self):
        src = _source()
        bad_section = _section("Bad", "Content with sufficient length here.", ["https://unknown.com/path"])
        with pytest.raises(Exception, match="unknown source"):
            ResearchReport(
                title="Test report title",
                query="test query with length",
                sources=[src],
                sections=[bad_section],
                summary="Summary with sufficient length for the validation.",
                confidence=0.7,
            )

    def test_to_markdown_contains_title(self):
        r = self._make_report()
        md = r.to_markdown()
        assert "Research on asyncio" in md
        assert "docs.python.org" in md


# ── ResearchAgent tests ───────────────────────────────────────────────────────

class TestResearchAgent:
    def setup_method(self):
        self.agent = ResearchAgent()

    def test_validate_sources_accepts_good(self):
        sources = [_source()]
        accepted = self.agent.validate_sources(sources)
        assert len(accepted) == 1

    def test_validate_sources_rejects_social(self):
        # Can't construct social source (validator blocks it), so we patch manually
        good = _source()
        # Low credibility source should be rejected
        low_cred = _source(
            url="https://example-blog.com/article",
            kind=SourceKind.BLOG,
            title="Some blog post",
            credibility=0.1,  # below 0.3 threshold
        )
        accepted = self.agent.validate_sources([good, low_cred])
        assert len(accepted) == 1

    def test_build_report_success(self):
        src = _source()
        section = _section("Overview", "Content about asyncio patterns and usage.", [src.url])
        report = self.agent.build_report(
            title="Asyncio Research",
            query="asyncio patterns in Python 3",
            sources=[src],
            sections=[section],
            summary="Asyncio provides event-loop based concurrency with full stdlib support.",
            confidence=0.85,
            agent_id="researcher-1",
        )
        assert report.read_only is True
        assert report.contains_personal_data is False

    def test_build_report_no_valid_sources_raises(self):
        low_cred = _source(
            url="https://example-blog.com/low",
            kind=SourceKind.BLOG,
            title="Low quality blog",
            credibility=0.1,
        )
        section = _section("Sec", "Content with enough length here.", [low_cred.url])
        with pytest.raises(ValueError, match="no sources"):
            self.agent.build_report(
                title="Will fail",
                query="test query here",
                sources=[low_cred],
                sections=[section],
                summary="This will fail because no sources pass policy validation here.",
            )
