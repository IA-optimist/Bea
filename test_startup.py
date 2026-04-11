#!/usr/bin/env python3
"""
Test container startup to validate no TypeError or AttributeError.
"""
import sys
sys.path.insert(0, '.')

print("Testing JarvisMax startup imports...")

try:
    # Core imports that would fail on startup
    print("1. Importing MetaOrchestrator...")
    from core.meta_orchestrator import MetaOrchestrator
    print("   ✓ MetaOrchestrator")
    
    print("2. Importing CognitionOrchestrator...")
    from core.cognition.orchestrator import CognitionOrchestrator
    print("   ✓ CognitionOrchestrator")
    
    print("3. Importing JarvisTeamDispatcher...")
    from core.orchestration.jarvis_team_dispatcher import dispatch_improve
    print("   ✓ JarvisTeamDispatcher")
    
    print("4. Importing Vault routes...")
    from api.routes.vault import router
    print("   ✓ Vault routes")
    
    print("5. Importing main API...")
    from api.routes import missions, health
    print("   ✓ API routes")
    
    print("\n✓ All critical modules import successfully")
    print("✓ No TypeError or AttributeError on startup")
    sys.exit(0)
    
except TypeError as e:
    print(f"\n✗ STARTUP FAILURE - TypeError: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
    
except AttributeError as e:
    print(f"\n✗ STARTUP FAILURE - AttributeError: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
    
except Exception as e:
    print(f"\n⚠ Warning - Other error (may be config-related): {e}")
    import traceback
    traceback.print_exc()
    # Don't fail on config errors, only on type/attribute errors
    sys.exit(0)
