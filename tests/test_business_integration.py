"""
Tests for business mission integration with MetaOrchestrator.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_settings():
    """Mock settings object."""
    settings = MagicMock()
    settings.jarvis_root = "/tmp/jarvismax"
    settings.llm_provider = "openai"
    settings.model = "gpt-4"
    return settings


class TestBusinessHandlersRegistration:
    """Test business handlers registration."""
    
    def test_handlers_registered_on_import(self):
        """Test that handlers are defined in registry."""
        from core.orchestration.business_missions import BUSINESS_MISSION_HANDLERS
        
        assert len(BUSINESS_MISSION_HANDLERS) == 6
        assert "business.scan_opportunities" in BUSINESS_MISSION_HANDLERS
        assert "business.build_product" in BUSINESS_MISSION_HANDLERS
        assert "business.deploy_product" in BUSINESS_MISSION_HANDLERS
        assert "business.check_compliance" in BUSINESS_MISSION_HANDLERS
        assert "business.optimize_taxes" in BUSINESS_MISSION_HANDLERS
        assert "business.track_revenue" in BUSINESS_MISSION_HANDLERS
    
    def test_register_business_handlers(self, mock_settings):
        """Test registering handlers with orchestrator."""
        from core.meta_orchestrator import MetaOrchestrator
        from core.orchestration.business_missions import register_business_handlers
        
        orchestrator = MetaOrchestrator(mock_settings)
        register_business_handlers(orchestrator)
        
        assert len(orchestrator._custom_handlers) == 6
        assert "business.scan_opportunities" in orchestrator._custom_handlers


class TestMetaOrchestratorCustomHandlers:
    """Test MetaOrchestrator custom handler system."""
    
    def test_register_mission_handler(self, mock_settings):
        """Test registering a custom handler."""
        from core.meta_orchestrator import MetaOrchestrator
        
        orchestrator = MetaOrchestrator(mock_settings)
        
        async def custom_handler(mission, context):
            return {"status": "success", "result": "test"}
        
        orchestrator.register_mission_handler("test.custom", custom_handler)
        
        assert "test.custom" in orchestrator._custom_handlers
        assert orchestrator._custom_handlers["test.custom"] == custom_handler
    
    async def test_dispatch_custom_mission_success(self, mock_settings):
        """Test dispatching to a custom handler."""
        from core.meta_orchestrator import MetaOrchestrator
        
        orchestrator = MetaOrchestrator(mock_settings)
        
        async def custom_handler(mission, context):
            return {"status": "success", "data": mission["params"]["test_value"]}
        
        orchestrator.register_mission_handler("test.custom", custom_handler)
        
        mission = {
            "type": "test.custom",
            "params": {"test_value": 42}
        }
        
        result = await orchestrator.dispatch_custom_mission("test.custom", mission)
        
        assert result["status"] == "success"
        assert result["data"] == 42
    
    async def test_dispatch_unknown_mission_type(self, mock_settings):
        """Test dispatching to unknown handler raises KeyError."""
        from core.meta_orchestrator import MetaOrchestrator
        
        orchestrator = MetaOrchestrator(mock_settings)
        
        mission = {"type": "unknown.type", "params": {}}
        
        with pytest.raises(KeyError, match="No handler registered"):
            await orchestrator.dispatch_custom_mission("unknown.type", mission)
    
    async def test_dispatch_handler_exception(self, mock_settings):
        """Test handler exceptions are propagated."""
        from core.meta_orchestrator import MetaOrchestrator
        
        orchestrator = MetaOrchestrator(mock_settings)
        
        async def failing_handler(mission, context):
            raise ValueError("Test error")
        
        orchestrator.register_mission_handler("test.failing", failing_handler)
        
        mission = {"type": "test.failing", "params": {}}
        
        with pytest.raises(ValueError, match="Test error"):
            await orchestrator.dispatch_custom_mission("test.failing", mission)


class TestBusinessScanOpportunities:
    """Test business.scan_opportunities handler."""
    
    @patch('business.automation.opportunity_scanner.OpportunityScanner')
    async def test_scan_opportunities_success(self, mock_scanner_class):
        """Test successful opportunity scan."""
        from core.orchestration.business_missions import handle_scan_opportunities
        from business.automation.opportunity_scanner import Opportunity
        from datetime import datetime
        
        # Mock scanner
        mock_scanner = MagicMock()
        mock_opp = MagicMock(spec=Opportunity)
        mock_opp.title = "Test Opportunity"
        mock_opp.description = "Test description"
        mock_opp.source = "reddit"
        mock_opp.url = "https://example.com"
        mock_opp.total_score = 75.0
        mock_opp.demand_score = 80.0
        mock_opp.competition_score = 70.0
        mock_opp.feasibility_score = 75.0
        mock_opp.monetization_score = 75.0
        mock_opp.upvotes = 100
        mock_opp.comments = 50
        mock_opp.tags = ["saas", "b2b"]
        mock_opp.pain_points = ["manual process"]
        
        mock_scanner.scan_all.return_value = [mock_opp]
        mock_scanner_class.return_value = mock_scanner
        
        mission = {
            "type": "business.scan_opportunities",
            "params": {
                "days_back": 7,
                "min_score": 60.0
            }
        }
        
        result = await handle_scan_opportunities(mission)
        
        assert result["status"] == "success"
        assert len(result["opportunities"]) == 1
        assert result["opportunities"][0]["title"] == "Test Opportunity"
        assert result["opportunities"][0]["score"] == 75.0
        assert result["summary"]["total_found"] == 1
        assert result["summary"]["high_score"] == 1
    
    @patch('business.automation.opportunity_scanner.OpportunityScanner')
    async def test_scan_opportunities_filters_low_score(self, mock_scanner_class):
        """Test that low-score opportunities are filtered."""
        from core.orchestration.business_missions import handle_scan_opportunities
        from business.automation.opportunity_scanner import Opportunity
        
        mock_scanner = MagicMock()
        
        # Create two opportunities: one high score, one low
        high_opp = MagicMock(spec=Opportunity)
        high_opp.total_score = 75.0
        high_opp.title = "High Score"
        high_opp.description = "desc"
        high_opp.source = "reddit"
        high_opp.url = "https://example.com"
        high_opp.demand_score = 80.0
        high_opp.competition_score = 70.0
        high_opp.feasibility_score = 75.0
        high_opp.monetization_score = 75.0
        high_opp.upvotes = 100
        high_opp.comments = 50
        high_opp.tags = []
        high_opp.pain_points = []
        
        low_opp = MagicMock(spec=Opportunity)
        low_opp.total_score = 45.0
        low_opp.source = "hackernews"
        
        mock_scanner.scan_all.return_value = [high_opp, low_opp]
        mock_scanner_class.return_value = mock_scanner
        
        mission = {
            "type": "business.scan_opportunities",
            "params": {
                "days_back": 30,
                "min_score": 60.0
            }
        }
        
        result = await handle_scan_opportunities(mission)
        
        assert result["status"] == "success"
        assert len(result["opportunities"]) == 1
        assert result["opportunities"][0]["title"] == "High Score"
        assert result["summary"]["total_found"] == 2
        assert result["summary"]["high_score"] == 1


class TestBusinessBuildProduct:
    """Test business.build_product handler."""
    
    @patch('business.automation.product_builder.ProductBuilder')
    async def test_build_product_success(self, mock_builder_class):
        """Test successful product build."""
        from core.orchestration.business_missions import handle_build_product
        from pathlib import Path
        
        # Mock builder
        mock_builder = MagicMock()
        mock_product = MagicMock()
        mock_product.name = "Test Product"
        mock_product.description = "Test description"
        mock_product.output_dir = Path("/tmp/test_product")
        mock_product.stack = "react_fastapi"
        mock_product.features = ["auth", "payments"]
        mock_product.pricing_model = "subscription"
        
        mock_builder.build_from_spec.return_value = mock_product
        mock_builder_class.return_value = mock_builder
        
        mission = {
            "type": "business.build_product",
            "params": {
                "opportunity": {
                    "title": "Test Product",
                    "description": "Test description",
                    "tags": ["saas"],
                    "pain_points": ["manual process"]
                },
                "stack": "react_fastapi",
                "features": ["auth", "payments"]
            }
        }
        
        result = await handle_build_product(mission)
        
        assert result["status"] == "success"
        assert result["product"]["name"] == "Test Product"
        assert result["product"]["stack"] == "react_fastapi"
        assert "artifacts" in result


class TestCLIIntegration:
    """Test CLI integration with orchestrator."""
    
    @patch('core.meta_orchestrator.get_meta_orchestrator')
    async def test_cli_scan_command(self, mock_get_orch):
        """Test CLI scan command."""
        from jarvismax_cli import cmd_scan
        
        mock_orch = MagicMock()
        mock_orch.dispatch_custom_mission = AsyncMock(return_value={
            "status": "success",
            "opportunities": [
                {
                    "title": "Test Opp",
                    "score": 75.0,
                    "source": "reddit",
                    "description": "desc",
                    "url": "https://example.com",
                    "upvotes": 100,
                    "comments": 50
                }
            ],
            "summary": {
                "total_found": 1,
                "high_score": 1,
                "avg_score": 75.0,
                "top_sources": {"reddit": 1}
            }
        })
        mock_get_orch.return_value = mock_orch
        
        # Test scan command
        await cmd_scan(["30"])
        
        # Verify dispatch was called with correct mission
        mock_orch.dispatch_custom_mission.assert_called_once()
        call_args = mock_orch.dispatch_custom_mission.call_args
        assert call_args[0][0] == "business.scan_opportunities"
        assert call_args[0][1]["params"]["days_back"] == 30
