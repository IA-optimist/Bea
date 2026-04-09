#!/usr/bin/env python3
"""
Lance la boucle proactive de JarvisMax en arrière-plan.
Usage: python scripts/run_proactive_agent.py
"""
import asyncio
import sys
sys.path.insert(0, ".")

async def main():
    from core.orchestration.proactive_loop import ProactiveAgent
    from core.orchestration.goal_registry import GoalRegistry

    registry = GoalRegistry()
    agent = ProactiveAgent(registry=registry)

    print("🚀 Proactive agent started. Checking goals every 30 minutes.")
    await agent.run_forever(interval_seconds=1800)

if __name__ == "__main__":
    asyncio.run(main())
