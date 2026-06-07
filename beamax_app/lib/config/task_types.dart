/// BeaMax — Canonical Task Type Definitions
/// Single source of truth for mission task types across all screens.
///
/// Each entry maps a backend skill key to its French label, icon codepoint,
/// and composer hint text.
library task_types;

const List<Map<String, dynamic>> kTaskTypes = [
  {'key': 'libre',                  'label': 'Libre',               'icon': 0xe3c9, 'hint': 'Décrivez votre mission ou posez une question...'},
  {'key': 'market_research',        'label': 'Recherche marché',    'icon': 0xe8b6, 'hint': 'Ex : Analysez le marché des outils IA pour PME en France…'},
  {'key': 'competitor_analysis',    'label': 'Concurrents',         'icon': 0xe14f, 'hint': 'Ex : Analysez les concurrents de [votre produit/service]…'},
  {'key': 'positioning',            'label': 'Positionnement',      'icon': 0xe1e0, 'hint': 'Ex : Définissez le positionnement de [votre offre]…'},
  {'key': 'pricing_strategy',       'label': 'Stratégie prix',      'icon': 0xe263, 'hint': 'Ex : Proposez une grille tarifaire pour [votre produit]…'},
  {'key': 'growth_plan',            'label': 'Plan de croissance',  'icon': 0xe6de, 'hint': 'Ex : Créez un plan de croissance sur 6 mois…'},
  {'key': 'acquisition_strategy',   'label': 'Acquisition',         'icon': 0xe7fe, 'hint': 'Ex : Définissez une stratégie d\'acquisition pour [cible client]…'},
  {'key': 'value_proposition',      'label': 'Valeur client',       'icon': 0xe838, 'hint': 'Ex : Formulez la proposition de valeur de [votre offre]…'},
  {'key': 'offer_design',           'label': 'Design offre',        'icon': 0xe19c, 'hint': 'Ex : Concevez une offre commerciale pour [votre marché cible]…'},
  {'key': 'customer_persona',       'label': 'Persona client',      'icon': 0xe7fd, 'hint': 'Ex : Créez des personas clients pour [votre produit]…'},
  {'key': 'copywriting',            'label': 'Copywriting',         'icon': 0xe22b, 'hint': 'Ex : Rédigez un texte de vente percutant pour [votre offre]…'},
  {'key': 'funnel_design',          'label': 'Funnel',              'icon': 0xef4f, 'hint': 'Ex : Concevez un funnel de conversion pour [votre offre]…'},
  {'key': 'landing_structure',      'label': 'Landing page',        'icon': 0xe051, 'hint': 'Ex : Structurez une landing page pour [votre produit]…'},
  {'key': 'spec_writing',           'label': 'Rédaction spec',      'icon': 0xe873, 'hint': 'Ex : Rédigez les spécifications de [votre fonctionnalité]…'},
  {'key': 'automation_opportunity', 'label': 'Automatisation',      'icon': 0xe553, 'hint': 'Ex : Identifiez les opportunités d\'automatisation…'},
  {'key': 'strategy_reasoning',     'label': 'Conseil stratégique', 'icon': 0xe90f, 'hint': 'Ex : Donnez un conseil stratégique sur [ma situation]…'},
];
