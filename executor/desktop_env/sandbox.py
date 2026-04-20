"""
JARVIS MAX v3 — Docker Sandbox
Environnement d'exécution isolé pour les missions autonomes.
"""
import os
import uuid
import shutil
import tempfile
import structlog
from pathlib import Path

log = structlog.get_logger()

class DesktopEnvironment:
    """Interface pour l'environnement d'exécution."""
    def start(self) -> None: ...
    def execute(self, cmd: str) -> tuple[int, str]: ...
    def stop(self) -> None: ...

class DockerSandbox(DesktopEnvironment):
    """Exécution isolée dans un conteneur Docker avec montage du workspace."""
    
    def __init__(self, workspace_path: str, image: str = "python:3.11-slim-bookworm"):
        self.workspace_path = Path(workspace_path).absolute()
        self.image = image
        self.container_id = f"jarvis-sandbox-{uuid.uuid4().hex[:8]}"
        self.container = None
        self._client = None
        self.tmp_workspace = None # Phase 12: Copy-on-Write tmp dir
        self._available = self._check_docker()

    def _check_docker(self) -> bool:
        try:
            from docker_sdk import docker
            self._client = docker.from_env()
            self._client.ping()
            return True
        except Exception as e:
            log.debug("sandbox_docker_unavailable", err=str(e)[:60])
            return False

    def is_available(self) -> bool:
        return self._available

    def start(self) -> None:
        if not self.is_available():
            raise RuntimeError("Docker non disponible (daemon ou librairie manquante).")

        from docker_sdk import docker
        log.info("sandbox_starting", container=self.container_id, image=self.image)
        try:
            # Phase 12 : SÉCURITÉ COPY-ON-WRITE
            # Crée un dossier temporaire et y copie le workspace pour protéger l'hôte
            self.workspace_path.mkdir(parents=True, exist_ok=True)
            self.tmp_workspace = Path(tempfile.mkdtemp(prefix="jarvis_sandbox_"))
            shutil.copytree(str(self.workspace_path), str(self.tmp_workspace), dirs_exist_ok=True)
            
            self.container = self._client.containers.run(
                image=self.image,
                name=self.container_id,
                command="tail -f /dev/null",  # Maintient le conteneur en vie
                volumes={str(self.tmp_workspace): {'bind': '/workspace', 'mode': 'rw'}},
                working_dir="/workspace",
                detach=True,
                auto_remove=True,
                network_mode="bridge"
            )
            log.info("sandbox_started", container=self.container_id, secure_cow=True)
        except Exception as _img_e:
            if "ImageNotFound" not in type(_img_e).__name__: raise
            _dummy = None  # noqa
            log.info("sandbox_pulling_image", image=self.image)
            self._client.images.pull(self.image)
            self.start()  # Ré-essaie après pull
        except Exception as e:
            log.error("sandbox_start_failed", err=str(e)[:100])
            raise

    def sync_to_host(self) -> None:
        """
        Applique les changements réalisés dans la Sandbox sur le vrai workspace hôte.
        Ne doit être appelé que si l'agent a terminé la tâche avec succès.
        """
        if self.tmp_workspace and self.tmp_workspace.exists():
            log.info("sandbox_syncing_to_host", source=str(self.tmp_workspace), target=str(self.workspace_path))
            shutil.copytree(str(self.tmp_workspace), str(self.workspace_path), dirs_exist_ok=True)

    def execute(self, cmd: str) -> tuple[int, str]:
        """
        Exécute une commande de façon isolée (stateless).
        NB : Pour un shell stateful (avec cd et variables d'env qui persistent),
        il faut utiliser terminal.py qui gère un flux stdin/stdout continu.
        """
        if not self.container:
            return -1, "Conteneur non démarré"
        
        log.debug("sandbox_exec", cmd=cmd[:50])
        try:
            exit_code, output = self.container.exec_run(
                cmd=["/bin/bash", "-c", cmd],
                workdir="/workspace"
            )
            return exit_code, output.decode("utf-8", errors="replace")
        except Exception as e:
            return -1, f"Erreur d'exécution Sandbox: {str(e)}"

    def stop(self) -> None:
        if self.container:
            log.info("sandbox_stopping", container=self.container_id)
            try:
                self.container.stop(timeout=2)
            except Exception as e:
                log.warning("sandbox_stop_error", err=str(e)[:80])
            finally:
                self.container = None
                
        # Nettoyage de l'espace temporaire (Copy-On-Write)
        if self.tmp_workspace and self.tmp_workspace.exists():
            shutil.rmtree(str(self.tmp_workspace), ignore_errors=True)

class LocalFallbackSandbox(DesktopEnvironment):
    """Fallback si Docker est indisponible : Exécution sur la machine hôte.

    Non isolé : RCE possible. Doit être activé explicitement via
    JARVIS_ALLOW_LOCAL_SANDBOX=1, sinon toute exécution est refusée.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path).absolute()
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self._enabled = os.getenv("JARVIS_ALLOW_LOCAL_SANDBOX", "0") == "1"

    def start(self) -> None:
        if not self._enabled:
            log.error("sandbox_local_fallback_refused",
                      reason="JARVIS_ALLOW_LOCAL_SANDBOX!=1, refuse d'ex\u00e9cuter sur l'h\u00f4te")
            return
        log.warning("sandbox_local_fallback_started", warning="NON-ISOLE, RISQUE DE SECURITE")

    def execute(self, cmd: str) -> tuple[int, str]:
        if not self._enabled:
            return -1, "LocalFallbackSandbox d\u00e9sactiv\u00e9 (JARVIS_ALLOW_LOCAL_SANDBOX!=1)"
        import subprocess
        log.debug("sandbox_local_exec", cmd=cmd[:50])
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=120
            )
            out = result.stdout + ("\n" + result.stderr if result.stderr else "")
            return result.returncode, out.strip()
        except Exception as e:
            return -1, str(e)
            
    def stop(self) -> None:
        pass
