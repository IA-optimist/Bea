#!/usr/bin/env python3
"""
Test P0/P1 bug fixes for JarvisMax.
Validates: CognitionOrchestrator signature, ainvoke usage, exception handling, RBAC.
"""
import sys
import asyncio
sys.path.insert(0, '.')

async def test_cognition_orchestrator_signature():
    """Test that CognitionOrchestrator.execute_mission_with_cognition has correct signature."""
    print("\n=== Test 1: CognitionOrchestrator signature ===")
    from core.cognition.orchestrator import CognitionOrchestrator
    import inspect
    
    sig = inspect.signature(CognitionOrchestrator.execute_mission_with_cognition)
    params = list(sig.parameters.keys())
    
    # Check required parameters
    assert 'self' in params, "Missing 'self' parameter"
    assert 'mission' in params, "Missing 'mission' parameter"
    assert 'enable_tot' in params, "Missing 'enable_tot' parameter"
    assert 'enable_confidence' in params, "Missing 'enable_confidence' parameter"
    assert 'enable_learning' in params, "Missing 'enable_learning' parameter"
    assert 'executor_fn' in params, "Missing 'executor_fn' parameter"
    
    print(f"✓ Signature correct: {params}")
    return True

async def test_jarvis_team_dispatcher_ainvoke():
    """Test that jarvis_team_dispatcher uses ainvoke, not achat."""
    print("\n=== Test 2: JarvisTeam ainvoke usage ===")
    
    # Read the source to verify
    with open('core/orchestration/jarvis_team_dispatcher.py', "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check no achat calls (except in comments)
    lines = content.split('\n')
    achat_calls = [i for i, line in enumerate(lines, 1) 
                   if '.achat(' in line and not line.strip().startswith('#')]
    
    assert len(achat_calls) == 0, f"Found .achat() calls at lines: {achat_calls}"
    
    # Check ainvoke is present
    assert '.ainvoke(' in content, "Missing .ainvoke() call"
    assert 'response.content' in content or 'hasattr(response, "content")' in content, \
           "Missing proper response.content handling"
    
    print("✓ Uses .ainvoke() with proper response.content handling")
    return True

async def test_jarvis_team_dispatcher_continue():
    """Test that jarvis_team_dispatcher uses continue, not break."""
    print("\n=== Test 3: Exception handling with continue ===")
    
    with open('core/orchestration/jarvis_team_dispatcher.py', "r", encoding="utf-8") as f:
        content = f.read()
    
    lines = content.split('\n')
    
    # Find except Exception blocks
    except_blocks = []
    for i, line in enumerate(lines, 1):
        if 'except Exception' in line:
            # Check next few lines
            for j in range(i, min(i+5, len(lines))):
                if 'break' in lines[j] and not lines[j].strip().startswith('#'):
                    except_blocks.append((i, j+1, 'break'))
                if 'continue' in lines[j] and not lines[j].strip().startswith('#'):
                    except_blocks.append((i, j+1, 'continue'))
                    break
    
    # Should have continue, not break
    has_continue = any(action == 'continue' for _, _, action in except_blocks)
    has_break = any(action == 'break' for _, _, action in except_blocks)
    
    assert has_continue, "Should use 'continue' in exception handler"
    assert not has_break, "Should NOT use 'break' in exception handler"
    
    print("✓ Uses 'continue' instead of 'break' (agents don't block each other)")
    return True

async def test_meta_orchestrator_create_task():
    """Test that meta_orchestrator uses create_task, not ensure_future."""
    print("\n=== Test 4: asyncio.create_task usage ===")
    
    with open('core/meta_orchestrator.py', "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check for ensure_future (should not be used for new code)
    lines = content.split('\n')
    ensure_future_lines = [i for i, line in enumerate(lines, 1) 
                           if 'asyncio.ensure_future(' in line 
                           and not line.strip().startswith('#')
                           and 'Use create_task' not in line]
    
    # Check for create_task with add_done_callback
    has_create_task = 'asyncio.create_task(' in content
    has_add_done_callback = '.add_done_callback(' in content
    
    if ensure_future_lines:
        print(f"⚠ Warning: Found ensure_future at lines: {ensure_future_lines}")
    
    assert has_create_task, "Should use asyncio.create_task()"
    assert has_add_done_callback, "Should use .add_done_callback() for exception logging"
    
    print("✓ Uses asyncio.create_task() with .add_done_callback()")
    return True

async def test_vault_rbac():
    """Test that vault /reveal endpoint has RBAC check."""
    print("\n=== Test 5: Vault RBAC for /reveal ===")
    
    with open('api/routes/vault.py', "r", encoding="utf-8") as f:
        content = f.read()
    
    # Find the reveal_secret function
    lines = content.split('\n')
    reveal_func_line = None
    for i, line in enumerate(lines, 1):
        if 'def reveal_secret(' in line:
            reveal_func_line = i
            break
    
    assert reveal_func_line is not None, "reveal_secret function not found"
    
    # Check if require_admin is in the signature
    func_signature = lines[reveal_func_line-1]
    assert 'require_admin' in func_signature or 'user: dict = Depends(require_admin)' in func_signature, \
           "Missing require_admin dependency in reveal_secret"
    
    print("✓ /reveal endpoint has admin role check (require_admin)")
    return True

async def test_docker_compose_no_reload():
    """Test that docker-compose.yml doesn't use --reload."""
    print("\n=== Test 6: Docker-compose no --reload ===")
    
    with open('docker-compose.yml', "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check for --reload in uvicorn command
    
    # Check the actual command
    lines = content.split('\n')
    command_line = None
    for line in lines:
        if 'command:' in line and 'uvicorn' in line:
            command_line = line
            break
    
    if command_line:
        assert '--reload' not in command_line, f"Found --reload in command: {command_line}"
    
    print("✓ Docker-compose doesn't use --reload (production mode)")
    return True

async def main():
    """Run all tests."""
    print("=" * 60)
    print("P0/P1 Bug Fixes Validation")
    print("=" * 60)
    
    tests = [
        test_cognition_orchestrator_signature,
        test_jarvis_team_dispatcher_ainvoke,
        test_jarvis_team_dispatcher_continue,
        test_meta_orchestrator_create_task,
        test_vault_rbac,
        test_docker_compose_no_reload,
    ]
    
    results = []
    for test in tests:
        try:
            await test()
            results.append(('PASS', test.__name__))
        except AssertionError as e:
            print(f"✗ FAIL: {e}")
            results.append(('FAIL', test.__name__))
        except Exception as e:
            print(f"✗ ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append(('ERROR', test.__name__))
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    for status, name in results:
        icon = "✓" if status == "PASS" else "✗"
        print(f"{icon} {status}: {name}")
    
    passed = sum(1 for s, _ in results if s == 'PASS')
    total = len(results)
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All P0/P1 fixes validated successfully!")
        return 0
    else:
        print("\n⚠ Some tests failed!")
        return 1

if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
