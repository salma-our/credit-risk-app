# modules/risk_drivers.py
"""
Identification automatique des Risk Drivers : les critères qui expliquent le
plus la note finale (positifs et négatifs), à partir des `details` déjà
calculés par `rating_engine.build_rating()`.

Ce module ne recalcule aucun score : il lit les `details` des 3 blocs
(Secteur / Ratios Financiers / Gouvernance) et les classe. Les benchmarks
sectoriels restent les valeurs statiques de `sectors.py` — aucun historique
sectoriel n'est fabriqué ici.
"""

import re

from modules.rating_engine import RatingEngine

BLOCK_LABELS = {
    'sector': 'Secteur',
    'financial': 'Ratios Financiers',
    'governance': 'Gouvernance',
}

_DEFAULT_REFERENCE_NOTE = (
    "valeur de référence par défaut du secteur, non personnalisée pour ce dossier"
)

_UNIT_RE = re.compile(r'^-?\d+(?:\.\d+)?(.*)$')

# Critères du bloc Secteur qui, par leur libellé (cf. sectors.py ->
# 'sector_weights_labels'), mesurent le MÊME indicateur sous-jacent qu'un
# critère du bloc Ratios Financiers — ex: "Évolution du coût du risque"
# (Secteur, valeur de référence par défaut du secteur) et "Coût du Risque"
# (Ratios Financiers, calculé sur les données réelles de CE dossier).
# Confirmé un par un par lecture directe de sectors.py/ratios.py (jamais
# une correspondance devinée) : 'evolution_cout_risque'/'evolution_
# taux_souffrance' reprennent littéralement le libellé du ratio Financier
# correspondant ; 'claims_ratio' (Assurance, "Ratio sinistres/primes") est
# la même formule que 'combined_ratio' (sinistres / primes, cf.
# ratios.py:calculate_sector_ratios) ; 'revenue_trend'/'technical_
# performance' recouvrent respectivement 'revenue_growth'/'technical_
# result'. Les clés ne se recoupent jamais entre secteurs (chacune n'existe
# que dans un seul secteur), une seule table plate suffit donc.
_SECTOR_DUPLICATES_OF_FINANCIAL = {
    'evolution_cout_risque': 'cout_risque',
    'evolution_taux_souffrance': 'taux_souffrance',
    'revenue_trend': 'revenue_growth',
    'claims_ratio': 'combined_ratio',
    'technical_performance': 'technical_result',
}


def _extract_unit(benchmark_display):
    """Extrait le suffixe d'unité (ex: '%', 'x') d'une chaîne 'benchmark'
    du type '40.0%' produite par `RatingEngine.calculate_financial_score`."""
    if not benchmark_display:
        return ''
    m = _UNIT_RE.match(str(benchmark_display))
    return m.group(1) if m else ''


def _trend_comment(key, ratio_series, years, unit='', higher_is_better=True):
    """
    Cherche, pour le ratio `key`, la plus longue série CONSÉCUTIVE de valeurs
    non-None se terminant au dernier exercice disponible dans `ratio_series`.
    Si elle compte au moins 3 points et est strictement monotone (croissante
    ou décroissante), retourne une phrase factuelle avec les valeurs
    réellement observées. Sinon retourne None (pas de tendance nette ou pas
    assez de données) — jamais d'extrapolation.

    `higher_is_better` (cf. `sectors.py`, déjà utilisé par
    `RatingEngine.score_ratio` pour la note elle-même) détermine le sens de
    "amélioration"/"dégradation" : pour un ratio où une valeur plus BASSE est
    préférable (ex: coût du risque, taux de souffrance, coefficient
    d'exploitation, Debt-to-Equity, Combined Ratio -- `higher_is_better:
    False`), une série DÉCROISSANTE est une amélioration, pas une
    dégradation. Sans ce correctif, une baisse était toujours étiquetée
    "dégradation" quel que soit le ratio, ce qui inversait le sens pour tous
    les ratios "inverses" (ex: "dégradation : 1.00% -> 0.80%" pour un coût du
    risque en baisse, alors que la note correspondante était déjà correcte).
    """
    if not ratio_series or not years or key not in ratio_series:
        return None
    values = ratio_series[key]
    if len(values) != len(years):
        return None

    run_values = []
    for v in values:
        if v is None:
            run_values = []
            continue
        run_values.append(v)

    if len(run_values) < 3:
        return None

    diffs = [run_values[i + 1] - run_values[i] for i in range(len(run_values) - 1)]
    if all(d > 1e-9 for d in diffs):
        is_increasing = True
    elif all(d < -1e-9 for d in diffs):
        is_increasing = False
    else:
        return None

    is_improvement = is_increasing if higher_is_better else not is_increasing
    direction = "amélioration" if is_improvement else "dégradation"

    chain = " -> ".join(f"{v:.2f}{unit}" for v in run_values)
    return f"{direction} sur {len(run_values)} exercices consécutifs : {chain}"


def _build_comment(note, poids, is_override, trend_text):
    parts = [f"Note {note:.2f}/5 (poids {poids})"]
    if trend_text:
        parts.append(trend_text)
    if is_override is False:
        parts.append(_DEFAULT_REFERENCE_NOTE)
    return " ; ".join(parts)


def identify_risk_drivers(sector_result, financial_result, governance_result,
                           ratio_series=None, years=None, top_n=4, ratios_cfg=None):
    """
    Identifie les `top_n` facteurs positifs et négatifs qui expliquent le
    plus la note finale, à partir des `details` déjà calculés par
    `RatingEngine`/`build_rating()` — aucun score n'est recalculé ici.

    Args:
        sector_result, financial_result, governance_result: les 3 dicts
            retournés par `build_rating()` (`rating['sector_result']`, etc.),
            chacun avec une clé `details` (liste de critères).
        ratio_series: dict {ratio_key: [valeur_par_exercice, ...]} aligné sur
            `years`, utilisé uniquement pour détecter une tendance factuelle
            sur les critères du bloc Ratios Financiers. Comme
            `financial_result` est construit à partir des ratios SECTORIELS
            (`calculate_sector_ratios`, cf. `RatingEngine.calculate_financial_score`
            appelé avec `sector_ratios` dans `build_rating()`), ce paramètre
            doit être le `sector_ratio_series` produit par
            `ratios.calculate_sector_ratios_series()` — pas le
            `ratio_series` générique — pour que les clés correspondent.
        years: liste des exercices alignée sur `ratio_series`.
        top_n: nombre de facteurs positifs et négatifs à retourner.
        ratios_cfg: dict {ratio_key: config} du secteur analysé (typiquement
            `rating['sector_config']['ratios']`), utilisé uniquement pour lire
            `higher_is_better` par ratio et donner un sens correct à la
            tendance du bloc Ratios Financiers (cf. `_trend_comment`) : pour
            un ratio où une valeur plus basse est préférable (coût du risque,
            taux de souffrance, COEX, Debt-to-Equity, Combined Ratio...), une
            série décroissante doit être lue comme une amélioration, pas une
            dégradation. Si omis, tous les ratios sont traités comme
            `higher_is_better=True` (comportement précédent).

    Returns:
        {'positifs': [...], 'negatifs': [...]}, chaque entrée :
        {'key', 'label', 'bloc', 'note', 'poids', 'contribution',
         'is_override', 'commentaire'}.

        `contribution` = part du critère dans la note finale /5 :
        (note * poids / poids_total_du_bloc) * poids_macro_du_bloc (20/60/20),
        ce qui permet de comparer des critères entre blocs de pondération
        différente. Les positifs sont triés par contribution décroissante,
        les négatifs par contribution croissante (aucun chevauchement entre
        les deux listes).

        Transparence : un critère Secteur ou Gouvernance dont `is_override`
        est False (valeur de référence par défaut, non évaluée spécifiquement
        pour ce dossier) est toujours inclus avec la mention explicite
        correspondante dans `commentaire` — jamais présenté comme un facteur
        différenciant sans cette précision.
    """
    block_weights = {
        'sector': RatingEngine.SECTOR_WEIGHT,
        'financial': RatingEngine.FINANCIAL_WEIGHT,
        'governance': RatingEngine.GOVERNANCE_WEIGHT,
    }
    blocks = {
        'sector': sector_result or {},
        'financial': financial_result or {},
        'governance': governance_result or {},
    }

    entries = []
    for block_key, result in blocks.items():
        details = result.get('details') or []
        total_weight = sum(d.get('weight', 0) or 0 for d in details)
        if not total_weight:
            continue

        for d in details:
            note = d.get('note')
            if note is None:
                continue  # ratio non disponible pour ce dossier : pas classable

            poids = d.get('weight', 0)
            contribution = (note * poids / total_weight) * block_weights[block_key]
            is_override = d.get('is_override')  # None (n/a) pour le bloc financier

            trend_text = None
            if block_key == 'financial':
                unit = _extract_unit(d.get('benchmark'))
                higher_is_better = (ratios_cfg or {}).get(d.get('key'), {}).get('higher_is_better', True)
                trend_text = _trend_comment(d.get('key'), ratio_series, years, unit, higher_is_better)

            entries.append({
                'key': d.get('key'),
                'label': d.get('label', d.get('key')),
                'bloc': BLOCK_LABELS[block_key],
                'note': round(note, 2),
                'poids': poids,
                'contribution': round(contribution, 3),
                'is_override': is_override,
                'commentaire': _build_comment(note, poids, is_override, trend_text),
            })

    # Retire du pool de sélection un critère Secteur qui duplique un critère
    # Ratios Financiers déjà présent (cf. _SECTOR_DUPLICATES_OF_FINANCIAL) —
    # UNIQUEMENT quand ce critère Secteur est une valeur de référence par
    # défaut non personnalisée (`is_override is False`) : c'est précisément
    # ce cas qui produisait "deux drivers contradictoires pour le même
    # indicateur" (ex: Coût du Risque 4.20/5 en positif ET Évolution du coût
    # du risque 2.00/5 en négatif) puisque le critère Secteur n'apportait
    # alors aucune information au-delà de ce que montre déjà le driver
    # Financier, plus riche (valeur réelle de ce dossier + tendance). Note :
    # ceci ne modifie AUCUN score — les deux critères continuent de compter
    # pour leur poids réel dans la note finale (cf. Tableau de Notation
    # Détaillé, qui liste toujours tous les critères de chaque bloc) ; seule
    # la sélection des facteurs mis en avant en Synthèse Exécutive change. Un
    # critère Secteur personnalisé pour ce dossier (`is_override is True`)
    # reste toujours affiché : il porte alors une évaluation propre à CE
    # dossier, pas un doublon générique.
    financial_keys_present = {e['key'] for e in entries if e['bloc'] == BLOCK_LABELS['financial']}
    entries = [
        e for e in entries
        if not (e['bloc'] == BLOCK_LABELS['sector'] and e['is_override'] is False
                and _SECTOR_DUPLICATES_OF_FINANCIAL.get(e['key']) in financial_keys_present)
    ]

    entries_desc = sorted(entries, key=lambda e: e['contribution'], reverse=True)
    positifs = entries_desc[:top_n]

    positifs_ids = {id(e) for e in positifs}
    remaining = [e for e in entries_desc if id(e) not in positifs_ids]
    negatifs = sorted(remaining, key=lambda e: e['contribution'])[:top_n]

    return {'positifs': positifs, 'negatifs': negatifs}
