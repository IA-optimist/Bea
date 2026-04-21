#!/usr/bin/env python3
"""
Tests for OpportunityScanner with Playwright mocking.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch
import json

from business.automation.opportunity_scanner import (
    OpportunityScanner, 
    Opportunity
)


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Temporary cache directory for tests"""
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def scanner(temp_cache_dir):
    """Create scanner instance with temp cache"""
    return OpportunityScanner(cache_dir=temp_cache_dir, headless=True)


@pytest.fixture
def sample_opportunity():
    """Create a sample opportunity for testing"""
    return Opportunity(
        title="Test SaaS Idea",
        description="A great SaaS solution for productivity",
        source="test_source",
        url="https://example.com/test",
        discovered_at=datetime.now(),
        upvotes=100,
        comments=25,
        mentions=5,
        tags=["saas", "productivity"],
        pain_points=["Difficult to manage tasks", "Need better workflow"]
    )


class TestOpportunity:
    """Test Opportunity dataclass methods"""
    
    def test_opportunity_creation(self, sample_opportunity):
        """Test basic opportunity creation"""
        assert sample_opportunity.title == "Test SaaS Idea"
        assert sample_opportunity.upvotes == 100
        assert sample_opportunity.comments == 25
        assert len(sample_opportunity.tags) == 2
        assert len(sample_opportunity.pain_points) == 2
    
    def test_calculate_total_score(self, sample_opportunity):
        """Test score calculation"""
        sample_opportunity.demand_score = 80.0
        sample_opportunity.competition_score = 60.0
        sample_opportunity.feasibility_score = 70.0
        sample_opportunity.monetization_score = 50.0
        
        sample_opportunity.calculate_total_score()
        
        # Weights: demand=0.35, competition=0.20, feasibility=0.25, monetization=0.20
        expected = 80*0.35 + 60*0.20 + 70*0.25 + 50*0.20
        assert abs(sample_opportunity.total_score - expected) < 0.01
    
    def test_to_dict(self, sample_opportunity):
        """Test serialization to dict"""
        sample_opportunity.demand_score = 75.0
        sample_opportunity.calculate_total_score()
        
        data = sample_opportunity.to_dict()
        
        assert isinstance(data, dict)
        assert data['title'] == "Test SaaS Idea"
        assert data['metrics']['upvotes'] == 100
        assert data['metrics']['comments'] == 25
        assert 'scores' in data
        assert data['scores']['demand'] == 75.0
        assert isinstance(data['discovered_at'], str)


class TestOpportunityScanner:
    """Test OpportunityScanner class"""
    
    def test_scanner_initialization(self, scanner, temp_cache_dir):
        """Test scanner initialization"""
        assert scanner.cache_dir == temp_cache_dir
        assert scanner.headless is True
        assert scanner.screenshot_dir.exists()
    
    def test_is_problem_post(self, scanner):
        """Test problem post detection"""
        # Should match
        assert scanner._is_problem_post("I have a problem with X", "")
        assert scanner._is_problem_post("Need help with automation", "")
        assert scanner._is_problem_post("", "Looking for a solution to manage tasks")
        assert scanner._is_problem_post("Struggling to automate workflow", "")
        
        # Should not match
        assert not scanner._is_problem_post("Just launched my new product", "")
        assert not scanner._is_problem_post("Happy with the results", "")
    
    def test_extract_pain_points(self, scanner):
        """Test pain point extraction"""
        text = """
        The main problem is that we struggle to manage our workflow efficiently.
        We need to automate repetitive tasks but it's frustrating when tools don't integrate.
        """
        
        pain_points = scanner._extract_pain_points(text)
        
        assert isinstance(pain_points, list)
        assert len(pain_points) > 0
        # Should extract at least one pain point
        assert any("manage" in pp.lower() or "automate" in pp.lower() for pp in pain_points)
    
    def test_extract_tags(self, scanner):
        """Test tag extraction"""
        text = "Looking for a SaaS solution with AI automation for productivity and analytics"
        
        tags = scanner._extract_tags(text)
        
        assert isinstance(tags, list)
        assert 'saas' in tags
        assert 'ai' in tags
        assert 'automation' in tags
        assert 'productivity' in tags
        assert 'analytics' in tags
    
    def test_score_opportunity(self, scanner, sample_opportunity):
        """Test opportunity scoring"""
        scanner._score_opportunity(sample_opportunity)
        
        assert sample_opportunity.demand_score > 0
        assert sample_opportunity.competition_score >= 0
        assert sample_opportunity.feasibility_score > 0
        assert sample_opportunity.monetization_score > 0
        assert sample_opportunity.total_score > 0
        
        # Check score bounds
        assert 0 <= sample_opportunity.demand_score <= 100
        assert 0 <= sample_opportunity.competition_score <= 100
        assert 0 <= sample_opportunity.feasibility_score <= 100
        assert 0 <= sample_opportunity.monetization_score <= 100
    
    def test_get_top_opportunities(self, scanner):
        """Test getting top opportunities"""
        opps = []
        for i in range(20):
            opp = Opportunity(
                title=f"Opportunity {i}",
                description="Test",
                source="test",
                url=f"https://test.com/{i}",
                discovered_at=datetime.now(),
                total_score=float(i * 5)  # Varying scores
            )
            opps.append(opp)
        
        top_5 = scanner.get_top_opportunities(opps, limit=5)
        
        assert len(top_5) == 5
        # Should be sorted by score descending
        assert top_5[0].total_score >= top_5[1].total_score
        assert top_5[1].total_score >= top_5[2].total_score
    
    def test_save_opportunities(self, scanner, sample_opportunity, temp_cache_dir):
        """Test saving opportunities to JSON"""
        opportunities = [sample_opportunity]
        
        filepath = scanner.save_opportunities(opportunities, "test_output.json")
        
        assert filepath.exists()
        assert filepath.name == "test_output.json"
        
        # Load and verify
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        assert data['total_opportunities'] == 1
        assert len(data['opportunities']) == 1
        assert data['opportunities'][0]['title'] == "Test SaaS Idea"
    
    def test_generate_report(self, scanner, sample_opportunity):
        """Test report generation"""
        opportunities = [sample_opportunity]
        scanner._score_opportunity(sample_opportunity)
        
        report = scanner.generate_report(opportunities, top_n=5)
        
        assert isinstance(report, str)
        assert "BUSINESS OPPORTUNITIES REPORT" in report
        assert sample_opportunity.title in report
        assert sample_opportunity.source in report
        assert "Scores:" in report


class TestPlaywrightIntegration:
    """Test Playwright browser automation with mocks"""
    
    @pytest.mark.asyncio
    async def test_setup_browser(self, scanner):
        """Test browser setup with stealth mode"""
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.add_init_script = AsyncMock()
        
        await scanner._setup_browser(mock_browser)
        
        # Verify context created with proper settings
        mock_browser.new_context.assert_called_once()
        call_kwargs = mock_browser.new_context.call_args[1]
        
        assert 'viewport' in call_kwargs
        assert call_kwargs['viewport']['width'] == 1920
        assert call_kwargs['viewport']['height'] == 1080
        assert 'user_agent' in call_kwargs
        assert 'Mozilla' in call_kwargs['user_agent']
        
        # Verify stealth script added
        mock_page.add_init_script.assert_called_once()
        script = mock_page.add_init_script.call_args[0][0]
        assert 'navigator.webdriver' in script
    
    @pytest.mark.asyncio
    async def test_capture_error_screenshot(self, scanner):
        """Test error screenshot capture"""
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()
        
        await scanner._capture_error_screenshot(mock_page, "test_error")
        
        mock_page.screenshot.assert_called_once()
        call_kwargs = mock_page.screenshot.call_args[1]
        
        assert 'path' in call_kwargs
        assert 'error_test_error' in call_kwargs['path']
        assert call_kwargs['full_page'] is True
    
    @pytest.mark.asyncio
    async def test_scan_product_hunt_mock(self, scanner):
        """Test Product Hunt scanning with mocked browser"""
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        
        # Setup mock chain
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.add_init_script = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.close = AsyncMock()
        
        # Mock HTML content
        mock_html = """
        <html>
            <article class="post-item">
                <h2 class="title">Amazing SaaS Product</h2>
                <p class="description">Solves automation problems</p>
                <a href="/posts/test-product">View</a>
                <span class="vote-count">150</span>
            </article>
        </html>
        """
        mock_page.content = AsyncMock(return_value=mock_html)
        
        opportunities = await scanner.scan_product_hunt(mock_browser, days_back=30)
        
        # Verify browser interactions
        mock_page.goto.assert_called_once()
        assert "producthunt.com" in mock_page.goto.call_args[0][0]
        mock_page.content.assert_called_once()
        mock_page.close.assert_called_once()
        
        # Verify opportunities extracted
        assert isinstance(opportunities, list)
    
    @pytest.mark.asyncio
    async def test_scan_reddit_mock(self, scanner):
        """Test Reddit scanning with mocked browser"""
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        
        # Setup mock chain
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.add_init_script = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.close = AsyncMock()
        
        # Mock Reddit HTML
        mock_html = """
        <html>
            <div class="thing">
                <a class="title">Looking for help with SaaS problem</a>
                <div class="score unvoted">250</div>
                <a class="comments">45 comments</a>
            </div>
        </html>
        """
        mock_page.content = AsyncMock(return_value=mock_html)
        
        opportunities = await scanner.scan_reddit(mock_browser, days_back=30)
        
        # Should have tried all subreddits
        assert mock_page.goto.call_count == 4  # 4 subreddits
        assert isinstance(opportunities, list)
    
    @pytest.mark.asyncio
    async def test_scan_hackernews_mock(self, scanner):
        """Test Hacker News scanning with mocked browser"""
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        
        # Setup mock chain
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.add_init_script = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.close = AsyncMock()
        
        # Mock HN HTML
        mock_html = """
        <html>
            <tr class="athing" id="12345">
                <td class="title"><span class="titleline"><a>Show HN: My cool automation tool</a></span></td>
            </tr>
            <tr>
                <td class="subtext">
                    <span class="score">120 points</span>
                    <a>35 comments</a>
                </td>
            </tr>
        </html>
        """
        mock_page.content = AsyncMock(return_value=mock_html)
        
        opportunities = await scanner.scan_hackernews(mock_browser, days_back=30)
        
        mock_page.goto.assert_called_once()
        assert "news.ycombinator.com" in mock_page.goto.call_args[0][0]
        assert isinstance(opportunities, list)
    
    @pytest.mark.asyncio
    async def test_scan_all_integration(self, scanner):
        """Test full scan_all workflow with mocked playwright"""
        with patch('business.automation.opportunity_scanner.async_playwright') as mock_playwright:
            # Setup mock playwright
            mock_pw = AsyncMock()
            mock_browser = AsyncMock()
            
            mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
            mock_playwright.return_value.__aexit__ = AsyncMock()
            mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.close = AsyncMock()
            
            # Mock individual scan methods
            scanner.scan_product_hunt = AsyncMock(return_value=[])
            scanner.scan_reddit = AsyncMock(return_value=[])
            scanner.scan_hackernews = AsyncMock(return_value=[])
            
            opportunities = await scanner.scan_all(days_back=30)
            
            # Verify browser lifecycle
            mock_pw.chromium.launch.assert_called_once()
            mock_browser.close.assert_called_once()
            
            # Verify all sources scanned
            scanner.scan_product_hunt.assert_called_once()
            scanner.scan_reddit.assert_called_once()
            scanner.scan_hackernews.assert_called_once()
            
            assert isinstance(opportunities, list)


class TestErrorHandling:
    """Test error handling and resilience"""
    
    @pytest.mark.asyncio
    async def test_screenshot_on_error(self, scanner):
        """Test that screenshots are captured on errors"""
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()
        
        await scanner._capture_error_screenshot(mock_page, "network_error")
        
        mock_page.screenshot.assert_called_once()
        # Verify screenshot saved in screenshot directory
        list(scanner.screenshot_dir.glob("*.png"))
        # Note: Won't exist in mock, but verifies the call was made
    
    @pytest.mark.asyncio
    async def test_scan_continues_on_source_failure(self, scanner):
        """Test that scan continues if one source fails"""
        with patch('business.automation.opportunity_scanner.async_playwright') as mock_playwright:
            mock_pw = AsyncMock()
            mock_browser = AsyncMock()
            
            mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
            mock_playwright.return_value.__aexit__ = AsyncMock()
            mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.close = AsyncMock()
            
            # Make Product Hunt fail but others succeed
            sample_opp = Opportunity(
                title="Test",
                description="Test",
                source="reddit",
                url="https://test.com",
                discovered_at=datetime.now()
            )
            
            scanner.scan_product_hunt = AsyncMock(side_effect=Exception("PH failed"))
            scanner.scan_reddit = AsyncMock(return_value=[sample_opp])
            scanner.scan_hackernews = AsyncMock(return_value=[])
            
            opportunities = await scanner.scan_all(days_back=30)
            
            # Should still get Reddit results despite PH failure
            assert len(opportunities) >= 1
            assert opportunities[0].source == "reddit"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
