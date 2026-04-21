#!/usr/bin/env python3
"""
Tests for Business Engine integration with CognitionOrchestrator.
Phase 7: Validates bridge between cognition and business automation.
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cognition.orchestrator import CognitionOrchestrator
from business.business_engine import BusinessEngine
from business.automation.opportunity_scanner import Opportunity


class TestBusinessIntegration:
    """Test CognitionOrchestrator + BusinessEngine integration."""
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = Mock()
        llm.ainvoke = Mock(return_value=Mock(content="Business analysis complete"))
        return llm
    
    @pytest.fixture
    def orchestrator(self, mock_llm, tmp_path):
        """Create orchestrator with mocked components."""
        return CognitionOrchestrator(
            llm_client=mock_llm,
            business_workspace=tmp_path / "business"
        )
    
    def test_orchestrator_has_business_engine(self, orchestrator):
        """Test that orchestrator initializes with BusinessEngine."""
        assert hasattr(orchestrator, 'business_engine')
        assert isinstance(orchestrator.business_engine, BusinessEngine)
    
    def test_business_mission_routing(self, orchestrator):
        """Test that business missions are routed correctly."""
        mission = {
            "mission_id": "test-001",
            "goal": "Scan for business opportunities",
            "operation": "scan_opportunities",
            "params": {"days_back": 7}
        }
        
        # Mock the business engine scan
        mock_opportunity = Mock(spec=Opportunity)
        mock_opportunity.to_dict.return_value = {
            "title": "Test Opportunity",
            "score": 8.5
        }
        
        with patch.object(orchestrator.business_engine, 'scan_opportunities', return_value=[mock_opportunity]):
            result = orchestrator.process(mission)
        
        assert result["status"] == "COMPLETED"
        assert "business_result" in result
        assert result["business_result"]["operation"] == "scan_opportunities"
        assert result["cognition"]["business_engine_used"] is True
    
    def test_keyword_detection_business(self, orchestrator):
        """Test that business keywords trigger business engine."""
        mission = {
            "mission_id": "test-002",
            "goal": "Check my SaaS portfolio revenue",
            "operation": "portfolio_status"  # Explicit operation
        }
        
        mock_portfolio = Mock()
        mock_portfolio.total_mrr = 1500.0
        mock_portfolio.total_arr = 18000.0
        mock_portfolio.total_products = 3
        mock_portfolio.total_customers = 50
        
        with patch.object(orchestrator.business_engine, 'get_portfolio_status', return_value=mock_portfolio):
            result = orchestrator.process(mission)
        
        assert result["status"] == "COMPLETED"
        assert "business_result" in result
        assert result["business_result"]["mrr"] == 1500.0
    
    def test_portfolio_status_operation(self, orchestrator):
        """Test portfolio_status operation."""
        mission = {
            "mission_id": "test-003",
            "goal": "Get portfolio metrics",
            "operation": "portfolio_status",
        }
        
        mock_portfolio = Mock()
        mock_portfolio.total_mrr = 2500.0
        mock_portfolio.total_arr = 30000.0
        mock_portfolio.total_products = 5
        mock_portfolio.total_customers = 100
        
        with patch.object(orchestrator.business_engine, 'get_portfolio_status', return_value=mock_portfolio):
            result = orchestrator.process(mission)
        
        assert result["status"] == "COMPLETED"
        assert result["business_result"]["mrr"] == 2500.0
        assert result["business_result"]["products"] == 5
        assert "€2500.00 MRR" in result["result"]
    
    def test_scan_opportunities_operation(self, orchestrator):
        """Test scan_opportunities operation."""
        mission = {
            "mission_id": "test-004",
            "goal": "Find new business opportunities",
            "operation": "scan_opportunities",
            "params": {"days_back": 14}
        }
        
        mock_opportunities = [
            Mock(to_dict=Mock(return_value={"title": f"Opp {i}", "score": 8.0 + i}))
            for i in range(3)
        ]
        
        with patch.object(orchestrator.business_engine, 'scan_opportunities', return_value=mock_opportunities):
            result = orchestrator.process(mission)
        
        assert result["status"] == "COMPLETED"
        assert result["business_result"]["opportunities_found"] == 3
        assert len(result["business_result"]["opportunities"]) == 3
    
    def test_run_pipeline_operation(self, orchestrator):
        """Test full pipeline operation."""
        mission = {
            "mission_id": "test-005",
            "goal": "Run full business pipeline",
            "operation": "run_pipeline",
            "params": {
                "days_back": 7,
                "top_n": 3,
                "auto_build": False,
                "auto_deploy": False
            }
        }
        
        mock_result = {
            "status": "success",
            "summary": {
                "opportunities_scanned": 10,
                "safe_opportunities": 5,
                "products_built": 0
            }
        }
        
        with patch.object(orchestrator.business_engine, 'run_pipeline', return_value=mock_result):
            result = orchestrator.process(mission)
        
        assert result["status"] == "COMPLETED"
        assert "summary" in result["business_result"]
        assert result["business_result"]["summary"]["opportunities_scanned"] == 10
    
    def test_business_mission_with_cognition_tracking(self, orchestrator):
        """Test that business missions get cognition tracking."""
        mission = {
            "mission_id": "test-006",
            "goal": "Business analysis",
            "operation": "portfolio_status",
        }
        
        mock_portfolio = Mock()
        mock_portfolio.total_mrr = 1000.0
        mock_portfolio.total_arr = 12000.0
        mock_portfolio.total_products = 2
        mock_portfolio.total_customers = 25
        
        with patch.object(orchestrator.business_engine, 'get_portfolio_status', return_value=mock_portfolio):
            result = orchestrator.process(mission)
        
        # Check cognition metadata
        assert "cognition" in result
        assert result["cognition"]["business_engine_used"] is True
        assert "confidence_scored" in result["cognition"]
    
    def test_business_operation_error_handling(self, orchestrator):
        """Test error handling in business operations."""
        mission = {
            "mission_id": "test-007",
            "goal": "Test error handling",
            "operation": "scan_opportunities",
        }
        
        with patch.object(orchestrator.business_engine, 'scan_opportunities', side_effect=Exception("API Error")):
            result = orchestrator.process(mission)
        
        assert result["status"] == "FAILED"
        assert "error" in result["business_result"]
        assert "API Error" in result["result"]
    
    def test_invalid_business_operation(self, orchestrator):
        """Test handling of invalid operation."""
        mission = {
            "mission_id": "test-008",
            "goal": "business Invalid operation test",  # Add business keyword
            "operation": "invalid_operation",
        }
        
        result = orchestrator.process(mission)
        
        assert result["status"] == "FAILED"
        assert "Unknown business operation" in result["result"]
    
    def test_build_product_requires_opportunity(self, orchestrator):
        """Test that build_product requires opportunity param."""
        mission = {
            "mission_id": "test-009",
            "goal": "Build product",
            "operation": "build_product",
            "params": {}  # Missing opportunity
        }
        
        result = orchestrator.process(mission)
        
        assert result["status"] == "FAILED"
        assert "opportunity parameter required" in result["result"]
    
    def test_business_prefix_stripping(self, orchestrator):
        """Test that business_ prefix is stripped from operation."""
        mission = {
            "mission_id": "test-010",
            "goal": "Test prefix",
            "operation": "business_portfolio_status",
        }
        
        mock_portfolio = Mock()
        mock_portfolio.total_mrr = 500.0
        mock_portfolio.total_arr = 6000.0
        mock_portfolio.total_products = 1
        mock_portfolio.total_customers = 10
        
        with patch.object(orchestrator.business_engine, 'get_portfolio_status', return_value=mock_portfolio):
            result = orchestrator.process(mission)
        
        assert result["status"] == "COMPLETED"
        assert result["business_result"]["operation"] == "portfolio_status"


class TestBusinessBridge:
    """Test the bridge between cognition results and business inputs."""
    
    @pytest.fixture
    def mock_llm(self):
        llm = Mock()
        llm.ainvoke = Mock(return_value=Mock(content="Analysis"))
        return llm
    
    def test_cognition_result_to_business_input(self, mock_llm, tmp_path):
        """Test data transformation from cognition to business."""
        orchestrator = CognitionOrchestrator(
            llm_client=mock_llm,
            business_workspace=tmp_path / "business"
        )
        
        # Simulate cognition result being used as business input
        cognition_mission = {
            "mission_id": "cog-001",
            "goal": "Analyze market trends",
            "result": "Strong demand for AI tools"
        }
        
        # Convert to business params
        business_mission = {
            "mission_id": "bus-001",
            "goal": "Find opportunities based on: " + cognition_mission["result"],
            "operation": "scan_opportunities",
            "params": {"days_back": 30}
        }
        
        mock_opportunities = [Mock(to_dict=Mock(return_value={"title": "AI Tool"}))]
        
        with patch.object(orchestrator.business_engine, 'scan_opportunities', return_value=mock_opportunities):
            result = orchestrator.process(business_mission)
        
        assert result["status"] == "COMPLETED"
        assert "AI tools" in result["goal"]  # Check the actual goal content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
