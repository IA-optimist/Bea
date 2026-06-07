"""
BEA MAX v3 — File Editor (Surgical Edit)
Outil métier permettant aux agents de modifier le code sans réécrire le 
fichier en entier, limitant grandement la consommation de tokens et les erreurs d'indentation.
"""
from pathlib import Path
import structlog

log = structlog.get_logger()

class SurgicalEditor:
    """Éditeur de fichiers pour le Sandbox ou l'hôte."""
    
    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir).absolute()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, filepath: str) -> Path:
        """Résout un chemin absolu tout en garantissant qu'il reste dans le workspace."""
        # Eviter la traversée de répertoire type "../../etc/passwd"
        p = (self._base_dir / filepath).resolve()
        if self._base_dir not in p.parents and p != self._base_dir:
            raise PermissionError(f"Le chemin {filepath} est en dehors du workspace autorisé.")
        return p

    def read_file(self, filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
        """Lit un fichier avec numéros de lignes (1-indexed)."""
        p = self._resolve(filepath)
        if not p.is_file():
            return f"❌ Fichier non trouvé : {filepath}."
            
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            start = (start_line - 1) if start_line else 0
            end = end_line if end_line else len(lines)
            start = max(0, start)
            end = min(len(lines), end)
                
            output = [f"> [{filepath} lignes {start+1}-{end}]"]
            _nl = '\n'
            for i in range(start, end):
                output.append(f"{i + 1:4d} | {lines[i].rstrip(_nl)}")
            
            return "\n".join(output)
            
        except UnicodeDecodeError:
            return f"❌ Le fichier {filepath} semble être un binaire ou n'est pas en UTF-8."
        except Exception as e:
            return f"❌ Erreur de lecture : {str(e)}"

    def write_file(self, filepath: str, content: str) -> str:
        """Écrase ou crée un fichier complet."""
        p = self._resolve(filepath)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return f"✅ Fichier {filepath} sauvegardé ({len(content)} caractères)."
        except Exception as e:
            return f"❌ Erreur d'écriture : {str(e)}"

    def edit_file(self, filepath: str, old_str: str, new_str: str) -> str:
        """
        Remplace une occurrence exacte de `old_str` par `new_str`.
        C'est l'équivalent du "Aider diff mode" très apprécié par SWE-agent.
        """
        p = self._resolve(filepath)
        if not p.is_file():
            return f"❌ Le fichier {filepath} n'existe pas."
            
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()

            occurrences = content.count(old_str)
            if occurrences == 0:
                # On essaie d'être permissif avec les sauts de ligne finaux (Windows \r\n vs \n)
                if old_str.replace('\r\n', '\n') in content.replace('\r\n', '\n'):
                    return "❌ Conflit de retour chariot CRLF/LF détecté. Assurez-vous d'utiliser les sauts de ligne exacts."
                return "❌ Erreur : `old_str` introuvable dans le fichier. L'extrait doit correspondre **exactement** caractère par caractère."
            
            if occurrences > 1:
                return "❌ Erreur : `old_str` apparaît plusieurs fois dans le fichier. L'extrait doit être unique pour éviter un remplacement ambigu. Prends plus de lignes dans `old_str`."
                
            # Remplacement
            content = content.replace(old_str, new_str, 1)
            
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
                
            added = len(new_str.split('\n'))
            removed = len(old_str.split('\n'))
            log.info("surgical_edit_applied", file=filepath, added=added, removed=removed)
            
            return f"✅ Patch appliqué sur {filepath} (+{added} lignes, -{removed} lignes)."

        except Exception as e:
            log.error("surgical_edit_error", err=str(e)[:80])
            return f"❌ Erreur lors du remplacement : {str(e)}"

    def create_patch(self, filepath: str, patch_content: str) -> str:
        """Optionnel: Appliquer un VRAI unified diff (plus robuste si le LLM le gère bien)."""
        pass # A implémenter plus tard si besoin
