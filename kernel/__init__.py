"""
kernel/ — BeaMax Cognitive OS Kernel.

The kernel is the minimal, stable, domain-agnostic core that everything
else is built on. It defines:

  - contracts/  — typed domain objects (Mission, Goal, Plan, Decision, etc.)
  - events/     — canonical event definitions and journal interface
  - capabilities/ — capability registry (what the system can do)
  - memory/     — typed memory interfaces (working, episodic, execution)
  - policy/     — risk evaluation, policy decisions, approval separation
  - runtime/    — kernel boot, lifecycle, runtime handle

The kernel does NOT contain:
  - Business logic or domain-specific workflows
  - UI or API adapters
  - Infrastructure (Docker, DB, cloud)
  - Experimental modules

Extensions (business, tools, agents) consume kernel contracts.
"""
__version__ = "0.1.0"
