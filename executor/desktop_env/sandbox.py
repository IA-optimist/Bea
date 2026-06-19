"""
BEA MAX v3 — Docker Sandbox
Environnement d'exécution isolé pour les missions autonomes.
"""
import os
import uuid
import shutil
import tempfile
import shlex
import subprocess
import structlog
from pathlib import Path

log = structlog.get_logger()
_COMMAND_METACHARS = ("|", "&&", "||", ";", ">", "<", "`", "$(", "\n", "\r")


def _parse_command(cmd: str) -> tuple[list[str] | None, str | None]:
    if any(meta in cmd for meta in _COMMAND_METACHARS):
        return None, "shell_metacharacters_not_allowed"
    try:
        args = shlex.split(cmd)
    except ValueError as exc:
        return None, f"invalid_command: {exc}"
    if not args:
        return None, "Commande vide"
    return args, None

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
        self.container_id = f"bea-sandbox-{uuid.uuid4().hex[:8]}"
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

        log.info("sandbox_starting", container=self.container_id, image=self.image)
        try:
            # Phase 12 : SÉCURITÉ COPY-ON-WRITE
            # Crée un dossier temporaire et y copie le workspace pour protéger l'hôte.
            # `ignore` list exclut les fichiers sensibles qui ne doivent JAMAIS
            # entrer dans le conteneur (audit Sprint 2).
            self.workspace_path.mkdir(parents=True, exist_ok=True)
            self.tmp_workspace = Path(tempfile.mkdtemp(prefix="bea_sandbox_"))
            _excluded = shutil.ignore_patterns(
                ".env", ".env.*", ".git", ".gitignore",
                "*.key", "*.pem", "secrets", "tokens.json", ".tokens.json",
            )
            shutil.copytree(
                str(self.workspace_path),
                str(self.tmp_workspace),
                dirs_exist_ok=True,
                ignore=_excluded,
            )

            # Sandbox hardening (audit Sprint 2 §4.1 P1) :
            #   - network_mode="none"  : pas d'accès réseau par défaut
            #     (opt-in via BEA_SANDBOX_ALLOW_NETWORK=1 → bridge)
            #   - read_only=True       : root filesystem read-only
            #   - tmpfs /tmp           : tmpfs writable pour /tmp
            #   - mem_limit / pids_limit / cap_drop=ALL / no-new-privileges
            _net = "bridge" if os.getenv("BEA_SANDBOX_ALLOW_NETWORK") == "1" else "none"
            self.container = self._client.containers.run(
                image=self.image,
                name=self.container_id,
                command="tail -f /dev/null",  # Maintient le conteneur en vie
                volumes={str(self.tmp_workspace): {'bind': '/workspace', 'mode': 'rw'}},
                working_dir="/workspace",
                detach=True,
                auto_remove=True,
                network_mode=_net,
                read_only=True,
                tmpfs={"/tmp": "size=64m,mode=1777", "/run": "size=8m"},
                mem_limit="512m",
                memswap_limit="512m",
                pids_limit=128,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
            )
            log.info(
                "sandbox_started",
                container=self.container_id,
                secure_cow=True,
                network=_net,
                read_only=True,
            )
        except Exception as _img_e:
            if "ImageNotFound" not in type(_img_e).__name__:
                log.error("sandbox_start_failed", err=str(_img_e)[:100])
                raise
            log.info("sandbox_pulling_image", image=self.image)
            self._client.images.pull(self.image)
            self.start()  # Ré-essaie après pull

    def sync_to_host(self) -> None:
        """
        Applique les changements réalisés dans la Sandbox sur le vrai workspace hôte.
        Ne doit être appelé que si l'agent a terminé la tâche avec succès.
        """
        if self.tmp_workspace and self.tmp_workspace.exists():
            log.info("sandbox_syncing_to_host", source=str(self.tmp_workspace), target=str(self.workspace_path))
            shutil.copytree(str(self.tmp_workspace), str(self.workspace_path), dirs_exist_ok=True)

    def execute(self, cmd: str, timeout: int = 30) -> tuple[int, str]:
        """
        Exécute une commande de façon isolée (stateless).

        Args:
            cmd: Command string (no shell metacharacters).
            timeout: Seconds before the killswitch fires (default 30s).
                     On timeout, the container is SIGKILL-ed and (-1, reason)
                     is returned. Set 0 to disable.

        NB : Pour un shell stateful (avec cd et variables d'env qui persistent),
        il faut utiliser terminal.py qui gère un flux stdin/stdout continu.
        """
        if not self.container:
            return -1, "Conteneur non démarré"

        log.debug("sandbox_exec", cmd=cmd[:50], timeout=timeout)
        args, parse_error = _parse_command(cmd)
        if parse_error:
            return -1, parse_error

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                self.container.exec_run, args, workdir="/workspace"
            )
            try:
                exit_code, output = future.result(timeout=timeout or None)
                return exit_code, output.decode("utf-8", errors="replace")
            except concurrent.futures.TimeoutError:
                log.warning(
                    "sandbox_exec_timeout",
                    cmd=cmd[:50],
                    timeout=timeout,
                )
                self.kill()
                return -1, f"sandbox_killed: command exceeded {timeout}s timeout"
            except Exception as exc:
                return -1, f"Erreur d'exécution Sandbox: {str(exc)}"

    def kill(self) -> None:
        """Killswitch: SIGKILL the container immediately (runaway task guard)."""
        if self.container:
            log.warning("sandbox_killswitch_activated", container=self.container_id)
            try:
                self.container.kill()
            except Exception as exc:
                log.error("sandbox_kill_failed", err=str(exc)[:80])
            finally:
                self.container = None

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
    BEA_ALLOW_LOCAL_SANDBOX=1, sinon toute exécution est refusée.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path).absolute()
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self._enabled = os.getenv("BEA_ALLOW_LOCAL_SANDBOX", "0") == "1"

    def start(self) -> None:
        if not self._enabled:
            log.error("sandbox_local_fallback_refused",
                      reason="BEA_ALLOW_LOCAL_SANDBOX!=1, refuse d'ex\u00e9cuter sur l'h\u00f4te")
            return
        log.warning("sandbox_local_fallback_started", warning="NON-ISOLE, RISQUE DE SECURITE")

    def execute(self, cmd: str) -> tuple[int, str]:
        if not self._enabled:
            return -1, "LocalFallbackSandbox d\u00e9sactiv\u00e9 (BEA_ALLOW_LOCAL_SANDBOX!=1)"
        log.debug("sandbox_local_exec", cmd=cmd[:50])
        try:
            args, parse_error = _parse_command(cmd)
            if parse_error:
                return -1, parse_error
            result = subprocess.run(
                args,
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
