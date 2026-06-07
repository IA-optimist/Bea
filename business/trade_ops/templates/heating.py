"""
BEA BUSINESS LAYER — Trade Ops : Template Chauffagiste / Plombier Chauffage
Template métier pré-configuré pour générer un agent IA spécialisé en chauffage.

Couvre : devis, maintenance, SAV, clients, planning techniciens.
"""
from __future__ import annotations

HEATING_SECTOR_CONTEXT = """\
Secteur : Plombier-Chauffagiste (TPE/PME, 1-20 techniciens)
Activités principales :
- Installation chaudières (gaz, fioul, pompe à chaleur, solaire)
- Maintenance annuelle (contrats d'entretien)
- SAV / dépannage urgence (disponibilité 24h/7j pour certains)
- Remplacement chauffe-eau, radiateurs, plancher chauffant
- Rénovation énergétique (RGE, MaPrimeRénov', CEE)

Clients typiques :
- Particuliers propriétaires (résidentiel 70%)
- Syndics/copropriétés (entretien collectif 20%)
- Tertiaire / PME locales (10%)

Douleurs principales :
1. Gestion des devis (lents, souvent non signés faute de suivi)
2. Planning techniciens / dispatching urgences
3. Commandes pièces (délais, ruptures, 3 fournisseurs différents)
4. Rapports d'intervention et bons de travaux
5. Suivi contrats d'entretien et relances
6. Comptabilité / facturation (souvent sur papier ou Excel)
7. Réponse aux demandes MaPrimeRénov' et CEE (complexe)

Outils utilisés typiquement :
- Sage, EBP (compta/devis)
- Synergys, Batigest (gestion chantier)
- WhatsApp (communication interne et clients !)
- Excel/papier (planning, bons)
- Téléphone (80% des prises de contact)
"""

HEATING_AGENT_CAPABILITIES = [
    "Générer des devis structurés pour installations et maintenances",
    "Planifier les interventions des techniciens selon disponibilité et localisation",
    "Répondre aux questions clients sur les pannes courantes (diagnostic niveau 1)",
    "Identifier les aides disponibles (MaPrimeRénov', CEE, éco-PTZ) selon situation client",
    "Rédiger des rapports d'intervention standardisés",
    "Relancer automatiquement les devis non signés (J+3, J+7, J+14)",
    "Vérifier la disponibilité des pièces chez les fournisseurs",
    "Calculer la rentabilité d'un chantier (heures * taux + matériaux + marge)",
    "Gérer les contrats d'entretien et alertes de renouvellement",
    "Rédiger des emails/SMS de confirmation d'intervention",
]

HEATING_KNOWLEDGE_BASE = {
    "maintenance_chaudiere": {
        "description": "Entretien annuel obligatoire chaudière gaz/fioul",
        "duree_min": 60,
        "prix_moyen": 120,
        "obligatoire": True,
        "periodicite": "annuelle",
        "points_controle": [
            "Nettoyage brûleur",
            "Contrôle électrodes d'allumage",
            "Vérification vase d'expansion",
            "Test sécurités (pression, température)",
            "Contrôle combustion (rendement, CO)",
            "Nettoyage échangeur",
            "Vérification robinetterie",
        ],
    },
    "depannage_pas_chaud": {
        "description": "Diagnostic chaudière ne chauffe plus",
        "questions_diagnostic": [
            "La chaudière s'allume-t-elle ? (voyant, bruit)",
            "Y a-t-il un code erreur affiché sur le tableau ?",
            "Les robinets thermostatiques sont-ils ouverts ?",
            "La pression du circuit est-elle entre 1 et 1.5 bar ?",
            "Le thermostat est-il réglé au-dessus de la température ambiante ?",
        ],
        "causes_frequentes": [
            "Pression trop basse → regonfler circuit",
            "Vase d'expansion défaillant",
            "Pompe de circulation bloquée",
            "Thermostat défectueux",
            "Filtre encrassé",
            "Sonde extérieure défaillante",
        ],
    },
    "aides_renovation": {
        "maprimerenov": {
            "description": "Aide État pour travaux rénovation énergétique",
            "plafond_pac_air_eau": 4000,
            "plafond_chaudiere_biomasse": 10000,
            "conditions": ["Propriétaire occupant", "Logement construit > 15 ans", "Artisan RGE"],
            "url": "https://www.maprimerenov.gouv.fr",
        },
        "cee": {
            "description": "Certificats d'Économie d'Énergie",
            "montant_variable": True,
            "cumulable_maprimerenov": True,
            "artisan_rge_requis": True,
        },
    },
    "tarifs_reference": {
        "main_oeuvre_horaire": {"min": 55, "max": 90, "unit": "€HT/h"},
        "deplacement":         {"forfait": 30, "unit": "€HT"},
        "installation_chaudiere_gaz": {"min": 800, "max": 1800, "unit": "€HT MO seule"},
        "installation_pac":    {"min": 2500, "max": 6000, "unit": "€HT MO seule"},
        "remplacement_ballon": {"min": 200, "max": 600, "unit": "€HT MO seule"},
    },
}

# Prompt système pré-configuré pour un agent chauffagiste
HEATING_SYSTEM_PROMPT_TEMPLATE = """\
Tu es l'assistant IA de {company_name}, entreprise de plomberie-chauffage.

Tu aides les artisans et techniciens à :
- Rédiger des devis professionnels rapidement
- Diagnostiquer les pannes courantes en posant les bonnes questions
- Informer les clients sur les aides disponibles (MaPrimeRénov', CEE)
- Rédiger des rapports d'intervention clairs
- Gérer les relances devis et confirmations d'intervention

Contexte entreprise :
- Zone d'intervention : {zone}
- Spécialités : {specialites}
- Certifications RGE : {rge}
- Tarif horaire : {tarif_horaire}€HT/h

RÈGLES :
- Sois professionnel, concis, pratique
- Les prix donnés sont HT (rappeler "hors taxes" ou "HT")
- Pour les devis, toujours demander : adresse, type de logement, âge de l'installation
- Pour les aides, toujours préciser les conditions et orienter vers le site officiel
- Ne jamais promettre de délai d'intervention sans vérification planning
"""


def get_heating_template(
    company_name: str = "l'entreprise",
    zone: str = "local",
    specialites: str = "chauffage, plomberie",
    rge: bool = True,
    tarif_horaire: int = 70,
) -> dict:
    """
    Retourne un dictionnaire de configuration pour un agent chauffagiste.
    Utilisé par TradeOpsAgent pour instancier un agent métier spécialisé.
    """
    return {
        "sector":        "chauffage",
        "template_name": "heating",
        "system_prompt": HEATING_SYSTEM_PROMPT_TEMPLATE.format(
            company_name=company_name,
            zone=zone,
            specialites=specialites,
            rge="Oui (RGE QualiPAC, Qualibat)" if rge else "Non",
            tarif_horaire=tarif_horaire,
        ),
        "capabilities":    HEATING_AGENT_CAPABILITIES,
        "knowledge_base":  HEATING_KNOWLEDGE_BASE,
        "sector_context":  HEATING_SECTOR_CONTEXT,
        "suggested_workflows": [
            "Prise de RDV → Diagnostic → Devis → Signature → Planning → Intervention → Facture",
            "Contrat entretien : Renouvellement automatique J-30 → Relance J-15 → Planification",
            "SAV Urgence : Appel → Qualification → Dispatch technicien disponible → Suivi",
        ],
    }
