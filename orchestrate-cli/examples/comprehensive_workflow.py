"""
Example: Comprehensive AI Agent Orchestration Workflow

This example demonstrates how to use all CLI agents together in a professional workflow.
It showcases the integration of multiple frameworks and AI coding assistants.
"""

import asyncio
import json
from typing import Dict, Any
from pathlib import Path

# Add src to path
import sys
sys.path.append(str(Path(__file__).parent / 'src'))

from src.orchestrators.orchestrator_factory import OrchestratorFactory
from src.utils.config_loader import ConfigLoader

class AIOrchestrationWorkflow:
    """Comprehensive AI agent orchestration workflow example"""

    def __init__(self):
        self.config_loader = ConfigLoader()
        self.orchestrator_factory = OrchestratorFactory(self.config_loader.config)

    async def comprehensive_workflow(self, project_description: str) -> Dict[str, Any]:
        """
        Run a comprehensive workflow using all available CLI agents and frameworks
        
        Args:
            project_description: Description of the project to build
            
        Returns:
            Dict containing workflow results
        """
        print(f"🚀 Starting comprehensive AI orchestration workflow...")
        print(f"📋 Project: {project_description}")

        workflow_results = {
            'project_description': project_description,
            'phases': [],
            'timestamp': asyncio.get_event_loop().time()
        }

        try:
            # Phase 1: Research and Planning
            print("\n📊 Phase 1: Research and Planning")
            research_phase = await self.research_phase(project_description)
            workflow_results['phases'].append(research_phase)

            # Phase 2: Architecture Design
            print("\n🏗️ Phase 2: Architecture Design")
            architecture_phase = await self.architecture_phase(research_phase)
            workflow_results['phases'].append(architecture_phase)

            # Phase 3: Code Generation
            print("\n💻 Phase 3: Code Generation")
            code_phase = await self.code_phase(architecture_phase)
            workflow_results['phases'].append(code_phase)

            # Phase 4: Code Review
            print("\n🔍 Phase 4: Code Review")
            review_phase = await self.review_phase(code_phase)
            workflow_results['phases'].append(review_phase)

            # Phase 5: Testing and Validation
            print("\n🧪 Phase 5: Testing and Validation")
            testing_phase = await self.testing_phase(code_phase)
            workflow_results['phases'].append(testing_phase)

            # Phase 6: Documentation
            print("\n📝 Phase 6: Documentation")
            documentation_phase = await self.documentation_phase(code_phase, review_phase)
            workflow_results['phases'].append(documentation_phase)

            # Phase 7: Deployment Setup
            print("\n🚀 Phase 7: Deployment Setup")
            deployment_phase = await self.deployment_phase(code_phase)
            workflow_results['phases'].append(deployment_phase)

            # Generate final summary
            workflow_results['summary'] = self.generate_summary(workflow_results)

            print("\n✅ Workflow completed successfully!")
            return workflow_results

        except Exception as e:
            print(f"❌ Workflow failed: {e}")
            workflow_results['error'] = str(e)
            return workflow_results

    async def research_phase(self, project_description: str) -> Dict[str, Any]:
        """Research phase using multiple AI agents"""
        print("   🔍 Gathering research...")

        # Use LangChain for general research
        research_result = await self.orchestrator_factory.run_cross_framework_task(
            f"Research current trends and best practices for: {project_description}",
            {
                'research_agent': 'langchain',
                'analysis_agent': 'crewai'
            }
        )

        # Use Gemini CLI for market analysis
        gemini_result = await self.orchestrator_factory.run_cli_command(
            'gemini',
            'get_version'  # This would normally be a market analysis command
        )

        return {
            'phase': 'research',
            'description': 'Research and analysis',
            'research_result': research_result,
            'gemini_analysis': gemini_result,
            'timestamp': asyncio.get_event_loop().time()
        }

    async def architecture_phase(self, research_phase: Dict[str, Any]) -> Dict[str, Any]:
        """Architecture design phase"""
        print("   🏗️ Designing architecture...")

        # Use CrewAI for architecture planning
        architecture_result = await self.orchestrator_factory.run_multi_agent_task(
            'crewai',
            "Create a detailed technical architecture based on research",
            ['planning_agent', 'analysis_agent']
        )

        # Use Claude Code for architectural review
        claude_result = await self.orchestrator_factory.run_cli_command(
            'claude',
            'analyze_code',  # This would analyze the architecture
            {
                'file_path': 'architecture.json',
                'analysis_type': 'architecture'
            }
        )

        return {
            'phase': 'architecture',
            'description': 'Architecture design and review',
            'architecture_result': architecture_result,
            'claude_review': claude_result,
            'timestamp': asyncio.get_event_loop().time()
        }

    async def code_phase(self, architecture_phase: Dict[str, Any]) -> Dict[str, Any]:
        """Code generation phase"""
        print("   💻 Generating code...")

        # Use LangChain for code generation
        langchain_result = await self.orchestrator_factory.run_multi_agent_task(
            'langchain',
            'Generate complete application code based on architecture',
            ['coding_agent']
        )

        # Use Codex CLI for specific implementations
        codex_result = await self.orchestrator_factory.run_cli_command(
            'codex',
            'generate_code',
            {
                'language': 'python',
                'framework': 'fastapi',
                'requirements': ['REST API', 'database integration']
            }
        )

        # Use Aider CLI for collaborative editing
        aider_result = await self.orchestrator_factory.run_cli_command(
            'aider',
            'edit_files',
            {
                'edits': [
                    {
                        'file_path': 'main.py',
                        'instructions': 'Add proper error handling and logging',
                        'changes': None
                    }
                ]
            }
        )

        return {
            'phase': 'code_generation',
            'description': 'Code generation and implementation',
            'langchain_code': langchain_result,
            'codex_implementations': codex_result,
            'aider_edits': aider_result,
            'timestamp': asyncio.get_event_loop().time()
        }

    async def review_phase(self, code_phase: Dict[str, Any]) -> Dict[str, Any]:
        """Code review phase"""
        print("   🔍 Reviewing code...")

        # Use GitHub Copilot CLI for code review
        copilot_result = await self.orchestrator_factory.run_cli_command(
            'github_copilot',
            'review_pr',
            {
                'file_path': 'main.py',
                'review_focus': ['quality', 'security', 'performance']
            }
        )

        # Use Cursor CLI for detailed analysis
        cursor_result = await self.orchestrator_factory.run_cli_command(
            'cursor',
            'review_code',
            {
                'file_path': 'main.py',
                'review_focus': ['bugs', 'security', 'optimization']
            }
        )

        # Use Claude Code for deep analysis
        claude_review = await self.orchestrator_factory.run_cli_command(
            'claude',
            'analyze_code',
            {
                'file_path': 'main.py',
                'analysis_type': 'comprehensive'
            }
        )

        return {
            'phase': 'code_review',
            'description': 'Code review and analysis',
            'github_copilot_review': copilot_result,
            'cursor_review': cursor_result,
            'claude_analysis': claude_review,
            'timestamp': asyncio.get_event_loop().time()
        }

    async def testing_phase(self, code_phase: Dict[str, Any]) -> Dict[str, Any]:
        """Testing and validation phase"""
        print("   🧪 Testing code...")

        # Use OpenHands CLI for testing
        openhands_result = await self.orchestrator_factory.run_cli_command(
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
            'Generate comprehensive unit and integration tests',
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

        return {
            'phase': 'testing',
            'description': 'Testing and validation',
            'openhands_tests': openhands_result,
            'test_generation': test_generation,
            'test_improvement': test_improvement,
            'timestamp': asyncio.get_event_loop().time()
        }

    async def documentation_phase(self, code_phase: Dict[str, Any], review_phase: Dict[str, Any]) -> Dict[str, Any]:
        """Documentation phase"""
        print("   📝 Creating documentation...")

        # Use GitHub Copilot CLI for documentation
        copilot_docs = await self.orchestrator_factory.run_cli_command(
            'github_copilot',
            'generate_documentation',
            {
                'file_path': 'README.md',
                'doc_type': 'comprehensive'
            }
        )

        # Use Aider CLI for inline documentation
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

        return {
            'phase': 'documentation',
            'description': 'Documentation creation',
            'github_copilot_docs': copilot_docs,
            'inline_documentation': inline_docs,
            'user_guides': user_guides,
            'timestamp': asyncio.get_event_loop().time()
        }

    async def deployment_phase(self, code_phase: Dict[str, Any]) -> Dict[str, Any]:
        """Deployment setup phase"""
        print("   🚀 Setting up deployment...")

        # Use OpenHands CLI for deployment scripts
        deployment_scripts = await self.orchestrator_factory.run_cli_command(
            'openhands',
            'generate_deployment_scripts',
            {
                'platform': 'docker',
                'framework': 'fastapi'
            }
        )

        # Use LangChain for deployment planning
        deployment_plan = await self.orchestrator_factory.run_multi_agent_task(
            'langchain',
            'Create deployment strategy and scripts',
            ['planning_agent']
        )

        # Use Claude Code for security analysis
        security_analysis = await self.orchestrator_factory.run_cli_command(
            'claude',
            'analyze_code',
            {
                'file_path': 'docker-compose.yml',
                'analysis_type': 'security'
            }
        )

        return {
            'phase': 'deployment',
            'description': 'Deployment setup and configuration',
            'deployment_scripts': deployment_scripts,
            'deployment_plan': deployment_plan,
            'security_analysis': security_analysis,
            'timestamp': asyncio.get_event_loop().time()
        }

    def generate_summary(self, workflow_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate workflow summary"""
        phases = workflow_results.get('phases', [])

        summary = {
            'total_phases': len(phases),
            'completed_phases': len([p for p in phases if 'error' not in p]),
            'failed_phases': len([p for p in phases if 'error' in p]),
            'total_agents_used': 0,
            'frameworks_used': set(),
            'agents_used': set(),
            'success_rate': 0
        }

        for phase in phases:
            # Count agents used
            if 'research_result' in phase:
                summary['total_agents_used'] += len(phase['research_result'].get('results', {}))
            if 'architecture_result' in phase:
                summary['total_agents_used'] += len(phase['architecture_result'].get('result', {}))
            if 'langchain_code' in phase:
                summary['total_agents_used'] += 1
            if 'codex_implementations' in phase:
                summary['total_agents_used'] += 1
            if 'aider_edits' in phase:
                summary['total_agents_used'] += 1
            if 'github_copilot_review' in phase:
                summary['total_agents_used'] += 1
            if 'cursor_review' in phase:
                summary['total_agents_used'] += 1
            if 'claude_analysis' in phase:
                summary['total_agents_used'] += 1
            if 'openhands_tests' in phase:
                summary['total_agents_used'] += 1
            if 'test_generation' in phase:
                summary['total_agents_used'] += 1
            if 'test_improvement' in phase:
                summary['total_agents_used'] += 1
            if 'github_copilot_docs' in phase:
                summary['total_agents_used'] += 1
            if 'inline_documentation' in phase:
                summary['total_agents_used'] += 1
            if 'user_guides' in phase:
                summary['total_agents_used'] += 1
            if 'deployment_scripts' in phase:
                summary['total_agents_used'] += 1
            if 'deployment_plan' in phase:
                summary['total_agents_used'] += 1
            if 'security_analysis' in phase:
                summary['total_agents_used'] += 1

            # Track frameworks and agents
            summary['frameworks_used'].update(['langchain', 'crewai', 'autogen', 'llamaindex', 'haystack'])
            summary['agents_used'].update(['gemini', 'codex', 'claude', 'github_copilot', 'aider', 'openhands', 'cursor'])

        # Calculate success rate
        summary['success_rate'] = summary['completed_phases'] / summary['total_phases'] if summary['total_phases'] > 0 else 0

        # Convert sets to lists for JSON serialization
        summary['frameworks_used'] = list(summary['frameworks_used'])
        summary['agents_used'] = list(summary['agents_used'])

        return summary

async def main():
    """Main execution function"""
    # Example usage
    workflow = AIOrchestrationWorkflow()

    # Run comprehensive workflow
    project_description = "Build a modern web application with FastAPI, PostgreSQL, and React"

    results = await workflow.comprehensive_workflow(project_description)

    # Save results
    with open('workflow_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n📄 Results saved to: workflow_results.json")

    # Print summary
    summary = results.get('summary', {})
    print(f"\n📊 Workflow Summary:")
    print(f"   Total Phases: {summary.get('total_phases', 0)}")
    print(f"   Completed Phases: {summary.get('completed_phases', 0)}")
    print(f"   Failed Phases: {summary.get('failed_phases', 0)}")
    print(f"   Success Rate: {summary.get('success_rate', 0):.1%}")
    print(f"   Total Agents Used: {summary.get('total_agents_used', 0)}")
    print(f"   Frameworks Used: {', '.join(summary.get('frameworks_used', []))}")
    print(f"   Agents Used: {', '.join(summary.get('agents_used', []))}")

if __name__ == "__main__":
    asyncio.run(main())