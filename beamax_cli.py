#!/usr/bin/env python3
"""
BeaMax CLI — Simple command-line interface

Commands:
    beamax scan              Scan business opportunities
    beamax build <opp_id>    Build product from opportunity
    beamax deploy <dir>      Deploy product
    beamax status            System status
    beamax revenue           Revenue dashboard
    beamax logs [n]          Show last N log entries
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import structlog

log = structlog.get_logger("beamax.cli")


async def cmd_scan(args):
    """Scan business opportunities."""
    from core.meta_orchestrator import get_meta_orchestrator
    
    days_back = int(args[0]) if args else 30
    
    print(f"🔍 Scanning opportunities (last {days_back} days)...\n")
    
    orchestrator = get_meta_orchestrator()
    
    mission = {
        "type": "business.scan_opportunities",
        "params": {
            "days_back": days_back,
            "min_score": 60.0
        }
    }
    
    result = await orchestrator.dispatch_custom_mission(
        "business.scan_opportunities",
        mission
    )
    
    if result["status"] == "success":
        opportunities = result["opportunities"]
        summary = result["summary"]
        
        print(f"✅ Found {summary['total_found']} opportunities, {summary['high_score']} high-score\n")
        print("=" * 80)
        print(f"{'#':<4} {'SCORE':<8} {'SOURCE':<15} {'TITLE':<50}")
        print("=" * 80)
        
        for i, opp in enumerate(opportunities[:10], 1):
            title = opp['title'][:47] + "..." if len(opp['title']) > 50 else opp['title']
            print(f"{i:<4} {opp['score']:<8.1f} {opp['source']:<15} {title:<50}")
        
        print("=" * 80)
        print(f"\nTop sources: {', '.join(f'{k}({v})' for k, v in summary['top_sources'].items())}")
        print(f"Average score: {summary['avg_score']:.1f}")
    else:
        print(f"❌ Scan failed: {result.get('error', 'Unknown error')}")


async def cmd_build(args):
    """Build product from opportunity."""
    if not args:
        print("❌ Usage: beamax build <opportunity_title>")
        return
    
    from core.meta_orchestrator import get_meta_orchestrator
    
    title = " ".join(args)
    
    print(f"🏗️  Building product: {title}...\n")
    
    orchestrator = get_meta_orchestrator()
    
    mission = {
        "type": "business.build_product",
        "params": {
            "opportunity": {
                "title": title,
                "description": f"Product for {title}",
                "tags": [],
                "pain_points": []
            },
            "stack": "react_fastapi",
            "features": ["auth", "payments", "dashboard"]
        }
    }
    
    result = await orchestrator.dispatch_custom_mission(
        "business.build_product",
        mission
    )
    
    if result["status"] == "success":
        product = result["product"]
        artifacts = result["artifacts"]
        
        print("✅ Product built successfully!\n")
        print(f"Name: {product['name']}")
        print(f"Stack: {product['stack']}")
        print(f"Output: {product['output_dir']}\n")
        print("Artifacts:")
        for key, path in artifacts.items():
            print(f"  - {key}: {path}")
    else:
        print(f"❌ Build failed: {result.get('error', 'Unknown error')}")


async def cmd_deploy(args):
    """Deploy product."""
    if not args:
        print("❌ Usage: beamax deploy <product_dir> [platform]")
        return
    
    from core.meta_orchestrator import get_meta_orchestrator
    
    product_dir = args[0]
    platform = args[1] if len(args) > 1 else "vercel"
    
    print(f"🚀 Deploying {product_dir} to {platform}...\n")
    
    orchestrator = get_meta_orchestrator()
    
    mission = {
        "type": "business.deploy_product",
        "params": {
            "product_dir": product_dir,
            "platform": platform
        }
    }
    
    result = await orchestrator.dispatch_custom_mission(
        "business.deploy_product",
        mission
    )
    
    if result["status"] == "success":
        deployment = result["deployment"]
        print("✅ Deployed successfully!")
        print(f"URL: {deployment['url']}")
        print(f"Platform: {deployment['platform']}")
    else:
        print(f"❌ Deployment failed: {result.get('error', 'Unknown error')}")


async def cmd_status(args):
    """Show system status."""
    from core.meta_orchestrator import get_meta_orchestrator
    
    print("📊 BeaMax System Status\n")
    print("=" * 80)
    
    orchestrator = get_meta_orchestrator()
    
    # Get kernel status
    try:
        from kernel.runtime.boot import get_runtime
        kernel = get_runtime()
        print(f"Kernel:        RUNNING (uptime: {kernel.uptime_seconds}s)")
        print(f"Capabilities:  {len(kernel.capabilities.list_all())}")
    except Exception as e:
        print(f"Kernel:        ERROR ({str(e)[:50]})")
    
    # Get orchestrator status
    print("Orchestrator:  READY")
    print(f"Custom handlers: {len(orchestrator._custom_handlers)}")
    
    # Get active missions
    print(f"Active missions: {len(orchestrator._missions)}")
    
    print("=" * 80)


async def cmd_revenue(args):
    """Show revenue dashboard."""
    from core.meta_orchestrator import get_meta_orchestrator
    
    print("💰 Revenue Dashboard\n")
    
    orchestrator = get_meta_orchestrator()
    
    mission = {
        "type": "business.track_revenue",
        "params": {}
    }
    
    result = await orchestrator.dispatch_custom_mission(
        "business.track_revenue",
        mission
    )
    
    if result["status"] == "success":
        metrics = result["metrics"]
        
        print("=" * 80)
        print(f"MRR:              €{metrics['mrr']:,.2f}")
        print(f"ARR:              €{metrics['arr']:,.2f}")
        print(f"Total Customers:  {metrics['total_customers']}")
        print(f"Active Products:  {metrics['active_products']}")
        print(f"Churn Rate:       {metrics['churn_rate']:.1f}%")
        print(f"Growth Rate:      {metrics['growth_rate']:.1f}%")
        print("=" * 80)
    else:
        print(f"❌ Revenue tracking failed: {result.get('error', 'Unknown error')}")


async def cmd_logs(args):
    """Show recent logs."""
    n = int(args[0]) if args else 50
    
    log_file = Path.home() / ".beamax" / "logs" / "beamax.log"
    
    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        return
    
    lines = log_file.read_text().splitlines()
    
    print(f"📋 Last {n} log entries:\n")
    print("=" * 80)
    for line in lines[-n:]:
        print(line)
    print("=" * 80)


def show_help():
    """Show help message."""
    print(__doc__)


async def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1]
    args = sys.argv[2:]
    
    commands = {
        "scan": cmd_scan,
        "build": cmd_build,
        "deploy": cmd_deploy,
        "status": cmd_status,
        "revenue": cmd_revenue,
        "logs": cmd_logs,
        "help": lambda _: show_help(),
    }
    
    if command not in commands:
        print(f"❌ Unknown command: {command}\n")
        show_help()
        return
    
    try:
        await commands[command](args)
    except Exception as e:
        log.error("cli_command_failed", command=command, error=str(e))
        print(f"\n❌ Command failed: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
