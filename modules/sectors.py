# modules/sectors.py
"""
Configuration des ratios et pondérations de notation par secteur d'activité.

Chaque ratio porte un flag `higher_is_better`: False pour les ratios où une
valeur plus basse est préférable (ex: coefficient d'exploitation, taux de
souffrance, Debt-to-Equity, Combined Ratio) -- utilisé par RatingEngine pour
savoir dans quel sens noter la valeur par rapport à `good_range`.
"""


class SectorConfig:
    """Configuration des ratios, poids sectoriels et gouvernance par secteur."""

    SECTORS = {
        'banking': {
            'name': 'Secteur Bancaire',
            'ratios': {
                'pnb_growth': {
                    'description': "Évolution du Produit Net Bancaire",
                    'weight': 4,
                    'benchmark': 4.2,
                    'good_range': (3.5, 6.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'coex': {
                    'description': "Coefficient d'exploitation",
                    'weight': 2,
                    'benchmark': 40.0,
                    'good_range': (35, 45),
                    'higher_is_better': False,
                    'unit': '%',
                },
                'margin_intermediation': {
                    'description': "Marge d'intermédiation",
                    'weight': 2,
                    'benchmark': 4.5,
                    'good_range': (4.0, 5.5),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'ratio_liquidite': {
                    'description': "Ratio liquidité bancaire",
                    'weight': 3,
                    'benchmark': 1.0,
                    'good_range': (0.9, 1.2),
                    'higher_is_better': True,
                    'unit': 'x',
                },
                'taux_souffrance': {
                    'description': "Taux de souffrance",
                    'weight': 4,
                    'benchmark': 0.8,
                    'good_range': (0.5, 1.5),
                    'higher_is_better': False,
                    'unit': '%',
                },
                'cout_risque': {
                    'description': "Coût du risque",
                    'weight': 4,
                    'benchmark': 0.9,
                    'good_range': (0.5, 2.0),
                    'higher_is_better': False,
                    'unit': '%',
                },
                'ratio_solvabilite_t1': {
                    'description': "Ratio de solvabilité Tier 1",
                    'weight': 3,
                    'benchmark': 13.0,
                    'good_range': (10.5, 15.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'roa': {
                    'description': "Return on Assets",
                    'weight': 2,
                    'benchmark': 1.0,
                    'good_range': (0.8, 1.5),
                    'higher_is_better': True,
                    'unit': '%',
                },
            },
            'sector_weights': {
                'evolution_credits': (4, 3),
                'evolution_cout_risque': (4, 2),
                'evolution_taux_souffrance': (4, 2),
                'contraintes_reglementaires': (3, 5),
            },
            'sector_weights_labels': {
                'evolution_credits': "Évolution des crédits distribués",
                'evolution_cout_risque': "Évolution du coût du risque",
                'evolution_taux_souffrance': "Évolution du taux de souffrance",
                'contraintes_reglementaires': "Contraintes réglementaires (Bâle III)",
            },
            'governance_weights': {
                'type_actionariat': (4, 4),
                'risque_conflit': (4, 4),
                'expertise_management': (3, 4),
                'clarte_strategie': (4, 4),
            },
            'governance_weights_labels': {
                'type_actionariat': "Type d'actionnariat",
                'risque_conflit': "Risque de conflit d'intérêts",
                'expertise_management': "Expertise du management",
                'clarte_strategie': "Clarté de la stratégie",
            },
            # Benchmarks riches pour affichage graphique (Phase 4, sourcés Maroc
            # depuis Phase 5A+ "Intégration Benchmarks Marocains") : distincts
            # du 'benchmark' plat utilisé par RatingEngine.score_ratio dans
            # 'ratios' ci-dessus (non modifié — ce dict n'affecte jamais la
            # note finale, uniquement l'affichage graphique/PDF, cf.
            # modules/charts_generator.py et modules/reports.py). Champs :
            # value/unit (valeur affichée), source_type ('regulatory' pour un
            # seuil BAM opposable, 'statistical' pour une moyenne/médiane
            # sectorielle), source/source_url/year (traçabilité), label
            # (rétrocompatible : ancien code qui ne lit que value+label
            # continue de fonctionner), note (contexte court).
            'benchmarks': {
                'ratio_solvabilite_t1': {
                    'value': 13.5, 'unit': '%', 'source_type': 'regulatory',
                    'label': 'Référence BAM — Bâle III (Circulaire n°44/2023)',
                    'source': 'BAM Circulaire n°44/2023 (Bâle III) — minimum 10,5%',
                    'source_url': 'www.bam.ma/fr', 'year': 2024,
                    'note': 'Minimum réglementaire BAM 10,5% + coussin contracyclique.',
                },
                'ratio_liquidite': {
                    'value': 1.5, 'unit': 'x', 'source_type': 'regulatory',
                    'label': 'Référence BAM — Liquidity Coverage Ratio',
                    'source': 'BAM — LCR (Liquidity Coverage Ratio), minimum réglementaire 100%',
                    'source_url': 'www.bam.ma', 'year': 2024,
                    'note': 'Exprimé ici sur la même base que le ratio calculé (actifs/dettes courants).',
                },
                'taux_souffrance': {
                    'value': 3.0, 'unit': '%', 'source_type': 'statistical',
                    'label': 'Référence BAM — Statistiques mensuelles',
                    'source': 'BAM — Statistiques mensuelles du secteur bancaire',
                    'source_url': 'www.bam.ma', 'year': 2024,
                    'note': 'Taux moyen de créances en souffrance (NPL) du secteur bancaire marocain.',
                },
                'roa': {
                    'value': 1.35, 'unit': '%', 'source_type': 'regulatory',
                    'label': 'Référence BAM — Rapports de Stabilité Financière',
                    'source': 'BAM — Rapports de Stabilité Financière 2024',
                    'source_url': 'www.bam.ma/fr/page/stabilite-financiere', 'year': 2024,
                    'note': 'Médiane ROA des banques marocaines. Non encore superposé à un graphique '
                            '(ROA vs ROE ne trace pas de ligne de référence à ce jour).',
                },
                'roe': {
                    'value': 13.5, 'unit': '%', 'source_type': 'regulatory',
                    'label': 'Référence BAM — Données publiques',
                    'source': 'BAM — Données publiques 2024',
                    'source_url': 'www.bam.ma', 'year': 2024,
                    'note': 'Médiane ROE du secteur. Non encore superposé à un graphique (cf. ROA ci-dessus).',
                },
            },
        },

        'industry': {
            'name': 'Secteur Industriel',
            'ratios': {
                'revenue_growth': {
                    'description': "Évolution du Chiffre d'Affaires",
                    'weight': 4,
                    'benchmark': 5.0,
                    'good_range': (2.0, 10.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'net_profit_margin': {
                    'description': "Marge nette",
                    'weight': 3,
                    'benchmark': 5.0,
                    'good_range': (3.0, 15.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'roe': {
                    'description': "Return on Equity",
                    'weight': 3,
                    'benchmark': 12.0,
                    'good_range': (8.0, 20.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'debt_to_equity': {
                    'description': "Ratio Dettes/Capitaux Propres",
                    'weight': 4,
                    'benchmark': 1.0,
                    'good_range': (0.5, 2.5),
                    'higher_is_better': False,
                    'unit': 'x',
                },
                'current_ratio': {
                    'description': "Ratio de liquidité générale",
                    'weight': 3,
                    'benchmark': 1.3,
                    'good_range': (1.0, 2.5),
                    'higher_is_better': True,
                    'unit': 'x',
                },
                'interest_coverage': {
                    'description': "Couverture des intérêts",
                    'weight': 4,
                    'benchmark': 4.0,
                    'good_range': (2.0, 8.0),
                    'higher_is_better': True,
                    'unit': 'x',
                },
                'asset_turnover': {
                    'description': "Rotation des actifs",
                    'weight': 2,
                    'benchmark': 1.2,
                    'good_range': (0.8, 2.0),
                    'higher_is_better': True,
                    'unit': 'x',
                },
                'roa': {
                    'description': "Return on Assets",
                    'weight': 2,
                    'benchmark': 5.0,
                    'good_range': (2.0, 10.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
            },
            # Sous-secteurs industriels: certains ratios "génériques" (surtout
            # la rotation des actifs et, dans une moindre mesure, la liquidité)
            # ne sont pas comparables entre une activité capitalistique lourde
            # (mines, énergie) et une activité de services. `ratios_overrides`
            # ne redéfinit que benchmark/good_range ; le reste (poids,
            # description, sens) est hérité du ratio de base via
            # RatingEngine.get_ratio_config().
            'sub_sectors': {
                'mining': {
                    'name': 'Extraction / Minier',
                    # Rotation des actifs typiquement basse pour les groupes
                    # miniers diversifiés (immobilisations lourdes: mines,
                    # usines de traitement, infrastructures) - comparables
                    # internationaux (Newmont, Barrick, Rio Tinto) ~0.3-0.6x.
                    'ratios_overrides': {
                        'asset_turnover': {'benchmark': 0.5, 'good_range': (0.3, 1.0)},
                        'current_ratio': {'benchmark': 1.1, 'good_range': (0.8, 1.8)},
                    },
                },
                'manufacturing': {
                    'name': 'Fabrication / Manufacturing',
                    'ratios_overrides': {
                        'asset_turnover': {'benchmark': 1.0, 'good_range': (0.8, 1.5)},
                    },
                },
                'services': {
                    'name': 'Services / Immatériel',
                    'ratios_overrides': {
                        'asset_turnover': {'benchmark': 1.5, 'good_range': (1.2, 2.5)},
                    },
                },
            },
            'sector_weights': {
                'revenue_trend': (4, 3),
                'profitability_trend': (4, 3),
                'margin_quality': (3, 3),
            },
            'sector_weights_labels': {
                'revenue_trend': "Tendance du chiffre d'affaires",
                'profitability_trend': "Tendance de la rentabilité",
                'margin_quality': "Qualité de la marge",
            },
            'governance_weights': {
                'management_quality': (3, 3),
                'strategic_clarity': (3, 3),
            },
            'governance_weights_labels': {
                'management_quality': "Qualité du management",
                'strategic_clarity': "Clarté stratégique",
            },
            'benchmarks': {
                'debt_to_equity': {
                    'value': 0.85, 'unit': 'x', 'source_type': 'statistical',
                    'label': 'Référence Office des Changes — Données structurelles',
                    'source': 'Données structurelles secteur Maroc (Office des Changes)',
                    'source_url': 'www.oc.gov.ma', 'year': 2024,
                    'note': 'Endettement moyen (Dettes / Capitaux Propres) du secteur industriel marocain.',
                },
                'interest_coverage': {
                    'value': 3.0, 'unit': 'x', 'source_type': 'statistical',
                    'label': 'Référence Office des Changes — Secteur industriel',
                    'source': 'Données secteur industriel Maroc (Office des Changes)',
                    'source_url': 'www.oc.gov.ma', 'year': 2024,
                    'note': 'Capacité moyenne de remboursement des intérêts du secteur.',
                },
                'revenue_growth': {
                    'value': 4.0, 'unit': '%', 'source_type': 'statistical',
                    'label': 'Référence Office des Changes — Statistiques secteur',
                    'source': 'Office des Changes — Statistiques secteur 2024',
                    'source_url': 'www.oc.gov.ma', 'year': 2024,
                    'note': "TCAM moyen du secteur industrie. Non encore superposé à un graphique "
                            "(le graphique « Chiffre d'Affaires » trace un niveau en MDH, pas un taux "
                            "de croissance — unités non comparables).",
                },
                'ebit_margin': {
                    'value': 10.0, 'unit': '%', 'source_type': 'statistical',
                    'label': 'Référence WALI Gestion — Analyse secteur industriel',
                    'source': 'WALI Gestion — Analyse secteur industriel 2024',
                    'source_url': 'www.wafiagestion.ma', 'year': 2024,
                    'note': 'Marge EBIT médiane du secteur industriel marocain.',
                },
                'roa': {
                    'value': 6.0, 'unit': '%', 'source_type': 'statistical',
                    'label': "Référence Ministère de l'Industrie — Données sectorielles",
                    'source': "Ministère de l'Industrie — Données sectorielles 2024",
                    'source_url': 'www.mcinet.gov.ma', 'year': 2024,
                    'note': 'ROA moyen industrie légère. Non encore superposé à un graphique (ROA vs '
                            'ROE ne trace pas de ligne de référence à ce jour).',
                },
                'roe': {
                    'value': 18.0, 'unit': '%', 'source_type': 'statistical',
                    'label': 'Référence secteur industriel Maroc',
                    'source': 'Données secteur industriel Maroc 2024',
                    'source_url': 'www.oc.gov.ma', 'year': 2024,
                    'note': 'ROE moyen du secteur. Non encore superposé à un graphique (cf. ROA ci-dessus).',
                },
            },
        },

        'insurance': {
            'name': 'Secteur Assurance',
            'ratios': {
                'technical_result': {
                    'description': "Résultat technique",
                    'weight': 4,
                    'benchmark': 2.0,
                    'good_range': (1.0, 5.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'combined_ratio': {
                    'description': "Taux de sinistralité (Combined Ratio)",
                    'weight': 4,
                    'benchmark': 95.0,
                    'good_range': (85.0, 105.0),
                    'higher_is_better': False,
                    'unit': '%',
                },
                'solvency_margin': {
                    'description': "Marge de solvabilité",
                    'weight': 4,
                    'benchmark': 150.0,
                    'good_range': (125.0, 200.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'roe': {
                    'description': "Return on Equity",
                    'weight': 3,
                    'benchmark': 10.0,
                    'good_range': (6.0, 15.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
                'operating_margin': {
                    'description': "Marge opérationnelle",
                    'weight': 3,
                    'benchmark': 3.0,
                    'good_range': (1.0, 6.0),
                    'higher_is_better': True,
                    'unit': '%',
                },
            },
            'sector_weights': {
                'technical_performance': (4, 3),
                'claims_ratio': (4, 2),
                'reserves_adequacy': (3, 3),
            },
            'sector_weights_labels': {
                'technical_performance': "Performance technique",
                'claims_ratio': "Ratio sinistres/primes",
                'reserves_adequacy': "Adéquation des provisions",
            },
            'governance_weights': {
                'board_composition': (3, 3),
                'risk_management': (4, 3),
            },
            'governance_weights_labels': {
                'board_composition': "Composition du conseil d'administration",
                'risk_management': "Gestion des risques",
            },
            'benchmarks': {
                'solvency_margin': {
                    'value': 10.0, 'unit': '%', 'source_type': 'regulatory',
                    'label': 'Référence AMMC — Circulaire solvabilité (minimum 8%)',
                    'source': 'AMMC — Circulaire solvabilité, minimum réglementaire 8%',
                    'source_url': 'www.ammc.ma', 'year': 2024,
                    'note': 'Marge de solvabilité de référence ; le minimum opposable AMMC est de 8%.',
                },
                # Le graphique existant (« Loss Ratio (Sinistres / Primes) »,
                # cf. charts_generator.py) trace la clé de ratio 'combined_ratio'
                # (seule disponible dans ce projet — il n'y a pas de calcul
                # distinct pour un "Combined Ratio" frais+sinistres). On y
                # attache donc la référence AMMC (loss ratio, réglementaire,
                # 70%) qui correspond au titre affiché ; la référence FMAR
                # (combined ratio statistique, 90%, périmètre plus large
                # incluant les frais de gestion) est conservée en `note` à
                # titre de repère complémentaire plutôt que sur une 2e ligne
                # de benchmark (le graphique ne trace qu'une seule référence).
                'combined_ratio': {
                    'value': 70.0, 'unit': '%', 'source_type': 'regulatory',
                    'label': 'Référence AMMC — Loss Ratio secteur assurance',
                    'source': 'AMMC — Rapports secteur assurance 2024',
                    'source_url': 'www.ammc.ma/fr', 'year': 2024,
                    'note': 'Loss Ratio moyen (sinistres/primes), secteur assurance non-vie. Repère '
                            'complémentaire : Combined Ratio (sinistres+frais/primes) FMAR 2024 = 90% '
                            '(www.fmar.ma), périmètre plus large non tracé séparément ici.',
                },
                'roa': {
                    'value': 3.0, 'unit': '%', 'source_type': 'statistical',
                    'label': 'Référence AMMC — Données publiques assureurs',
                    'source': 'AMMC — Données publiques assureurs 2024',
                    'source_url': 'www.ammc.ma', 'year': 2024,
                    'note': 'ROA moyen assurance non-vie. Non encore superposé à un graphique (ROA vs '
                            'ROE ne trace pas de ligne de référence à ce jour).',
                },
                'roe': {
                    'value': 14.0, 'unit': '%', 'source_type': 'statistical',
                    'label': 'Référence secteur assurance Maroc',
                    'source': 'Données secteur assurance Maroc 2024',
                    'source_url': 'www.ammc.ma', 'year': 2024,
                    'note': 'ROE moyen du secteur. Non encore superposé à un graphique (cf. ROA ci-dessus).',
                },
            },
        },
    }

    @staticmethod
    def get_sector_config(sector_name):
        """Récupère la config du secteur (fallback: 'industry' si secteur inconnu)."""
        if not sector_name:
            return SectorConfig.SECTORS['industry']
        sector_lower = str(sector_name).strip().lower()
        if sector_lower in SectorConfig.SECTORS:
            return SectorConfig.SECTORS[sector_lower]
        for key, config in SectorConfig.SECTORS.items():
            if sector_lower in key or key in sector_lower:
                return config
        return SectorConfig.SECTORS['industry']
