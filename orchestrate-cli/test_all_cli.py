#!/usr/bin/env python3
"""
Test script for Orchestrate CLI - Comprehensive testing of all CLI integrations

This script tests:
1. All framework orchestrators
2. All CLI agents
3. Cross-framework capabilities
4. Configuration loading
5. Tool registry
6. Integration scenarios
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any
from loguru import logger

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.orchestrators.orchestrator_factory import OrchestratorFactory
from src.utils.config_loader import ConfigLoader
from src.utils.tool_registry import ToolRegistry

class OrchestrateTester:
    """Comprehensive tester for Orchestrate CLI"""

    def __init__(self):
        self.config_loader = ConfigLoader()
        self.tool_registry = ToolRegistry()
        self.orchestrator_factory = OrchestratorFactory()
        self.test_results = {}

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all tests"""
        logger.info("🧪 Starting comprehensive Orchestrate CLI tests...")

        # Test results
        results = {
            'config_tests': await self.test_configuration(),
            'framework_tests': await self.test_frameworks(),
            'cli_agent_tests': await self.test_cli_agents(),
            'tool_registry_tests': await self.test_tool_registry(),
            'integration_tests': await self.test_integration(),
            'performance_tests': await self.test_performance(),
            'summary': {}
        }

        # Generate summary
        results['summary'] = self.generate_summary(results)

        return results

    async def test_configuration(self) -> Dict[str, Any]:
        """Test configuration loading and validation"""
        logger.info("🔧 Testing configuration...")

        try:
            # Load configuration
            config = self.config_loader.load()

            # Test configuration validation
            is_valid = self.config_loader._validate_config()

            # Test framework configurations
            frameworks_status = {}
            for framework_name, framework_config in config.get('frameworks', {}).items():
                frameworks_status[framework_name] = {
                    'enabled': framework_config.get('enabled', False),
                    'configured': bool(framework_config.get('providers', {})),
                    'agents_count': len(framework_config.get('agents', {}))
                }

            return {
                'success': True,
                'config_loaded': True,
                'validation_passed': is_valid,
                'frameworks_status': frameworks_status,
                'config_keys': list(config.keys()),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Configuration test failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    async def test_frameworks(self) -> Dict[str, Any]:
        """Test all framework orchestrators"""
        logger.info("🏗️ Testing framework orchestrators...")

        results = {}
        available_frameworks = self.orchestrator_factory.list_available_frameworks()

        for framework in available_frameworks:
            try:
                # Test orchestrator creation
                orchestrator = self.orchestrator_factory.create(framework)

                if orchestrator:
                    # Test getting available agents
                    agents = self.orchestrator_factory.get_available_agents(framework)

                    results[framework] = {
                        'orchestrator_created': True,
                        'agents_count': len(agents),
                        'agents_list': list(agents.keys()),
                        'status': 'ready'
                    }

                    logger.info(f"✓ {framework} orchestrator created successfully")
                else:
                    results[framework] = {
                        'orchestrator_created': False,
                        'error': 'Failed to create orchestrator',
                        'status': 'failed'
                    }

            except Exception as e:
                results[framework] = {
                    'orchestrator_created': False,
                    'error': str(e),
                    'status': 'error'
                }
                logger.error(f"✗ {framework} test failed: {e}")

        return results

    async def test_cli_agents(self) -> Dict[str, Any]:
        """Test all CLI agents"""
        logger.info("🤖 Testing CLI agents...")

        results = {}
        available_agents = self.orchestrator_factory.list_available_cli_agents()

        for agent_name in available_agents:
            try:
                agent = self.orchestrator_factory.get_cli_agent(agent_name)

                if agent:
                    # Test agent availability check
                    if hasattr(agent, 'check_availability'):
                        available = agent.check_availability()
                    else:
                        available = True

                    # Test version check
                    if hasattr(agent, 'get_version'):
                        version = agent.get_version()
                    else:
                        version = {'version': 'unknown'}

                    results[agent_name] = {
                        'agent_loaded': True,
                        'available': available,
                        'version': version,
                        'status': 'ready' if available else 'unavailable'
                    }

                    if available:
                        logger.info(f"✓ {agent_name} agent is available")
                    else:
                        logger.warning(f"⚠ {agent_name} agent is not available")
                else:
                    results[agent_name] = {
                        'agent_loaded': False,
                        'error': 'Failed to load agent',
                        'status': 'failed'
                    }

            except Exception as e:
                results[agent_name] = {
                    'agent_loaded': False,
                    'error': str(e),
                    'status': 'error'
                }
                logger.error(f"✗ {agent_name} test failed: {e}")

        return results

    async def test_tool_registry(self) -> Dict[str, Any]:
        """Test tool registry functionality"""
        logger.info("🔧 Testing tool registry...")

        try:
            # Test tool registration
            initial_count = len(self.tool_registry.list_tools())

            # Register a test tool
            test_tool = {
                'name': 'test_tool',
                'description': 'Test tool for validation',
                'category': 'test',
                'frameworks': ['langchain'],
                'function': lambda x: f"Test response: {x}",
                'parameters': {
                    'input': {'type': 'string', 'required': True}
                }
            }

            registration_result = self.tool_registry.register_tool('test_tool', test_tool)

            # Get updated tool count
            updated_count = len(self.tool_registry.list_tools())

            # Test tool retrieval
            retrieved_tool = self.tool_registry.get_tool('test_tool')

            # Test framework-specific tools
            langchain_tools = self.tool_registry.get_tools_for_framework('langchain')

            # Clean up test tool
            self.tool_registry.remove_tool('test_tool')

            return {
                'success': True,
                'initial_count': initial_count,
                'updated_count': updated_count,
                'registration_successful': registration_result,
                'tool_retrieved': retrieved_tool is not None,
                'langchain_tools_count': len(langchain_tools),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Tool registry test failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    async def test_integration(self) -> Dict[str, Any]:
        """Test integration scenarios"""
        logger.info("🔗 Testing integration scenarios...")

        results = {}

        try:
            # Test 1: Cross-framework task
            cross_framework_task = await self.orchestrator_factory.run_cross_framework_task(
                "Analyze the latest AI trends",
                {
                    'research_agent': 'langchain',
                    'analysis_agent': 'crewai'
                }
            )

            # Test 2: Multi-agent task within framework
            multi_agent_task = await self.orchestrator_factory.run_multi_agent_task(
                'crewai',
                'Create a business plan for a tech startup',
                ['research_agent', 'planning_agent']
            )

            # Test 3: CLI command execution
            cli_test = await self.orchestrator_factory.run_cli_command(
                'gemini',
                'get_version'
            )

            results['cross_framework_task'] = {
                'executed': True,
                'has_result': cross_framework_task.get('results') is not None,
                'agents_used': len(cross_framework_task.get('results', {}))
            }

            results['multi_agent_task'] = {
                'executed': True,
                'has_result': multi_agent_task.get('result') is not None,
                'agents_used': 2
            }

            results['cli_command'] = {
                'executed': True,
                'success': 'error' not in cli_test,
                'has_version': 'version' in cli_test
            }

            return {
                'success': True,
                'scenarios': results,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Integration test failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    async def test_performance(self) -> Dict[str, Any]:
        """Test performance aspects"""
        logger.info("⚡ Testing performance...")

        try:
            import time

            # Test 1: Configuration loading performance
            start_time = time.time()
            self.config_loader.load()
            config_load_time = time.time() - start_time

            # Test 2: Orchestrator creation performance
            start_time = time.time()
            self.orchestrator_factory.create('langchain')
            orchestrator_creation_time = time.time() - start_time

            # Test 3: Tool registry performance
            start_time = time.time()
            self.tool_registry.list_tools()
            tool_list_time = time.time() - start_time

            # Test 4: CLI agent access performance
            start_time = time.time()
            self.orchestrator_factory.get_cli_agent('gemini')
            agent_access_time = time.time() - start_time

            return {
                'success': True,
                'performance_metrics': {
                    'config_load_time': config_load_time,
                    'orchestrator_creation_time': orchestrator_creation_time,
                    'tool_list_time': tool_list_time,
                    'agent_access_time': agent_access_time
                },
                'all_under_1s': all([
                    config_load_time < 1,
                    orchestrator_creation_time < 1,
                    tool_list_time < 1,
                    agent_access_time < 1
                ]),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Performance test failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    def generate_summary(self, test_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate test summary"""
        summary = {
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': 0,
            'frameworks_tested': len(test_results.get('framework_tests', {})),
            'cli_agents_tested': len(test_results.get('cli_agent_tests', {})),
            'tools_count': len(self.tool_registry.list_tools()),
            'overall_status': 'success'
        }

        # Count tests
        for test_category, test_data in test_results.items():
            if test_category != 'summary':
                if isinstance(test_data, dict):
                    if test_data.get('success', False):
                        summary['passed_tests'] += 1
                    else:
                        summary['failed_tests'] += 1
                    summary['total_tests'] += 1

        # Determine overall status
        if summary['failed_tests'] > 0:
            summary['overall_status'] = 'partial_failure'
        if summary['failed_tests'] > summary['passed_tests']:
            summary['overall_status'] = 'major_failure'

        return summary

    def print_report(self, results: Dict[str, Any]):
        """Print test report"""
        print("\n" + "="*60)
        print("🧪 ORCHESTRATE CLI COMPREHENSIVE TEST REPORT")
        print("="*60)

        # Summary
        summary = results.get('summary', {})
        print(f"\n📊 SUMMARY:")
        print(f"   Total Tests: {summary.get('total_tests', 0)}")
        print(f"   Passed: {summary.get('passed_tests', 0)} ✅")
        print(f"   Failed: {summary.get('failed_tests', 0)} ❌")
        print(f"   Overall Status: {summary.get('overall_status', 'unknown').upper()}")

        # Frameworks
        print(f"\n🏗️ FRAMEWORKS:")
        frameworks = results.get('framework_tests', {})
        for framework, status in frameworks.items():
            status_icon = "✅" if status.get('orchestrator_created') else "❌"
            print(f"   {status_icon} {framework}: {status.get('status', 'unknown')}")

        # CLI Agents
        print(f"\n🤖 CLI AGENTS:")
        cli_agents = results.get('cli_agent_tests', {})
        for agent, status in cli_agents.items():
            status_icon = "✅" if status.get('available') else "⚠️"
            print(f"   {status_icon} {agent}: {status.get('status', 'unknown')}")

        # Performance
        print(f"\n⚡ PERFORMANCE:")
        perf = results.get('performance_tests', {})
        if perf.get('success'):
            metrics = perf.get('performance_metrics', {})
            print(f"   Config Load: {metrics.get('config_load_time', 0):.3f}s")
            print(f"   Orchestrator Create: {metrics.get('orchestrator_creation_time', 0):.3f}s")
            print(f"   Tool List: {metrics.get('tool_list_time', 0):.3f}s")
            print(f"   Agent Access: {metrics.get('agent_access_time', 0):.3f}s")
            print(f"   All Under 1s: {'✅' if perf.get('all_under_1s') else '❌'}")

        # Integration
        print(f"\n🔗 INTEGRATION:")
        integration = results.get('integration_tests', {})
        if integration.get('success'):
            scenarios = integration.get('scenarios', {})
            for scenario, result in scenarios.items():
                status_icon = "✅" if result.get('executed') else "❌"
                print(f"   {status_icon} {scenario}: {result.get('success', False)}")

        print("\n" + "="*60)

async def main():
    """Main test runner"""
    tester = OrchestrateTester()

    # Run all tests
    results = await tester.run_all_tests()

    # Print report
    tester.print_report(results)

    # Save results
    results_file = Path("test_results.json")
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"📄 Test results saved to: {results_file}")

    # Return exit code based on results
    summary = results.get('summary', {})
    if summary.get('overall_status') == 'success':
        print("\n🎉 All tests passed!")
        return 0
    elif summary.get('overall_status') == 'partial_failure':
        print("\n⚠️ Some tests failed, but system is functional")
        return 1
    else:
        print("\n❌ Multiple test failures detected")
        return 2

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
