#!/usr/bin/env python3
"""
Demo Script - Showcasing Orchestrate CLI Capabilities

This script demonstrates the power of Orchestrate CLI by showing:
1. All CLI agents working together
2. Cross-framework orchestration
3. Multi-agent collaboration
4. Professional workflow automation
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any

# Add src to path
import sys
sys.path.append(str(Path(__file__).parent / 'src'))

from src.orchestrators.orchestrator_factory import OrchestratorFactory
from src.utils.config_loader import ConfigLoader

class OrchestrateDemo:
    """Demonstration of Orchestrate CLI capabilities"""
    
    def __init__(self):
        self.config_loader = ConfigLoader()
        self.orchestrator_factory = OrchestratorFactory(self.config_loader.config)
        
    async def run_demo(self) -> Dict[str, Any]:
        """Run the complete demonstration"""
        print("🎬 Starting Orchestrate CLI Demo...")
        print("="*60)
        
        demo_results = {
            'demo_name': 'Orchestrate CLI Comprehensive Demo',
            'timestamp': asyncio.get_event_loop().time(),
            'scenarios': []
        }
        
        # Scenario 1: Show all available agents
        print("\n📋 Scenario 1: Show Available Agents")
        scenario1 = await self.show_available_agents()
        demo_results['scenarios'].append(scenario1)
        
        # Scenario 2: Cross-framework research
        print("\n🔍 Scenario 2: Cross-Framework Research")
        scenario2 = await self.cross_framework_research()
        demo_results['scenarios'].append(scenario2)
        
        # Scenario 3: Multi-agent code generation
        print("\n💻 Scenario 3: Multi-Agent Code Generation")
        scenario3 = await self.multi_agent_code_generation()
        demo_results['scenarios'].append(scenario3)
        
        # Scenario 4: Comprehensive code review
        print("\n🔍 Scenario 4: Comprehensive Code Review")
        scenario4 = await self.comprehensive_code_review()
        demo_results['scenarios'].append(scenario4)
        
        # Scenario 5: Testing and validation
        print("\n🧪 Scenario 5: Testing and Validation")
        scenario5 = await self.testing_validation()
        demo_results['scenarios'].append(scenario5)
        
        # Scenario 6: Documentation generation
        print("\n📝 Scenario 6: Documentation Generation")
        scenario6 = await self.documentation_generation()
        demo_results['scenarios'].append(scenario6)
        
        # Scenario 7: Deployment planning
        print("\n🚀 Scenario 7: Deployment Planning")
        scenario7 = await self.deployment_planning()
        demo_results['scenarios'].append(scenario7)
        
        # Generate final summary
        demo_results['summary'] = self.generate_demo_summary(demo_results)
        
        print("\n" + "="*60)
        print("✅ Demo completed successfully!")
        return demo_results
    
    async def show_available_agents(self) -> Dict[str, Any]:
        """Show all available agents and their status"""
        print("   🔍 Checking agent availability...")
        
        # Get CLI agents status
        cli_status = self.orchestrator_factory.get_cli_agents_status()
        
        # Get framework status
        framework_status = self.orchestrator_factory.get_framework_status()
        
        # Get available frameworks
        available_frameworks = self.orchestrator_factory.list_available_frameworks()
        
        # Get available CLI agents
        available_agents = self.orchestrator_factory.list_available_cli_agents()
        
        return {
            'scenario': 'show_available_agents',
            'available_frameworks': available_frameworks,
            'available_cli_agents': available_agents,
            'framework_status': framework_status,
            'cli_agent_status': cli_status,
            'timestamp': asyncio.get_event_loop().time()
        }
    
    async def cross_framework_research(self) -> Dict[str, Any]:
        """Demonstrate cross-framework research capabilities"""
        print("   🔍 Running research across frameworks...")
        
        try:
            # Use multiple frameworks for research
            research_result = await self.orchestrator_factory.run_cross_framework_task(
                "Research the latest trends in AI and machine learning for 2024",
                {
                    'research_agent': 'langchain',
                    'analysis_agent': 'crewai',
                    'document_agent': 'llamaindex'
                }
            )
            
            # Use Gemini CLI for additional insights
            geminsight = await self.orchestrator_factory.run_cli_command(
                'gemini',
                'get_version'  # This would be a market analysis command
            )
            
            return {
                'scenario': 'cross_framework_research',
                'research_result': research_result,
                'gemini_insight': geminsight,
                'success': True,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            return {
                'scenario': 'cross_framework_research',
                'error': str(e),
                'success': False,
                'timestamp': asyncio.get_event_loop().time()
            }
    
    async def multi_agent_code_generation(self) -> Dict[str, Any]:
        """Demonstrate multi-agent code generation"""
        print("   � Generating code with multiple agents...")
        
        try:
            # Use CrewAI for initial code generation
            crewai_result = await self.orchestrator_factory.run_multi_agent_task(
                'crewai',
                'Generate a Python REST API with FastAPI and PostgreSQL integration',
                ['code_agent', 'research_agent']
            )
            
            # Use LangChain for additional features
            langchain_result = await self.orchestrator_factory.run_multi_agent_task(
                'langchain',
                'Add authentication and security features to the API',
                ['coding_agent']
            )
            
            # Use Codex CLI for specific implementations
            codex_result = await self.orchestrator_factory.run_cli_command(
                'codex',
                'generate_code',
                {
                    'language': 'python',
                    'framework': 'fastapi',
                    'features': ['JWT authentication', 'SQLAlchemy ORM']
                }
            )
            
            return {
                'scenario': 'multi_agent_code_generation',
                'crewai_code': crewai_result,
                'langchain_features': langchain_result,
                'codex_implementations': codex_result,
                'success': True,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            return {
                'scenario': 'multi_agent_code_generation',
                'error': str(e),
                'success': False,
                'timestamp': asyncio.get_event_loop().time()
            }
    
    async def comprehensive_code_review(self) -> Dict[str, Any]:
        """Demonstrate comprehensive code review"""
        print("   🔍 Reviewing code with multiple agents...")
        
        try:
            # Use GitHub Copilot for initial review
            copilot_review = await self.orchestrator_factory.run_cli_command(
                'github_copilot',
                'review_pr',
                {
                    'file_path': 'main.py',
                    'review_focus': ['quality', 'security', 'performance']
                }
            )
            
            # Use Claude Code for detailed analysis
            claude_review = await self.orchestrator_factory.run_cli_command(
                'claude',
                'analyze_code',
                {
                    'file_path': 'main.py',
                    'analysis_type': 'comprehensive'
                }
            )
            
            # Use Cursor CLI for specific improvements
            cursor_improvements = await self.orchestrator_factory.run_cli_command(
                'cursor',
                'review_code',
                {
                    'file_path': 'main.py',
                    'review_focus': ['optimization', 'readability']
                }
            )
            
            # Use Aider CLI for automated refactoring
            aider_refactoring = await self.orchestrator_factory.run_cli_command(
                'aider',
                'refactor_code',
                {
                    'file_path': 'main.py',
                    'refactoring_type': 'improve_naming'
                }
            )
            
            return {
                'scenario': 'comprehensive_code_review',
                'github_copilot_review': copilot_review,
                'claude_analysis': claude_review,
                'cursor_improvements': cursor_improvements,
                'aider_refactoring': aider_refactoring,
                'success': True,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            return {
                'scenario': 'comprehensive_code_review',
                'error': str(e),
                'success': False,
                'timestamp': asyncio.get_event_loop().time()
            }
    
    async def testing_validation(self) -> Dict[str, Any]:
        """Demonstrate testing and validation"""
        print("   🧪 Running tests and validation...")
        
        try:
            # Use OpenHands CLI for testing
            openhands_tests = await self.orchestrator_factory.run_cli_command(
                'openhands',
                'run_tests',
                {
                    'test_files': ['test_*.py'],
                    'coverage': True
                }
            )
            
            # Use LangChain for test generation
            test_generation = await self.orchestrator_factory.run_multi_agent_task(
                'langchain',
                'Generate unit and integration tests for the API',
                ['coding_agent']
            )
            
            # Use Aider CLI for test improvement
            test_improvement = await self.orchestrator_factory.run_cli_command(
                'aider',
                'add_tests',
                {
                    'file_path': 'main.py',
                    'test_framework': 'pytest'
                }
            )
            
            # Use Claude Code for security testing
            security_testing = await self.orchestrator_factory.run_cli_command(
                'claude',
                'analyze_code',
                {
                    'file_path': 'main.py',
                    'analysis_type': 'security'
                }
            )
            
            return {
                'scenario': 'testing_validation',
                'openhands_tests': openhands_tests,
                'test_generation': test_generation,
                'test_improvement': test_improvement,
                'security_testing': security_testing,
                'success': True,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            return {
                'scenario': 'testing_validation',
                'error': str(e),
                'success': False,
                'timestamp': asyncio.get_event_loop().time()
            }
    
    async def documentation_generation(self) -> Dict[str, Any]:
        """Demonstrate documentation generation"""
        print("   📝 Creating documentation...")
        
        try:
            # Use GitHub Copilot for README
            github_readme = await self.orchestrator_factory.run_cli_command(
                'github_copilot',
                'generate_documentation',
                {
                    'file_path': 'README.md',
                    'doc_type': 'comprehensive'
                }
            )
            
            # Use Aider CLI for inline docs
            inline_docs = await self.orchestrator_factory.run_cli_command(
                'aider',
                'generate_documentation',
                {
                    'file_path': 'main.py',
                    'doc_type': 'inline'
                }
            )
            
            # Use Gemini CLI for user guides
            user_guides = await self.orchestrator_factory.run_cli_command(
                'gemini',
                'generate_content',
                {
                    'topic': 'User Guide',
                    'format': 'markdown',
                    'style': 'user-friendly'
                }
            )
            
            # Use Claude Code for API documentation
            api_docs = await self.orchestrator_factory.run_cli_command(
                'claude',
                'generate_documentation',
                {
                    'file_path': 'api.py',
                    'doc_type': 'api'
                }
            )
            
            return {
                'scenario': 'documentation_generation',
                'github_readme': github_readme,
                'inline_docs': inline_docs,
                'user_guides': user_guides,
                'api_docs': api_docs,
                'success': True,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            return {
                'scenario': 'documentation_generation',
                'error': str(e),
                'success': False,
                'timestamp': asyncio.get_event_loop().time()
            }
    
    async def deployment_planning(self) -> Dict[str, Any]:
        """Demonstrate deployment planning"""
        print("   🚀 Planning deployment...")
        
        try:
            # Use OpenHands CLI for deployment scripts
            deployment_scripts = await self.orchestrator_factory.run_cli_command(
                'openhands',
                'generate_deployment_scripts',
                {
                    'platform': 'docker',
                    'framework': 'fastapi'
                }
            )
            
            # Use LangChain for deployment strategy
            deployment_strategy = await self.orchestrator_factory.run_multi_agent_task(
                'langchain',
                'Create deployment strategy and CI/CD pipeline',
                ['planning_agent']
            )
            
            # Use Claude Code for security analysis
            security_analysis = await self.orchestrator_factory.run_cli_command(
                'claude',
                'analyze_code',
                {
                    'file_path': 'Dockerfile',
                    'analysis_type': 'security'
                }
            )
            
            # Use GitHub Copilot for GitHub Actions
            github_actions = await self.orchestrator_factory.run_cli_command(
                'github_copilot',
                'generate_ci_cd',
                {
                    'platform': 'github',
                    'framework': 'fastapi'
                }
            )
            
            return {
                'scenario': 'deployment_planning',
                'deployment_scripts': deployment_scripts,
                'deployment_strategy': deployment_strategy,
                'security_analysis': security_analysis,
                'github_actions': github_actions,
                'success': True,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            return {
                'scenario': 'deployment_planning',
                'error': str(e),
                'success': False,
                'timestamp': asyncio.get_event_loop().time()
            }
    
    def generate_demo_summary(self, demo_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate demo summary"""
        scenarios = demo_results.get('scenarios', [])
        
        summary = {
            'total_scenarios': len(scenarios),
            'successful_scenarios': len([s for s in scenarios if s.get('success', False)]),
            'failed_scenarios': len([s for s in scenarios if not s.get('success', False)]),
            'success_rate': 0,
            'frameworks_used': [],
            'agents_used': [],
            'total_operations': 0
        }
        
        # Count operations and track usage
        for scenario in scenarios:
            if scenario.get('success', False):
                summary['total_operations'] += len(scenario) - 2  # Remove scenario and timestamp
                
                # Track frameworks
                if 'research_result' in scenario:
                    summary['frameworks_used'].append('langchain')
                    summary['frameworks_used'].append('crewai')
                    summary['frameworks_used'].append('llamaindex')
                
                # Track agents
                if 'github_copilot_review' in scenario:
                    summary['agents_used'].append('github_copilot')
                if 'claude_analysis' in scenario:
                    summary['agents_used'].append('claude')
                if 'cursor_improvements' in scenario:
                    summary['agents_used'].append('cursor')
                if 'aider_refactoring' in scenario:
                    summary['agents_used'].append('aider')
                if 'openhands_tests' in scenario:
                    summary['agents_used'].append('openhands')
                if 'gemini_insight' in scenario:
                    summary['agents_used'].append('gemini')
                if 'codex_implementations' in scenario:
                    summary['agents_used'].append('codex')
        
        # Calculate success rate
        summary['success_rate'] = summary['successful_scenarios'] / summary['total_scenarios'] if summary['total_scenarios'] > 0 else 0
        
        # Remove duplicates
        summary['frameworks_used'] = list(set(summary['frameworks_used']))
        summary['agents_used'] = list(set(summary['agents_used']))
        
        return summary

async def main():
    """Main demo execution"""
    print("🎬 Orchestrate CLI - Professional Demo")
    print("="*60)
    print("This demo showcases the power of Orchestrate CLI by demonstrating:")
    print("• 20+ AI coding assistants integration")
    print("• Cross-framework orchestration")
    print("• Multi-agent collaboration")
    print("• Professional workflow automation")
    print("• Comprehensive testing and validation")
    print("• Documentation generation")
    print("• Deployment planning")
    print("="*60)
    
    # Run demo
    demo = OrchestrateDemo()
    results = await demo.run_demo()
    
    # Save results
    results_file = Path("demo_results.json")
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Print summary
    summary = results.get('summary', {})
    print(f"\n📊 Demo Summary:")
    print(f"   Total Scenarios: {summary.get('total_scenarios', 0)}")
    print(f"   Successful Scenarios: {summary.get('successful_scenarios', 0)} ✅")
    print(f"   Failed Scenarios: {summary.get('failed_scenarios', 0)} ❌")
    print(f"   Success Rate: {summary.get('success_rate', 0):.1%}")
    print(f"   Frameworks Used: {', '.join(summary.get('frameworks_used', []))}")
    print(f"   Agents Used: {', '.join(summary.get('agents_used', []))}")
    print(f"   Total Operations: {summary.get('total_operations', 0)}")
    
    print(f"\n📄 Results saved to: {results_file}")
    
    # Show next steps
    print(f"\n🚀 Next Steps:")
    print(f"1. Configure your API keys in .env file")
    print(f"2. Run 'python main.py --help' to see all commands")
    print(f"3. Try: python main.py run langchain 'Create a simple Python app'")
    print(f"4. Test individual agents: python main.py agent gemini get_version")
    print(f"5. Run comprehensive tests: python test_all_cli.py")

if __name__ == "__main__":
    asyncio.run(main())