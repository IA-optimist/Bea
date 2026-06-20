#!/usr/bin/env python3
"""
End-to-end test for BeaMax cognition pipeline.
Tests ToT + self-confidence + active learning integration.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cognition.orchestrator import CognitionOrchestrator
from openai import OpenAI


async def test_cognition_pipeline():
    """Run E2E cognition test."""

    print("=== BeaMax Cognition E2E Test ===\n")

    # Setup LLM client
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not set")
        return

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

    # Create orchestrator
    orchestrator = CognitionOrchestrator(client)

    # Test mission (complex enough to trigger ToT)
    test_mission = {
        "mission_id": "test-e2e-001",
        "goal": "Design a scalable architecture for a real-time chat application with 1M concurrent users",
        "status": "RUNNING",
        "domain": "architecture",
        "agents": ["architect-design"],
        "result": ""  # Will be populated by orchestrator
    }

    print(f"📋 Mission: {test_mission['goal']}\n")

    # Execute with cognition
    try:
        print("🧠 Executing with cognition pipeline...")
        result = await orchestrator.execute_mission_with_cognition(
            test_mission,
            enable_tot=True,
            enable_confidence=True,
            enable_learning=True
        )

        print("\n✅ Cognition execution complete!\n")

        # Display results
        print("--- Results ---")
        print(f"ToT Used: {result['cognition']['tot_used']}")

        if "tot_plan" in result:
            print(f"ToT Confidence: {result['tot_plan']['confidence']:.2f}")
            print(f"Nodes Explored: {result['tot_plan']['nodes_explored']}")
            print(f"\nToT Solution:\n{result['tot_plan']['solution'][:300]}...")

        if "confidence_score" in result:
            print(f"\nSelf-Confidence: {result['confidence_score']:.2f}")
            print(f"Issues: {', '.join(result['confidence_issues']) if result['confidence_issues'] else 'None'}")

        if result['cognition']['was_corrected']:
            print("\n✏️ Output was auto-corrected")
            print(f"Improvement: {result.get('correction_improved', False)}")

        if "discovered_skill" in result:
            skill = result['discovered_skill']
            print(f"\n💡 Skill Discovered: {skill.get('skill_name')}")
            print(f"   Description: {skill.get('skill_description')}")

        # Performance report
        print("\n--- Performance Report ---")
        perf = orchestrator.get_performance_report()
        print(f"Total Missions: {perf['summary']['total_missions']}")
        print(f"Success Rate: {perf['summary']['success_rate']:.1%}")

        print("\n✅ All cognition systems operational!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_cognition_pipeline())
