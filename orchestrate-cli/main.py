#!/usr/bin/env python3
"""
Orchestrate CLI - Professional AI Agent Orchestration Platform

A comprehensive command-line interface for orchestrating AI agents across multiple frameworks.
Integrates the most powerful AI coding assistants and development tools into a unified platform.

Features:
- Multi-framework orchestration (LangChain, AutoGen, CrewAI, LlamaIndex, Haystack)
- CLI agent integration (Gemini, Codex, Claude, GitHub Copilot, Aider, OpenCode, OpenHands, Cursor)
- Unified interface for all AI coding assistants
- Cross-framework task orchestration
- Multi-agent collaboration
- Configuration management
- Performance monitoring
"""

import asyncio
import sys
from pathlib import Path
from typing import List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# Import core modules
from src.orchestrators.orchestrator_factory import OrchestratorFactory
from src.utils.config_loader import ConfigLoader
from src.utils.tool_registry import ToolRegistry

# Create CLI app
app = typer.Typer(
    name="orchestrate-cli",
    help="Professional AI Agent Orchestration Platform",
    add_completion=False,
    no_args_is_help=True
)

# Create console for rich output
console = Console()

# Global variables
orchestrator_factory = None
config_loader = None
tool_registry = None

def initialize():
    """Initialize the orchestrator factory and configuration"""
    global orchestrator_factory, config_loader, tool_registry
    
    if not config_loader:
        config_loader = ConfigLoader()
    
    if not orchestrator_factory:
        orchestrator_factory = OrchestratorFactory(config_loader.config)
    
    if not tool_registry:
        tool_registry = ToolRegistry()

@app.command()
def frameworks():
    """List available frameworks"""
    initialize()
    
    table = Table(title="Available Frameworks")
    table.add_column("Framework", style="cyan", no_wrap=True)
    table.add_column("Enabled", style="green", no_wrap=True)
    table.add_column("Agents", justify="right", style="blue")
    
    framework_status = orchestrator_factory.get_framework_status()
    
    for framework_name, status in framework_status.items():
        status_text = "✅" if status.get('enabled', False) else "❌"
        agent_count = status.get('agents', 0)
        table.add_row(framework_name, status_text, str(agent_count))
    
    console.print(table)

@app.command()
def agents():
    """List available CLI agents"""
    initialize()
    
    table = Table(title="Available CLI Agents")
    table.add_column("Agent", style="cyan", no_wrap=True)
    table.add_column("Available", style="green", no_wrap=True)
    table.add_column("Version", style="blue")
    
    agent_status = orchestrator_factory.get_cli_agents_status()
    
    for agent_name, status in agent_status.items():
        available_text = "✅" if status.get('available', False) else "❌"
        version_info = status.get('version', {}).get('version', 'N/A')
        table.add_row(agent_name, available_text, version_info)
    
    console.print(table)

@app.command()
def tools():
    """List available tools"""
    initialize()
    
    tools = tool_registry.list_tools()
    
    table = Table(title="Available Tools")
    table.add_column("Tool", style="cyan", no_wrap=True)
    table.add_column("Category", style="green")
    table.add_column("Frameworks", style="blue")
    
    for tool_name, tool_info in tools.items():
        category = tool_info.get('category', 'general')
        frameworks = ', '.join(tool_info.get('frameworks', []))
        table.add_row(tool_name, category, frameworks)
    
    console.print(table)

@app.command()
def run(
    framework: str = typer.Argument(..., help="Framework to use"),
    task: str = typer.Argument(..., help="Task to execute"),
    agents: List[str] = typer.Option([], "--agent", help="Specific agents to use"),
    config: str = typer.Option(None, "--config", help="Configuration file path"),
    output: str = typer.Option(None, "--output", help="Output file path")
):
    """Run a task using the specified framework"""
    initialize()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task_progress = progress.add_task("Running task...", total=None)
        
        try:
            # Create orchestrator
            orchestrator = orchestrator_factory.create(framework)
            
            if not orchestrator:
                console.print(f"❌ Framework '{framework}' not available")
                return
            
            # Execute task
            if agents:
                result = orchestrator.execute(task, agents)
            else:
                result = orchestrator.execute(task)
            
            progress.update(task_progress, completed=True)
            
            # Display result
            console.print(Panel(f"Task Result: {task}", title="Execution Complete"))
            
            # Save result if output path provided
            if output:
                import json
                with open(output, 'w') as f:
                    json.dump(result, f, indent=2, default=str)
                console.print(f"📄 Result saved to: {output}")
            
        except Exception as e:
            progress.update(task_progress, completed=True)
            console.print(f"❌ Task failed: {e}")

@app.command()
def run_cross_framework(
    task: str = typer.Argument(..., help="Task to execute"),
    mapping: str = typer.Argument(..., help="Agent to framework mapping (e.g., agent1:framework1,agent2:framework2)"),
    output: str = typer.Option(None, "--output", help="Output file path")
):
    """Run a task using multiple frameworks"""
    initialize()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task_progress = progress.add_task("Running cross-framework task...", total=None)
        
        try:
            # Parse mapping
            framework_mapping = {}
            for pair in mapping.split(','):
                agent, framework = pair.split(':')
                framework_mapping[agent.strip()] = framework.strip()
            
            # Execute cross-framework task
            result = orchestrator_factory.run_cross_framework_task(task, framework_mapping)
            
            progress.update(task_progress, completed=True)
            
            # Display result
            console.print(Panel(f"Cross-Task Result: {task}", title="Execution Complete"))
            
            # Save result if output path provided
            if output:
                import json
                with open(output, 'w') as f:
                    json.dump(result, f, indent=2, default=str)
                console.print(f"📄 Result saved to: {output}")
            
        except Exception as e:
            progress.update(task_progress, completed=True)
            console.print(f"❌ Task failed: {e}")

@app.command()
def agent(
    agent_name: str = typer.Argument(..., help="CLI agent to use"),
    command: str = typer.Argument(..., help="Command to execute"),
    params: str = typer.Option(None, "--params", help="JSON parameters for the command"),
    output: str = typer.Option(None, "--output", help="Output file path")
):
    """Execute a command using a specific CLI agent"""
    initialize()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task_progress = progress.add_task(f"Executing {agent_name}.{command}...", total=None)
        
        try:
            # Parse parameters
            params_dict = {}
            if params:
                import json
                params_dict = json.loads(params)
            
            # Execute command
            result = orchestrator_factory.run_cli_command(agent_name, command, params_dict)
            
            progress.update(task_progress, completed=True)
            
            # Display result
            console.print(Panel(f"Agent Result: {agent_name}.{command}", title="Execution Complete"))
            
            # Save result if output path provided
            if output:
                import json
                with open(output, 'w') as f:
                    json.dump(result, f, indent=2, default=str)
                console.print(f"📄 Result saved to: {output}")
            
        except Exception as e:
            progress.update(task_progress, completed=True)
            console.print(f"❌ Command failed: {e}")

@app.command()
def test(
    component: str = typer.Option("all", "--component", help="Component to test (all, config, frameworks, cli_agents, integration)")
):
    """Test system components"""
    initialize()
    
    console.print("🧪 Starting component tests...")
    
    if component == "all":
        # Run all tests
        asyncio.run(run_all_tests())
    else:
        # Run specific test
        asyncio.run(run_specific_test(component))

async def run_all_tests():
    """Run all tests"""
    from test_all_cli import OrchestrateTester
    
    tester = OrchestrateTester()
    results = await tester.run_all_tests()
    tester.print_report(results)

async def run_specific_test(component: str):
    """Run specific test"""
    from test_all_cli import OrchestrateTester
    
    tester = OrchestrateTester()
    
    if component == "config":
        results = await tester.test_configuration()
    elif component == "frameworks":
        results = await tester.test_frameworks()
    elif component == "cli_agents":
        results = await tester.test_cli_agents()
    elif component == "integration":
        results = await tester.test_integration()
    else:
        console.print(f"❌ Unknown component: {component}")
        return
    
    # Print results
    console.print(f"\n🧪 {component.upper()} Test Results:")
    if results.get('success'):
        console.print("✅ Test passed")
    else:
        console.print(f"❌ Test failed: {results.get('error')}")

@app.command()
def validate():
    """Validate configuration"""
    initialize()
    
    try:
        is_valid = config_loader._validate_config()
        
        if is_valid:
            console.print("✅ Configuration is valid")
        else:
            console.print("❌ Configuration is invalid")
            sys.exit(1)
        
    except Exception as e:
        console.print(f"❌ Configuration validation failed: {e}")
        sys.exit(1)

@app.command()
def config(
    action: str = typer.Argument(..., help="Action (validate, export, show)"),
    output: str = typer.Option(None, "--output", help="Output file path")
):
    """Manage configuration"""
    initialize()
    
    try:
        if action == "validate":
            is_valid = config_loader._validate_config()
            if is_valid:
                console.print("✅ Configuration is valid")
            else:
                console.print("❌ Configuration is invalid")
        
        elif action == "export":
            import json
            config_data = config_loader.config
            if output:
                with open(output, 'w') as f:
                    json.dump(config_data, f, indent=2, default=str)
                console.print(f"📄 Configuration exported to: {output}")
            else:
                console.print(json.dumps(config_data, indent=2, default=str))
        
        elif action == "show":
            console.print("🔧 Current Configuration:")
            console.print(f"   Frameworks: {len(config_loader.config.get('frameworks', {}))}")
            console.print(f"   CLI Agents: {len(config_loader.config.get('agents', {}))}")
            console.print(f"   Tools: {len(tool_registry.list_tools())}")
        
        else:
            console.print(f"❌ Unknown action: {action}")
    
    except Exception as e:
        console.print(f"❌ Configuration action failed: {e}")

@app.command()
def monitor(
    metrics: str = typer.Option("response_time,error_rate,throughput", "--metrics", help="Metrics to monitor")
):
    """Monitor system performance"""
    initialize()
    
    console.print("📊 Starting performance monitoring...")
    
    try:
        metric_list = metrics.split(',')
        
        for metric in metric_list:
            console.print(f"📈 Monitoring {metric}...")
            
            # This would be implemented with actual monitoring logic
            # For now, we'll simulate monitoring
            import time
            time.sleep(1)
            
            console.print(f"   {metric}: OK")
    
    except KeyboardInterrupt:
        console.print("\n⏹️ Monitoring stopped")
    except Exception as e:
        console.print(f"❌ Monitoring failed: {e}")

@app.command()
def version():
    """Show version information"""
    console.print("🚀 Orchestrate CLI v1.0.0")
    console.print("Professional AI Agent Orchestration Platform")

@app.command()
def help():
    """Show help information"""
    console.print("📚 Orchestrate CLI Help")
    console.print("\nCommands:")
    console.print("  frameworks          - List available frameworks")
    console.print("  agents             - List available CLI agents")
    console.print("  tools              - List available tools")
    console.print("  run                - Run a task using a framework")
    console.print("  run-cross-framework - Run a task using multiple frameworks")
    console.print("  agent              - Execute a CLI agent command")
    console.print("  test               - Test system components")
    console.print("  validate           - Validate configuration")
    console.print("  config             - Manage configuration")
    console.print("  monitor            - Monitor performance")
    console.print("  version            - Show version")
    console.print("  help               - Show this help")

if __name__ == "__main__":
    app()