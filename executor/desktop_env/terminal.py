"""
JARVIS MAX v3 — Terminal (Stateful PTY)
Enveloppe un processus sous-jacent (bash via docker exec ou local) avec persistance.
"""
import asyncio
import os
import re
import uuid
import structlog

from executor.desktop_env.sandbox import DesktopEnvironment, DockerSandbox

log = structlog.get_logger()

# Délimiteur complexe pour savoir avec certitude quand une commande est terminée
# car on lit de manière asynchrone le stdout d'un process en continu.
_END_MARKER = f"__JARVIS_CMD_END_{uuid.uuid4().hex[:8]}__"


class PersistentTerminal:
    """
    Simule une session de terminal stateful.
    Toutes les commandes se suivent dans le même shell bash (les 'cd' et 'export' persistent).
    """
    def __init__(self, env: DesktopEnvironment):
        self._env = env
        self._process = None
        self._lock = asyncio.Lock()
        
    async def start(self) -> None:
        """Lance le processus Bash interactif."""
        if isinstance(self._env, DockerSandbox):
            if not self._env.container:
                self._env.start()
            
            # Sous docker, on lance `docker exec -i ... /bin/bash` via subprocess
            # pour avoir un pipe in/out constant. (L'alternative est docker.py socket stream)
            cmd = ["docker", "exec", "-i", self._env.container.name, "/bin/bash"]
        else:
            # Fallback Windows / Unix
            shell = "powershell.exe" if os.name == "nt" else "/bin/bash"
            cmd = [shell]

        log.info("terminal_starting", cmd=cmd)
        
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # On merge stdout/stderr
            cwd=str(self._env.workspace_path)
        )
        
        # Injection du setup initial
        if os.name != "nt" or isinstance(self._env, DockerSandbox):
            # Désactiver l'écho et les prompts fioritures, préparer la syntaxe.
            setup = "export PS1=''; stty -echo 2>/dev/null; echo 'ready'\n"
            if self._process.stdin:
                self._process.stdin.write(setup.encode())
                await self._process.stdin.drain()
            
            # Flush initial ("ready")
            if self._process.stdout:
                await self._process.stdout.readline()
                
    async def execute(self, command: str, timeout_s: int = 120) -> tuple[int, str]:
        """
        Exécute une commande et attend sa terminaison avec timeout.
        Retourne (exit_code, output).
        """
        if not self._process or self._process.returncode is not None:
            await self.start()
            
        if not self._process or not self._process.stdin or not self._process.stdout:
            return -1, "Processus terminal mort ou injoignable."

        async with self._lock:
            # On envoie la commande suivie d'un echo de notre marqueur et du code de retour.
            # Syntax bash (marche dans docker ou linux):
            if isinstance(self._env, DockerSandbox) or os.name != "nt":
                full_cmd = f"{command.strip()}\n_EXIT_CODE=$?\necho '{_END_MARKER}'${{_EXIT_CODE}}\n"
            else:
                # Syntax powershell fallback :
                full_cmd = f"{command.strip()}\n$lastexitcode\nWrite-Output '{_END_MARKER}'\n"

            try:
                self._process.stdin.write(full_cmd.encode('utf-8'))
                await self._process.stdin.drain()
            except BrokenPipeError:
                return -1, "Processus terminal cassé (Broken Pipe)."

            output_lines = []
            exit_code = 0
            
            # Lecture du flux jusqu'à rencontrer notre marqueur de fin (ou timeout)
            try:
                async def read_until_marker():
                    nonlocal exit_code
                    while True:
                        if not self._process or not self._process.stdout:
                            break
                        line_bytes = await self._process.stdout.readline()
                        if not line_bytes: # EOF
                            break
                            
                        line = line_bytes.decode('utf-8', errors='replace').rstrip('\r\n')
                        
                        # Détection du marqueur de fin
                        if _END_MARKER in line:
                            # Parse l'exit code attaché au marqueur (ex: __JARVIS_CMD_END_123456__0)
                            match = re.search(f"{_END_MARKER}(\\d+)", line)
                            if match:
                                exit_code = int(match.group(1))
                            break
                        
                        output_lines.append(line)

                await asyncio.wait_for(read_until_marker(), timeout=timeout_s)
            except asyncio.TimeoutError:
                # Le terminal prend trop de temps, on retourne ce qu'on a déjà lu
                # Si necessaire, on pourrait envoyer SIGINT au process enfant.
                output_lines.append(f"\n[Terminé de force après {timeout_s}s - Timeout]")
                exit_code = 124 # Bash timeout convention
            
            output = "\n".join(output_lines)
            
            # Sécurité tokens LLM : Si l'output est trop lourd (ex: build logs, npm install)
            # On tronque intelligemment (les 1000 premiers chars + les 2000 derniers)
            if len(output) > 5000:
                output = output[:1000] + "\n\n... [TRONQUÉ] ...\n\n" + output[-2000:]
                
            return exit_code, output.strip()

    def close(self):
        if self._process and self._process.returncode is None:
            try:
                self._process.kill()
            except Exception as _exc:
                log.warning("swallowed_exception", action="terminal_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            self._process = None
