"""
Wrapper to import the real docker SDK, bypassing /app/docker/ directory shadowing.
Use: from docker_sdk import docker
"""
import sys
import importlib.util
import os

def _load_real_docker():
    for path in sys.path:
        if not path or 'site-packages' not in path:
            continue
        init = os.path.join(path, 'docker', '__init__.py')
        if os.path.exists(init):
            spec = importlib.util.spec_from_file_location('_docker_sdk', init)
            spec.submodule_search_locations = [os.path.join(path, 'docker')]
            mod = importlib.util.module_from_spec(spec)
            mod.__path__ = [os.path.join(path, 'docker')]
            mod.__package__ = 'docker'
            spec.loader.exec_module(mod)
            return mod
    raise ImportError('docker SDK not found in site-packages')

docker = _load_real_docker()
__all__ = ['docker']
