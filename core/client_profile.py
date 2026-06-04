"""ClientProfile — Contexte client persistant pour JarvisMax."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

_PROFILES_PATH = Path('/opt/jarvismax-app/workspace/client_profiles.jsonl')

@dataclass
class ClientProfile:
    name: str
    sector: str
    objectives: list = field(default_factory=list)
    communication_style: str = 'professionnel'
    mission_history: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    profile_id: str = ''

    def __post_init__(self):
        if not self.profile_id:
            import hashlib
            self.profile_id = hashlib.md5(f'{self.name}:{self.sector}'.encode(), usedforsecurity=False).hexdigest()[:8]

    def inject_context(self, goal: str) -> str:
        """Enrichit un goal avec le contexte client."""
        ctx = '\n\n[CONTEXTE CLIENT]\n'
        ctx += f'- Client: {self.name}\n'
        ctx += f'- Secteur: {self.sector}\n'
        if self.objectives:
            ctx += '- Objectifs: ' + ', '.join(self.objectives[:3]) + '\n'
        ctx += f'- Style de communication: {self.communication_style}\n'
        if self.mission_history:
            ctx += f'- Historique: {len(self.mission_history)} missions precedentes\n'
            for m in self.mission_history[-2:]:
                ctx += f'  * {m.get("goal","")[:60]} -> {m.get("status","")}\n'
        return goal + ctx

    def add_mission(self, goal: str, status: str, result_summary: str = ''):
        self.mission_history.append({
            'goal': goal[:100], 'status': status,
            'summary': result_summary[:200], 'ts': time.time()
        })
        if len(self.mission_history) > 50:
            self.mission_history = self.mission_history[-50:]

    def save(self):
        _PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PROFILES_PATH, 'a') as f:
            f.write(json.dumps(asdict(self), ensure_ascii=False) + '\n')

    @staticmethod
    def load(profile_id: str):
        if not _PROFILES_PATH.exists():
            return None
        for line in reversed(_PROFILES_PATH.read_text().splitlines()):
            try:
                d = json.loads(line)
                if d.get('profile_id') == profile_id:
                    flds = ClientProfile.__dataclass_fields__
                    return ClientProfile(**{k: v for k, v in d.items() if k in flds})
            except Exception:
                import logging as _lg; _lg.getLogger(__name__).debug("swallowed_exception", exc_info=True)
        return None

    @staticmethod
    def list_all():
        if not _PROFILES_PATH.exists():
            return []
        seen, profiles = set(), []
        for line in _PROFILES_PATH.read_text().splitlines():
            try:
                d = json.loads(line)
                pid = d.get('profile_id', '')
                if pid not in seen:
                    seen.add(pid)
                    flds = ClientProfile.__dataclass_fields__
                    profiles.append(ClientProfile(**{k: v for k, v in d.items() if k in flds}))
            except Exception:
                import logging as _lg; _lg.getLogger(__name__).debug("swallowed_exception", exc_info=True)
        return profiles


def seed_unity_clients():
    """Crée les profils des clients existants d'Unity."""
    clients = [
        ClientProfile(
            name='Client Jardinage', sector='jardinage',
            objectives=['visibilite locale', 'SEO Google Maps', 'contenu saisonnier'],
            communication_style='simple et chaleureux'),
        ClientProfile(
            name='Client Chauffage PAC', sector='chauffage pompes a chaleur',
            objectives=['ventes PAC air-eau', 'aides MaPrimeRenov', 'contrats maintenance'],
            communication_style='technique mais accessible'),
        ClientProfile(
            name='Client Ecommerce Chauffage', sector='ecommerce pieces chauffage',
            objectives=['SEO produits', 'fiches produits optimisees', 'taux conversion'],
            communication_style='professionnel ecommerce'),
    ]
    for p in clients:
        existing = ClientProfile.load(p.profile_id)
        if not existing:
            p.save()
            print(f'Cree: {p.name} [{p.profile_id}]')
        else:
            print(f'Existant: {p.name} [{p.profile_id}]')


if __name__ == '__main__':
    seed_unity_clients()
    print('\nProfils disponibles:')
    for p in ClientProfile.list_all():
        print(f'  [{p.profile_id}] {p.name} - {p.sector}')
