"""
Module de calcul des ratios financiers a partir des donnees extraites du bilan,
du compte de resultat et du tableau de flux de tresorerie.
"""

from modules.data_provenance import DataProvenance


def _safe_div(numerator, denominator):
    """Division protegee: retourne None si les operandes sont invalides ou si le denominateur est nul."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


# Formule affichée en provenance (include_provenance=True) pour chacun des 15
# ratios génériques — texte informatif seulement, ne participe à aucun calcul.
_GENERIC_RATIO_FORMULAS = {
    'current_ratio': 'Actifs Courants / Dettes Courantes',
    'quick_ratio': '(Actifs Courants - Stocks) / Dettes Courantes',
    'cash_ratio': 'Trésorerie / Dettes Courantes',
    'debt_to_equity': 'Dettes / Capitaux Propres',
    'debt_ratio': 'Dettes / Actifs Totaux',
    'equity_ratio': 'Capitaux Propres / Actifs Totaux',
    'equity_multiplier': 'Actifs Totaux / Capitaux Propres',
    'interest_coverage_ratio': "EBIT / Charges d'Intérêts",
    'roe': 'Résultat Net / Capitaux Propres',
    'roa': 'Résultat Net / Actifs Totaux',
    'net_profit_margin': 'Résultat Net / Revenus',
    'operating_margin': 'EBIT / Revenus',
    'roce': 'EBIT / (Actifs Totaux - Dettes Courantes)',
    'asset_turnover': 'Revenus / Actifs Totaux',
    'operating_cash_flow_ratio': 'Cash-Flow Opérationnel / Dettes Courantes',
}


def _wrap(value, mark_fn, *args):
    """Enveloppe `value` avec `DataProvenance` via `mark_fn`, ou `mark_na()` si None."""
    if value is None:
        return DataProvenance.mark_na()
    return mark_fn(value, *args)


def _wrap_maybe_proxy(value, is_proxy, proxy_args, else_mark_fn, else_args):
    """Comme `_wrap`, mais choisit entre `mark_proxy` (si `is_proxy`) et
    `else_mark_fn` (donnée réelle / calcul standard) selon la branche qui a
    effectivement produit `value` dans le calcul déjà effectué plus haut."""
    if value is None:
        return DataProvenance.mark_na()
    if is_proxy:
        return DataProvenance.mark_proxy(value, *proxy_args)
    return else_mark_fn(value, *else_args)


def calculate_ratios(financials, include_provenance=False):
    """
    Calcule 15 ratios financiers standards a partir du dict `financials`
    produit par `data_processing.process_excel`.

    Args:
        financials: dict avec les cles actifs_totaux, actifs_courants, stocks,
                    tresorerie, dettes, dettes_courantes, equity,
                    benefices_non_repartis, revenus, ebit, resultat_net,
                    charges_interets, cash_flow_operationnel
        include_provenance: si False (défaut), retourne {ratio_key: value}
                    comme avant (contrat inchangé). Si True, retourne
                    {ratio_key: DataProvenance.create(...)} — chaque valeur
                    enveloppée avec sa provenance (calculée / indisponible).

    Returns:
        dict contenant les 15 ratios calcules (valeur None si non calculable),
        ou leur version enveloppée si `include_provenance=True`.
    """
    actifs_totaux = financials.get('actifs_totaux')
    actifs_courants = financials.get('actifs_courants')
    stocks = financials.get('stocks')
    tresorerie = financials.get('tresorerie')
    dettes = financials.get('dettes')
    dettes_courantes = financials.get('dettes_courantes')
    equity = financials.get('equity')
    revenus = financials.get('revenus')
    ebit = financials.get('ebit')
    resultat_net = financials.get('resultat_net')
    charges_interets = financials.get('charges_interets')
    cash_flow_operationnel = financials.get('cash_flow_operationnel')

    ratios = {
        # --- Liquidite ---
        'current_ratio': _safe_div(actifs_courants, dettes_courantes),
        'quick_ratio': _safe_div(
            (actifs_courants - stocks) if actifs_courants is not None and stocks is not None else None,
            dettes_courantes,
        ),
        'cash_ratio': _safe_div(tresorerie, dettes_courantes),

        # --- Structure financiere / Levier ---
        'debt_to_equity': _safe_div(dettes, equity),
        'debt_ratio': _safe_div(dettes, actifs_totaux),
        'equity_ratio': _safe_div(equity, actifs_totaux),
        'equity_multiplier': _safe_div(actifs_totaux, equity),
        'interest_coverage_ratio': _safe_div(ebit, charges_interets),

        # --- Rentabilite ---
        'roe': _safe_div(resultat_net, equity),
        'roa': _safe_div(resultat_net, actifs_totaux),
        'net_profit_margin': _safe_div(resultat_net, revenus),
        'operating_margin': _safe_div(ebit, revenus),
        'roce': _safe_div(
            ebit,
            (actifs_totaux - dettes_courantes) if actifs_totaux is not None and dettes_courantes is not None else None,
        ),

        # --- Efficacite / Cash flow ---
        'asset_turnover': _safe_div(revenus, actifs_totaux),
        'operating_cash_flow_ratio': _safe_div(cash_flow_operationnel, dettes_courantes),
    }

    if not include_provenance:
        return ratios

    return {
        key: _wrap(value, DataProvenance.mark_calculated, _GENERIC_RATIO_FORMULAS.get(key, key))
        for key, value in ratios.items()
    }


def _pct(ratio):
    """Convertit un ratio décimal (0.05) en pourcentage (5.0). None si non calculable."""
    return ratio * 100 if ratio is not None else None


def calculate_sector_ratios(financials, sector, include_provenance=False):
    """
    Calcule les ratios spécifiques au secteur (clés attendues par
    `modules.sectors.SectorConfig`), à partir du dict `financials` produit
    par `data_processing.process_excel`.

    Quand une donnée sectorielle réelle est disponible dans `financials`
    (ex: 'taux_souffrance_reel', 'primes_emises'), elle est utilisée
    directement. Sinon, un proxy raisonnable est calculé à partir des états
    financiers génériques ; si aucun proxy fiable n'existe (ex: taux de
    souffrance bancaire sans données de créances douteuses), le ratio reste
    `None` et sera simplement exclu de la notation par RatingEngine plutôt
    que fabriqué.

    `include_provenance` (défaut False, contrat inchangé) : si True, chaque
    valeur est enveloppée dans une structure `DataProvenance` distinguant
    donnée réelle / ratio calculé / proxy / indisponible — utile pour les
    graphiques analytiques (Phase 4), qui doivent indiquer explicitement
    quand un proxy a été utilisé plutôt que la donnée réelle demandée.
    """
    sector_key = str(sector or '').strip().lower()
    if 'bank' in sector_key or 'banq' in sector_key:
        return _calculate_banking_ratios(financials, include_provenance)
    if 'insur' in sector_key or 'assur' in sector_key:
        return _calculate_insurance_ratios(financials, include_provenance)
    return _calculate_industry_ratios(financials, include_provenance)


def _growth_pct(current, prior):
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior) * 100


def _calculate_banking_ratios(financials, include_provenance=False):
    actifs_totaux = financials.get('actifs_totaux')
    actifs_courants = financials.get('actifs_courants')
    dettes_courantes = financials.get('dettes_courantes')
    equity = financials.get('equity')
    revenus = financials.get('revenus')
    ebit = financials.get('ebit')
    resultat_net = financials.get('resultat_net')
    charges_interets = financials.get('charges_interets')

    pnb_reel = financials.get('pnb')
    pnb = pnb_reel if pnb_reel is not None else revenus
    pnb_n1 = financials.get('pnb_n1') if financials.get('pnb_n1') is not None else financials.get('revenus_n1')
    opex = (pnb - ebit) if (pnb is not None and ebit is not None) else None
    net_interest_income = (revenus - charges_interets) if (revenus is not None and charges_interets is not None) else None

    t1_reel = financials.get('ratio_solvabilite_t1_reel')
    ratio_solvabilite_t1 = t1_reel if t1_reel is not None else _pct(_safe_div(equity, actifs_totaux))

    result = {
        'pnb_growth': _growth_pct(pnb, pnb_n1),
        'coex': _pct(_safe_div(opex, pnb)),
        'margin_intermediation': _pct(_safe_div(net_interest_income, actifs_totaux)),
        'ratio_liquidite': _safe_div(actifs_courants, dettes_courantes),
        'taux_souffrance': financials.get('taux_souffrance_reel'),
        'cout_risque': financials.get('cout_du_risque_reel'),
        'ratio_solvabilite_t1': ratio_solvabilite_t1,
        'roa': _pct(_safe_div(resultat_net, actifs_totaux)),
    }

    if not include_provenance:
        return result

    pnb_is_proxy = pnb_reel is None and revenus is not None
    t1_is_proxy = t1_reel is None and ratio_solvabilite_t1 is not None

    return {
        'pnb_growth': _wrap_maybe_proxy(
            result['pnb_growth'], pnb_is_proxy, ('PNB', 'Revenus'),
            DataProvenance.mark_calculated, ('Évolution du PNB (ou Revenus si PNB absent) N vs N-1',)),
        'coex': _wrap_maybe_proxy(
            result['coex'], pnb_is_proxy, ('PNB', 'Revenus'),
            DataProvenance.mark_calculated, ('(PNB - EBIT) / PNB',)),
        'margin_intermediation': _wrap(
            result['margin_intermediation'], DataProvenance.mark_calculated,
            '(Revenus - Charges Intérêts) / Actifs Totaux'),
        'ratio_liquidite': _wrap(
            result['ratio_liquidite'], DataProvenance.mark_calculated,
            'Actifs Courants / Dettes Courantes'),
        'taux_souffrance': _wrap(
            result['taux_souffrance'], DataProvenance.mark_real_data,
            'Fichier Excel — Taux de Souffrance'),
        'cout_risque': _wrap(
            result['cout_risque'], DataProvenance.mark_real_data,
            'Fichier Excel — Coût du Risque'),
        'ratio_solvabilite_t1': _wrap_maybe_proxy(
            result['ratio_solvabilite_t1'], t1_is_proxy, ('Ratio Solvabilité T1', 'Equity / Actifs Totaux'),
            DataProvenance.mark_real_data, ('Fichier Excel — Ratio Solvabilité T1',)),
        'roa': _wrap(result['roa'], DataProvenance.mark_calculated, 'Résultat Net / Actifs Totaux'),
    }


def _calculate_industry_ratios(financials, include_provenance=False):
    actifs_totaux = financials.get('actifs_totaux')
    actifs_courants = financials.get('actifs_courants')
    dettes_courantes = financials.get('dettes_courantes')
    dettes = financials.get('dettes')
    equity = financials.get('equity')
    revenus = financials.get('revenus')
    ebit = financials.get('ebit')
    resultat_net = financials.get('resultat_net')
    charges_interets = financials.get('charges_interets')

    result = {
        'revenue_growth': _growth_pct(revenus, financials.get('revenus_n1')),
        'net_profit_margin': _pct(_safe_div(resultat_net, revenus)),
        'roe': _pct(_safe_div(resultat_net, equity)),
        'debt_to_equity': _safe_div(dettes, equity),
        'current_ratio': _safe_div(actifs_courants, dettes_courantes),
        'interest_coverage': _safe_div(ebit, charges_interets),
        'asset_turnover': _safe_div(revenus, actifs_totaux),
        'roa': _pct(_safe_div(resultat_net, actifs_totaux)),
    }

    if not include_provenance:
        return result

    formulas = {
        'revenue_growth': 'Évolution des Revenus N vs N-1',
        'net_profit_margin': 'Résultat Net / Revenus',
        'roe': 'Résultat Net / Capitaux Propres',
        'debt_to_equity': 'Dettes / Capitaux Propres',
        'current_ratio': 'Actifs Courants / Dettes Courantes',
        'interest_coverage': "EBIT / Charges d'Intérêts",
        'asset_turnover': 'Revenus / Actifs Totaux',
        'roa': 'Résultat Net / Actifs Totaux',
    }
    return {key: _wrap(value, DataProvenance.mark_calculated, formulas[key]) for key, value in result.items()}


def _calculate_insurance_ratios(financials, include_provenance=False):
    equity = financials.get('equity')
    revenus = financials.get('revenus')
    ebit = financials.get('ebit')
    resultat_net = financials.get('resultat_net')
    primes = financials.get('primes_emises')
    primes_nettes = financials.get('primes_nettes')
    sinistres = financials.get('sinistres')
    commissions_frais = financials.get('commissions_frais')

    technique_reelle = primes is not None and sinistres is not None
    if technique_reelle:
        # Résultat technique : Primes Nettes (net de réassurance) si le
        # fichier les distingue des Primes Brutes, sinon Primes Brutes pour
        # les deux termes -- comportement historique inchangé quand le
        # fichier ne fournit pas cette distinction.
        primes_pour_resultat = primes_nettes if primes_nettes is not None else primes
        technical_result = _pct(_safe_div(primes_pour_resultat - sinistres, primes))
        # Combined Ratio : Sinistres + Commissions/Frais si disponibles (vrai
        # Combined Ratio), sinon Sinistres seuls (Loss Ratio -- comportement
        # historique inchangé, cf. commentaire 'combined_ratio' dans sectors.py).
        charges = (sinistres + commissions_frais) if commissions_frais is not None else sinistres
        combined_ratio = _pct(_safe_div(charges, primes))
    else:
        technical_result = _pct(_safe_div(ebit, revenus))
        combined_ratio = (100 - _pct(_safe_div(resultat_net, revenus))) if _safe_div(resultat_net, revenus) is not None else None

    result = {
        'technical_result': technical_result,
        'combined_ratio': combined_ratio,
        'solvency_margin': financials.get('solvency_margin_reel'),
        'roe': _pct(_safe_div(resultat_net, equity)),
        'operating_margin': _pct(_safe_div(ebit, revenus)),
    }

    if not include_provenance:
        return result

    is_proxy = not technique_reelle
    technical_formula = ('(Primes Nettes - Sinistres) / Primes Émises' if primes_nettes is not None
                          else '(Primes Émises - Sinistres) / Primes Émises')
    combined_formula = ('(Sinistres + Commissions/Frais) / Primes Émises' if commissions_frais is not None
                         else 'Sinistres / Primes Émises')
    return {
        'technical_result': _wrap_maybe_proxy(
            result['technical_result'], is_proxy, ('Primes Émises / Sinistres', 'EBIT / Revenus'),
            DataProvenance.mark_calculated, (technical_formula,)),
        'combined_ratio': _wrap_maybe_proxy(
            result['combined_ratio'], is_proxy, ('Primes Émises / Sinistres', 'Résultat Net / Revenus'),
            DataProvenance.mark_calculated, (combined_formula,)),
        'solvency_margin': _wrap(
            result['solvency_margin'], DataProvenance.mark_real_data,
            'Fichier Excel — Marge de Solvabilité'),
        'roe': _wrap(result['roe'], DataProvenance.mark_calculated, 'Résultat Net / Capitaux Propres'),
        'operating_margin': _wrap(result['operating_margin'], DataProvenance.mark_calculated, 'EBIT / Revenus'),
    }


def _at(values, idx):
    """Accès sûr à `values[idx]` : None si l'index est hors bornes (ou < 0)."""
    if values is None or idx < 0 or idx >= len(values):
        return None
    return values[idx]


def calculate_ratios_series(series, years, include_provenance=False):
    """
    Calcule les 15 ratios génériques (cf. `calculate_ratios`) pour CHAQUE
    exercice de l'historique `series`/`years` produit par
    `data_processing.extract_financial_history`.

    Ne redéfinit aucune formule : construit un instantané plat par exercice
    (mêmes clés que le dict `financials` d'un seul exercice) et délègue à
    `calculate_ratios()`, puis transpose le résultat.

    Args:
        series: dict {champ: [valeur_annee_1, valeur_annee_2, ...]} (None si
                absent cette année-là), tel que retourné par
                `extract_financial_history()['series']`.
        years: liste des exercices, alignée sur `series`.
        include_provenance: cf. `calculate_ratios` — si True, chaque valeur
                de chaque année est enveloppée dans une structure
                `DataProvenance` plutôt qu'un float brut.

    Returns:
        dict {ratio_key: [valeur_annee_1, valeur_annee_2, ...]}, aligné sur
        `years`. Une valeur individuelle est None (ou `DataProvenance` de
        type 'na') si le ratio n'est pas calculable pour cette année précise.
        Le jeu de clés est exactement celui de `calculate_ratios({})`.
    """
    ratio_keys = list(calculate_ratios({}).keys())
    result = {key: [] for key in ratio_keys}
    for i in range(len(years)):
        snapshot = {field: _at(values, i) for field, values in series.items()}
        year_ratios = calculate_ratios(snapshot, include_provenance=include_provenance)
        for key in ratio_keys:
            result[key].append(year_ratios.get(key))
    return result


def calculate_sector_ratios_series(series, years, sector, include_provenance=False):
    """
    Équivalent de `calculate_ratios_series()` pour les ratios sectoriels
    (cf. `calculate_sector_ratios`) : un instantané plat par exercice, délégué
    à `calculate_sector_ratios()`, jamais de formule redéfinie ici.

    Pour les ratios de croissance (`pnb_growth`, `revenue_growth`), la valeur
    "N-1" utilisée pour chaque exercice `i` est `series[champ][i-1]` — la
    vraie valeur datée de l'exercice précédent dans l'historique, jamais une
    valeur fabriquée. Note : ceci n'utilise PAS les libellés "X N-1"
    explicites de l'ancien format à une seule colonne (ces libellés ne sont
    rattachés à aucune année précise et vivent uniquement dans
    `history['current']`, pas dans `series`) — un fichier à un seul exercice
    avec une ligne "Revenue N-1"/"PNB N-1" aura donc une croissance à `None`
    ici même si `calculate_sector_ratios(history['current'], sector)` calcule
    une vraie valeur pour ce même exercice à partir de cette ligne. C'est une
    divergence attendue entre les deux chemins de calcul dans ce cas précis ;
    elle ne concerne que ce cas historique et n'affecte jamais le score
    final, qui reste calculé sur `current`.

    Args:
        series: dict {champ: [valeur_annee_1, ...]}, cf. `calculate_ratios_series`.
        years: liste des exercices, alignée sur `series`.
        sector: nom du secteur (transmis tel quel à `calculate_sector_ratios`).
        include_provenance: cf. `calculate_ratios_series`.

    Returns:
        dict {ratio_key: [valeur_annee_1, ...]}, aligné sur `years`.
    """
    ratio_keys = list(calculate_sector_ratios({}, sector).keys())
    result = {key: [] for key in ratio_keys}
    for i in range(len(years)):
        snapshot = {field: _at(values, i) for field, values in series.items()}
        snapshot['revenus_n1'] = _at(series.get('revenus'), i - 1)
        snapshot['pnb_n1'] = _at(series.get('pnb'), i - 1)
        year_ratios = calculate_sector_ratios(snapshot, sector, include_provenance=include_provenance)
        for key in ratio_keys:
            result[key].append(year_ratios.get(key))
    return result
