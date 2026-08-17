# modules/rating_engine.py
"""
Moteur de notation pondérée /5, inspiré des grilles de notation bancaires
type ATW : Secteur (20%) + Ratios Financiers (60%) + Gouvernance (20%).
"""

from modules.sectors import SectorConfig

CATEGORIES = [
    (4.5, 1, "Très Faible Risque"),
    (3.5, 2, "Faible Risque"),
    (2.5, 3, "Risque Moyen"),
    (0.0, 4, "Risque Élevé"),
]

RECOMMENDATIONS = {
    1: {'decision': 'APPROUVER', 'level': 'Strong', 'color': 'success'},
    2: {'decision': 'APPROUVER AVEC CONDITIONS', 'level': 'Medium', 'color': 'warning'},
    3: {'decision': 'APPROUVER SOUS CONDITIONS STRICTES', 'level': 'Weak', 'color': 'danger'},
    4: {'decision': 'REJETER', 'level': 'Critical', 'color': 'dark'},
}


class RatingEngine:
    """Moteur de notation pondérée /5 pour un secteur donné."""

    SECTOR_WEIGHT = 0.20
    FINANCIAL_WEIGHT = 0.60
    GOVERNANCE_WEIGHT = 0.20

    def __init__(self, sector_config, sub_sector=None):
        self.config = sector_config
        self.sub_sector = str(sub_sector).strip().lower() if sub_sector else None

    # ------------------------------------------------------------------
    def get_ratio_config(self, ratio_key):
        """
        Récupère la config d'un ratio (benchmark, good_range, poids...) en
        appliquant les overrides du sous-secteur courant si présents.
        Seuls les champs listés dans `ratios_overrides` sont remplacés ;
        le reste (poids, description, sens) est hérité du ratio de base.
        """
        base_cfg = self.config['ratios'][ratio_key]
        if not self.sub_sector:
            return base_cfg
        sub_sectors = self.config.get('sub_sectors') or {}
        sub_cfg = sub_sectors.get(self.sub_sector)
        if not sub_cfg:
            return base_cfg
        override = (sub_cfg.get('ratios_overrides') or {}).get(ratio_key)
        if not override:
            return base_cfg
        return {**base_cfg, **override}

    # ------------------------------------------------------------------
    def score_ratio(self, value, benchmark, good_range, higher_is_better=True):
        """Note un ratio (0-5) par rapport à sa fourchette `good_range`."""
        if value is None:
            return None
        min_range, max_range = good_range
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        if higher_is_better:
            if value >= max_range:
                return 5.0
            if value <= min_range:
                return 1.0
            return 1.0 + ((value - min_range) / (max_range - min_range)) * 4
        else:
            if value <= min_range:
                return 5.0
            if value >= max_range:
                return 1.0
            return 5.0 - ((value - min_range) / (max_range - min_range)) * 4

    # ------------------------------------------------------------------
    def calculate_financial_score(self, ratios):
        """
        Score Ratios Financiers (60% de la note finale).
        Calculé à partir des ratios sectoriels disponibles ; les ratios
        manquants (donnée non fournie) sont exclus du calcul plutôt que
        remplacés par une valeur par défaut, pour ne pas fausser la note.
        """
        ratios = ratios or {}
        details = []
        weighted_sum = 0.0
        total_weight = 0.0

        for key in self.config['ratios']:
            ratio_cfg = self.get_ratio_config(key)
            value = ratios.get(key)
            note = self.score_ratio(
                value, ratio_cfg['benchmark'], ratio_cfg['good_range'],
                ratio_cfg.get('higher_is_better', True),
            )
            weight = ratio_cfg['weight']
            unit = ratio_cfg.get('unit', '')
            display = f"{value:.2f}{unit}" if value is not None else "N/A"

            if note is not None:
                weighted_sum += note * weight
                total_weight += weight

            details.append({
                'key': key,
                'label': ratio_cfg['description'],
                'value': value,
                'display': display,
                'benchmark': f"{ratio_cfg['benchmark']}{unit}",
                'weight': weight,
                'note': round(note, 2) if note is not None else None,
                'available': note is not None,
            })

        score = (weighted_sum / total_weight) if total_weight > 0 else 3.0
        available_count = sum(1 for d in details if d['available'])
        return {
            'score': round(score, 2),
            'details': details,
            'coverage': f"{available_count}/{len(details)}",
        }

    # ------------------------------------------------------------------
    def _weighted_block(self, weights_map, labels_map, overrides=None):
        overrides = overrides or {}
        details = []
        weighted_sum = 0.0
        total_weight = 0.0

        for key, (weight, default_note) in weights_map.items():
            note = overrides.get(key, default_note)
            weighted_sum += note * weight
            total_weight += weight
            details.append({
                'key': key,
                'label': labels_map.get(key, key),
                'weight': weight,
                'note': note,
                'is_override': key in overrides,
                # Redondant avec `is_override` (is_default == not is_override) mais nommé
                # pour ce que consomme le frontend web (badge "Estimé" — cf. transparence
                # données manquantes) plutôt que pour ce que ce calcul a fait en interne.
                'is_default': key not in overrides,
            })

        score = (weighted_sum / total_weight) if total_weight > 0 else 3.0
        return {'score': round(score, 2), 'details': details}

    def calculate_sector_score(self, overrides=None):
        """
        Score Secteur (20% de la note finale) : évolution des crédits/CA,
        coût du risque, contraintes réglementaires, etc.
        Utilise les notes de référence du secteur (`sector_weights`), sauf si
        une note qualitative réelle est fournie via `overrides`.
        """
        return self._weighted_block(
            self.config['sector_weights'],
            self.config.get('sector_weights_labels', {}),
            overrides,
        )

    def calculate_governance_score(self, overrides=None):
        """
        Score Gouvernance (20% de la note finale) : actionnariat, management,
        clarté stratégique. Utilise les notes de référence, sauf `overrides`.
        """
        return self._weighted_block(
            self.config['governance_weights'],
            self.config.get('governance_weights_labels', {}),
            overrides,
        )

    # ------------------------------------------------------------------
    def calculate_final_rating(self, sector_result, financial_result, governance_result):
        """Combine les 3 blocs (20/60/20) en une note finale /5 + catégorie."""
        sector_score = sector_result['score']
        financial_score = financial_result['score']
        governance_score = governance_result['score']

        final = (sector_score * self.SECTOR_WEIGHT +
                 financial_score * self.FINANCIAL_WEIGHT +
                 governance_score * self.GOVERNANCE_WEIGHT)

        category, rating = 4, "Risque Élevé"
        for threshold, cat, label in CATEGORIES:
            if final >= threshold:
                category, rating = cat, label
                break

        return {
            'final_score': round(final, 2),
            'category': category,
            'rating': rating,
            'sector_score': sector_score,
            'financial_score': financial_score,
            'governance_score': governance_score,
            'recommendation': RECOMMENDATIONS[category],
        }


def build_rating(sector, ratios, sector_ratios=None, sector_overrides=None,
                  governance_overrides=None, sub_sector=None):
    """
    Helper haut-niveau : construit la config secteur, exécute les 3 blocs de
    notation et retourne un dict prêt à être injecté dans `results` (app.py)
    et dans le générateur de rapport PDF.

    `sub_sector`: sous-secteur optionnel (ex: 'mining', 'manufacturing',
    'services' pour le secteur 'industry') utilisé pour ajuster les
    benchmarks de certains ratios via `SectorConfig.SECTORS[...]['sub_sectors']`.
    """
    sector_config = SectorConfig.get_sector_config(sector)
    engine = RatingEngine(sector_config, sub_sector=sub_sector)

    financial_result = engine.calculate_financial_score(sector_ratios or ratios or {})
    sector_result = engine.calculate_sector_score(sector_overrides)
    governance_result = engine.calculate_governance_score(governance_overrides)
    final_rating = engine.calculate_final_rating(sector_result, financial_result, governance_result)

    return {
        'sector_config': sector_config,
        'engine': engine,
        'sector_result': sector_result,
        'financial_result': financial_result,
        'governance_result': governance_result,
        'final_rating': final_rating,
    }
