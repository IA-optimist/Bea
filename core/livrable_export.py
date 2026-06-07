"""
core/livrable_export.py — Export de livrables clients pour BeaMax.

Transforme le résultat d'une mission en livrable professionnel :
- Markdown propre (prêt à copier/envoyer)
- HTML pour impression/PDF (via wkhtmltopdf ou browser)
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


class LivrableExport:
    """Exporte les résultats de missions en livrables clients."""

    LIVRABLE_DIR = Path('/opt/beamax-app/workspace/livrables')

    def __init__(self):
        self.LIVRABLE_DIR.mkdir(parents=True, exist_ok=True)

    def to_markdown(
        self,
        mission_result: str,
        client_name: str = '',
        goal: str = '',
        date: str = '',
        mission_id: str = '',
    ) -> str:
        """
        Produit un fichier Markdown propre et professionnel.
        Directement présentable au client.
        """
        if not date:
            date = datetime.now().strftime('%d/%m/%Y')

        # Nettoyer le résultat brut
        content = self._clean_for_client(mission_result)

        # En-tête
        header = '# Rapport BeaMax\n\n'
        if client_name:
            header += f'**Client :** {client_name}  \n'
        header += f'**Date :** {date}  \n'
        if goal:
            header += f'**Mission :** {goal[:120]}  \n'
        if mission_id:
            header += f'**Référence :** {mission_id[:8]}  \n'
        header += '\n---\n\n'

        # Corps
        body = content

        # Pied de page
        footer = '\n\n---\n*Généré par BeaMax — Rapport confidentiel*\n'

        return header + body + footer

    def to_html(self, markdown_text: str) -> str:
        """
        Convertit le Markdown en HTML propre pour impression/PDF.
        Compatible wkhtmltopdf et navigateurs modernes.
        """
        # Conversion basique Markdown -> HTML
        html_body = markdown_text

        # Headers
        html_body = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_body, flags=re.MULTILINE)
        html_body = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_body, flags=re.MULTILINE)
        html_body = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_body, flags=re.MULTILINE)

        # Bold/italic
        html_body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_body)
        html_body = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_body)

        # Bullet lists
        lines = html_body.split('\n')
        result = []
        in_list = False
        for line in lines:
            if re.match(r'^[\*\-]\s+', line):
                if not in_list:
                    result.append('<ul>')
                    in_list = True
                item = re.sub(r'^[\*\-]\s+', '', line)
                result.append(f'  <li>{item}</li>')
            else:
                if in_list:
                    result.append('</ul>')
                    in_list = False
                result.append(line)
        if in_list:
            result.append('</ul>')
        html_body = '\n'.join(result)

        # Paragraphes
        html_body = re.sub(r'\n\n', '</p><p>', html_body)
        html_body = f'<p>{html_body}</p>'

        # Hr
        html_body = html_body.replace('---', '<hr>')

        return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rapport BeaMax</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; color: #333; line-height: 1.6; }}
  h1 {{ color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 10px; }}
  h2 {{ color: #16213e; margin-top: 30px; }}
  h3 {{ color: #0f3460; }}
  hr {{ border: 1px solid #eee; margin: 20px 0; }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 5px; }}
  strong {{ color: #1a1a2e; }}
  .footer {{ font-size: 0.85em; color: #888; margin-top: 40px; border-top: 1px solid #eee; padding-top: 10px; }}
</style>
</head>
<body>
{html_body}
</body>
</html>'''

    def save(
        self,
        mission_result: str,
        client_name: str,
        goal: str = '',
        mission_id: str = '',
    ) -> dict:
        """
        Sauvegarde le livrable en Markdown et HTML.
        Retourne les chemins des fichiers créés.
        """
        date = datetime.now().strftime('%Y-%m-%d')
        safe_client = re.sub(r'[^\w\-]', '_', client_name.lower())[:30]
        safe_mid = (mission_id or 'unknown')[:8]
        base = f'{date}_{safe_client}_{safe_mid}'

        md_text = self.to_markdown(mission_result, client_name, goal, mission_id=mission_id)
        html_text = self.to_html(md_text)

        md_path = self.LIVRABLE_DIR / f'{base}.md'
        html_path = self.LIVRABLE_DIR / f'{base}.html'

        md_path.write_text(md_text, encoding='utf-8')
        html_path.write_text(html_text, encoding='utf-8')

        return {
            'markdown': str(md_path),
            'html': str(html_path),
            'client': client_name,
            'date': date,
        }

    def _clean_for_client(self, text: str) -> str:
        """Nettoyage final pour présentation client."""
        # Supprimer préfixes techniques Bea
        text = re.sub(r'^[\u2705\u274c\u26a0\ufe0f\s]*\*{0,2}(?:SUCCESS|FAILED|PARTIAL)\*{0,2}\s*\n+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^1\)\s*Statut\s*:[^\n]*\n+', '', text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r'^2\)\s*Synth[eè]se\s*:\s*', '', text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r'^[0-9]+\)\s*Prochaines?\s*[eé]tapes?[^\n]*(?:\n[ \t]+[^\n]+)*', '', text, flags=re.IGNORECASE | re.MULTILINE)
        return text.strip()


# ── Usage direct ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    exporter = LivrableExport()

    test_result = """Le marche francais des services de jardinage represente 2.8 milliards euros en 2025.

**Points clés :**
- Marche en croissance de 8% par an
- 65% des particuliers font appel a un professionnel
- SEO local crucial: "jardinier Lyon", "entretien jardin [ville]"

**Structure site optimale :**
- Page accueil avec zone de chalandise
- Page services avec tarifs indicatifs
- Galerie realisations avec photos
- Contact avec formulaire et telephone click-to-call
"""

    paths = exporter.save(test_result, 'Client Jardinage Lyon', 'Analyse marche jardinage', 'test-001')
    print(f'Markdown: {paths["markdown"]}')
    print(f'HTML:     {paths["html"]}')
    print('\n--- Apercu Markdown ---')
    print(open(paths['markdown']).read()[:500])
