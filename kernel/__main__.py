"""
python -m kernel — Boot the BeaMax kernel standalone.

Usage:
  python -m kernel          # boot and show status
  python -m kernel --status # show runtime status
"""
import sys
import json


def main():
    from kernel.runtime.boot import boot_kernel
    runtime = boot_kernel()

    if "--status" in sys.argv:
        print(json.dumps(runtime.status(), indent=2))
    else:
        print(f"BeaMax Kernel v{runtime.version} booted")
        print(f"  Capabilities: {len(runtime.capabilities.list_all())}")
        print(f"  Memory: {runtime.memory.stats()['working_memory']['count']} working records")
        print(f"  Uptime: {runtime.uptime_seconds}s")


if __name__ == "__main__":
    main()
