"""
Adaptateur Client pour contrôler OpenHands depuis BeaMax.
Permet d'invoquer l'immense Agent OpenHands (ex-OpenDevin) sur une tâche ultra complexe de longue durée,
en lui cédant temporairement le contrôle d'un workspace précis via CLI ou API.
"""
import asyncio
import sys
import structlog
from pathlib import Path

log = structlog.get_logger()

class OpenHandsLocalClient:
    """
    Pilote l'installation locale de OpenHands située dans Documents/OpenHands.
    On utilise l'exécution CLI headless (Headless Mode) supportée par OpenHands
    plutôt que de parser des WebSockets internes potentiellement volatiles.
    """
    def __init__(self, openhands_dir: str = "C:/Users/maxen/Documents/OpenHands"):
        self.openhands_dir = Path(openhands_dir).absolute()
        if not self.openhands_dir.exists():
            log.warning("openhands_repo_not_found", path=str(self.openhands_dir))

    async def run_delegated_mission(self, prompt: str, target_workspace: str, max_iterations: int = 50) -> tuple[bool, str]:
        """
        Lance une mission complète dans OpenHands.
        Args:
            prompt: La tâche de code hyper complète (générée par le BeaMax Planner).
            target_workspace: Le dossier où OpenHands doit coder.
        Returns:
            (Success, Log Résumé)
        """
        log.info("openhands_mission_delegated", prompt_preview=prompt[:50])
        
        target_path = Path(target_workspace).absolute()
        args = [
            sys.executable,
            "-m",
            "openhands.core.main",
            "-t",
            prompt,
            "-d",
            str(target_path),
            "-i",
            str(int(max_iterations)),
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self.openhands_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT # Redirige stderr vers stdout pour un seul flux
            )
            
            # Lecture du flux de sortie en temps réel
            stream_history = []
            
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                
                decoded_line = line.decode('utf-8', errors='replace').strip()
                if decoded_line:
                    stream_history.append(decoded_line)
                    # Afficher dynamiquement le logging de OpenHands (en évitant de polluer tout l'écran)
                    if "Exception" in decoded_line or "Error" in decoded_line:
                        log.error("openhands_stream", msg=decoded_line[:200])
                    else:
                        # Log de niveau DEBUG pour ne pas inonder la console BeaMax
                        log.debug("openhands_stream", msg=decoded_line[:200])
            
            # Attend la finition absolue du processus (bien qu'il dût être terminé avec eof)
            exit_code = await process.wait()
            success = exit_code == 0
            
            raw_output = "\n".join(stream_history)
            
            if success:
                log.info("openhands_mission_completed", exit_code=exit_code)
                return True, raw_output[-1500:] # Retourne la fin du log pour le Planner
            else:
                log.error("openhands_mission_failed", exit_code=exit_code)
                return False, f"Erreur critique OpenHands:\n{raw_output[-1000:]}"
                
        except Exception as e:
            log.exception("openhands_mission_crashed")
            return False, str(e)

if __name__ == "__main__":
    # Test unitaire rapide
    async def _test():
        client = OpenHandsLocalClient()
        success, out = await client.run_delegated_mission("Fais un echo hello world", "C:/Users/maxen/Documents/beamax/workspace")
        print(success, out)
    # asyncio.run(_test())
