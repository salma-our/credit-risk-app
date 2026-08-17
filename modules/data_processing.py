# modules/data_processing.py
"""
Module de traitement des données Excel.

Parse un fichier Excel au format Key-Value (`Column | Value`, un seul
exercice) ou au format historique multi-exercices (`Column | 2021 | 2022 |
... | 2025`, jusqu'à 5 colonnes-années) et extrait les données financières.

Règle stricte : si une donnée n'est pas présente dans le fichier Excel, elle
reste `None`. Aucune valeur par défaut inventée, aucune heuristique
silencieuse (ex: "resultat_net = revenus * 0.05") ne remplace une donnée
manquante. Les champs manquants sont listés dans `missing_fields`/`warnings`
et c'est au pipeline aval (ratios.py, avec ses divisions protégées) de gérer
ces `None` proprement.

Toutes les valeurs monétaires sont considérées comme déjà exprimées dans
l'unité de reporting du dossier transmis (typiquement MDH - Millions de
Dirhams pour les dossiers marocains). L'application ne les redivise jamais :
elle les affiche telles quelles avec le suffixe "MDH".
"""

import re
import pandas as pd

# Colonnes considérées comme un identifiant d'année (ex: 2022, "2022", "FY2022")
_YEAR_COL_RE = re.compile(r'(19|20)\d{2}')

# Nombre maximum d'exercices historiques conservés si le fichier en fournit
# davantage (on garde les plus récents).
MAX_HISTORY_YEARS = 5

# Sentinel identifiant les données d'une sheet au format Key-Value classique
# (une seule colonne de valeurs, sans année associée).
_SINGLE_COLUMN = object()

# ---------------------------------------------------------------------------
# Définition des champs extraits (secteur = tous sauf mention contraire) et
# des libellés Excel possibles pour chacun. Ne pas ajouter de champs ici sans
# vérifier qu'ils sont bien consommés par ratios.py / rating_engine.py.
# ---------------------------------------------------------------------------

# key -> (sheets à chercher par ordre de priorité, libellés Excel possibles)
_FIELD_SOURCES = {
    # --- Balance Sheet (tous secteurs) ---
    'actifs_totaux': (('bs',), ('Total Assets', 'total assets')),
    'actifs_courants': (('bs',), ('Current Assets', 'current assets')),
    'stocks': (('bs',), ('Inventory', 'inventory')),
    'tresorerie': (('bs',), ('Cash', 'cash')),
    'dettes_courantes': (('bs',), ('Current Liabilities', 'current liabilities')),
    'dettes': (('bs',), ('Total Debt', 'total debt', 'Long-term Debt')),
    'equity': (('bs',), ('Total Equity', 'total equity')),

    # --- Income Statement (tous secteurs) ---
    'revenus': (('income',), ('Revenue', 'revenue', 'Sales')),
    'ebit': (('income',), ('EBIT', 'ebit', 'Operating Income')),
    'resultat_net': (('income',), ('Net Income', 'net income')),
    'charges_interets': (('income',), ('Interest Expense', 'interest expense')),

    # --- Cash Flow (tous secteurs) ---
    'cash_flow_operationnel': (('cf',), ('Operating CF', 'operating cf', 'Operating Cash Flow')),

    # --- Optionnels sectoriels : Banque ---
    'pnb': (('bs', 'income', 'cf'), ('PNB', 'Produit Net Bancaire', 'Net Banking Income')),
    'credits_bancaires': (('bs', 'income', 'cf'), ('Crédits', 'Credits', 'Loans', 'Total Loans')),
    'taux_souffrance_reel': (('bs', 'income', 'cf'), ('Taux de Souffrance', 'NPL Ratio', 'Taux de souffrance')),
    'cout_du_risque_reel': (('bs', 'income', 'cf'), ('Coût du Risque', 'Cost of Risk')),
    'ratio_solvabilite_t1_reel': (('bs', 'income', 'cf'), ('Ratio Solvabilité T1', 'Tier 1 Ratio', 'CET1 Ratio')),

    # --- Optionnels sectoriels : Assurance ---
    'primes_emises': (('bs', 'income', 'cf'), ('Primes Émises', 'Gross Written Premiums', 'Primes')),
    'primes_nettes': (('bs', 'income', 'cf'), ('Primes Nettes', 'Net Premiums', 'Primes Nettes Émises')),
    'sinistres': (('bs', 'income', 'cf'), ('Sinistres', 'Claims', 'Charge des Sinistres')),
    'commissions_frais': (('bs', 'income', 'cf'), (
        'Commissions + Frais', 'Commissions et Frais', 'Commissions', 'Acquisition Costs')),
    'solvency_margin_reel': (('bs', 'income', 'cf'), ('Marge de Solvabilité', 'Solvency Margin', 'Solvency Ratio')),
}

# Champs obligatoires (tous secteurs) : s'ils sont absents sur le dernier
# exercice, un warning explicite est ajouté (cf. spec, point 3).
_REQUIRED_FIELDS = (
    'actifs_totaux', 'actifs_courants', 'stocks', 'tresorerie',
    'dettes_courantes', 'dettes', 'equity',
    'revenus', 'ebit', 'resultat_net', 'charges_interets',
    'cash_flow_operationnel',
)

# Lignes "N-1" explicites (courantes dans l'ancien format à une seule
# colonne) : prioritaires sur la valeur déduite de l'historique
# multi-exercices quand les deux sont disponibles.
_EXPLICIT_PRIOR_SOURCES = {
    'revenus_n1': (('income',), (
        'Revenue N-1', 'Prior Year Revenue', 'Revenue Prior Year',
        "Chiffre d'Affaires N-1", "CA N-1", "Revenus N-1",
    )),
    'resultat_net_n1': (('income',), ('Net Income N-1', 'Prior Year Net Income', 'Résultat Net N-1')),
    'pnb_n1': (('bs', 'income', 'cf'), ('PNB N-1', 'Prior Year PNB')),
    'credits_bancaires_n1': (('bs', 'income', 'cf'), ('Crédits N-1', 'Loans N-1')),
}

# Paires (champ courant -> champ N-1 dérivé) utilisées pour compléter
# `current` avec les mêmes clés qu'aujourd'hui.
_DERIVED_PRIOR_PAIRS = {
    'revenus_n1': 'revenus',
    'resultat_net_n1': 'resultat_net',
    'pnb_n1': 'pnb',
    'credits_bancaires_n1': 'credits_bancaires',
}

_FIELD_LABELS = {
    'actifs_totaux': 'Total des Actifs',
    'actifs_courants': 'Actifs Courants',
    'stocks': 'Stocks',
    'tresorerie': 'Trésorerie',
    'dettes_courantes': 'Dettes Courantes',
    'dettes': 'Total Dettes',
    'equity': 'Capitaux Propres',
    'revenus': "Chiffre d'Affaires",
    'ebit': 'EBIT',
    'resultat_net': 'Résultat Net',
    'charges_interets': "Charges d'Intérêts",
    'cash_flow_operationnel': 'Cash-Flow Opérationnel',
    'pnb': 'Produit Net Bancaire (PNB)',
    'credits_bancaires': 'Crédits Bancaires',
    'taux_souffrance_reel': 'Taux de Souffrance',
    'cout_du_risque_reel': 'Coût du Risque',
    'ratio_solvabilite_t1_reel': 'Ratio de Solvabilité T1',
    'primes_emises': 'Primes Émises',
    'primes_nettes': 'Primes Nettes',
    'sinistres': 'Sinistres',
    'commissions_frais': 'Commissions + Frais',
    'solvency_margin_reel': 'Marge de Solvabilité',
}


def _parse_sheet_by_year(df):
    """
    Convertit une sheet en dict `{year_label: {row_key: value}}`.

    `year_label` est soit un entier (année détectée dans l'en-tête de
    colonne), soit le sentinel `_SINGLE_COLUMN` si la sheet utilise l'ancien
    format à une seule colonne de valeurs (`Column | Value`, ou une colonne
    de valeurs sans nom explicite).
    """
    if df is None or df.empty or 'Column' not in df.columns:
        return {}

    value_cols = [c for c in df.columns if c != 'Column']

    if 'Value' in df.columns:
        cols_to_read = {_SINGLE_COLUMN: 'Value'}
    else:
        year_cols = {}
        for c in value_cols:
            m = _YEAR_COL_RE.search(str(c))
            if m:
                year_cols[int(m.group(0))] = c
        if year_cols:
            cols_to_read = year_cols
        elif len(value_cols) == 1:
            cols_to_read = {_SINGLE_COLUMN: value_cols[0]}
        else:
            return {}

    result = {}
    for year_label, col in cols_to_read.items():
        year_data = {}
        for _, row in df.iterrows():
            key = str(row['Column']).strip()
            val = row[col]
            if pd.notna(val):
                try:
                    year_data[key] = float(val)
                except (TypeError, ValueError):
                    pass
        result[year_label] = year_data
    return result


def _get_from(year_dict, *aliases):
    for alias in aliases:
        if alias in year_dict:
            return year_dict[alias]
    return None


# ---------------------------------------------------------------------------
# Actionnariat (onglet optionnel, commun aux 3 secteurs) : Actionnaire |
# % Détention | Montant (MDH) | Nature | Depuis | Notes. Pure donnée de
# visibilité (jamais consommée par ratios.py/rating_engine.py) : son
# absence ou un nom de colonne différent ne doit jamais faire échouer
# extract_financial_history() — c'est le même principe "None/vide plutôt
# qu'une exception" que le reste de ce module.
# ---------------------------------------------------------------------------

_SHAREHOLDER_SHEET_CANDIDATES = (
    'Actionnariat', 'actionnariat', 'Shareholders', 'shareholders',
)

_SHAREHOLDER_COLUMN_ALIASES = {
    'name': ('Actionnaire', 'Shareholder', 'Name'),
    'pct': ('% Détention', '% Detention', 'Pct', 'Percentage'),
    'amount': ('Montant (MDH)', 'Amount', 'Valeur'),
    'nature': ('Nature', 'Type', 'Catégorie', 'Categorie'),
    'since': ('Depuis', 'Since', 'Année', 'Annee'),
    'notes': ('Notes', 'Commentaires', 'Remarks'),
}


def _get_column(row, aliases):
    """Cherche une valeur de `row` par variantes de noms de colonnes
    (l'onglet Actionnariat n'impose pas un intitulé exact)."""
    for alias in aliases:
        if alias in row.index:
            val = row[alias]
            if pd.notna(val):
                return val
    return None


def _load_shareholders(file):
    """
    Lit l'onglet Actionnariat (optionnel) d'un template Excel — même
    structure pour les 3 secteurs. Onglet absent (nom différent de
    `_SHAREHOLDER_SHEET_CANDIDATES`) ou illisible -> liste vide, jamais
    d'exception.

    Returns:
        list[dict] : [{'name', 'pct', 'amount', 'nature', 'since', 'notes'}, ...]
    """
    df = None
    for sheet_name in _SHAREHOLDER_SHEET_CANDIDATES:
        try:
            df = pd.read_excel(file, sheet_name=sheet_name, header=0)
            break
        except ValueError:
            continue
        except Exception as e:
            print(f"Erreur lecture onglet Actionnariat : {e}")
            return []

    if df is None or df.empty:
        return []

    first_col = df.columns[0]
    shareholders = []
    for _, row in df.iterrows():
        name = _get_column(row, _SHAREHOLDER_COLUMN_ALIASES['name'])
        if name is None:
            # Repli sur la 1ère colonne si aucun intitulé connu ne matche
            # (ex: fichier avec un en-tête non standard).
            raw_first = row[first_col]
            name = raw_first if pd.notna(raw_first) else None
        if name is None or str(name).strip().upper() == 'TOTAL':
            continue
        shareholders.append({
            'name': name,
            'pct': _get_column(row, _SHAREHOLDER_COLUMN_ALIASES['pct']),
            'amount': _get_column(row, _SHAREHOLDER_COLUMN_ALIASES['amount']),
            'nature': _get_column(row, _SHAREHOLDER_COLUMN_ALIASES['nature']),
            'since': _get_column(row, _SHAREHOLDER_COLUMN_ALIASES['since']),
            'notes': _get_column(row, _SHAREHOLDER_COLUMN_ALIASES['notes']),
        })
    return shareholders


def extract_financial_history(file, sector):
    """
    Parse le fichier Excel (3 sheets: Balance Sheet, Income Statement, Cash
    Flow) et retourne l'historique complet détecté (1 à 5 exercices) :

    {
        'years': [2021, 2022, 2023, 2024, 2025],
        'series': {'actifs_totaux': [340.0, 355.0, None, 401.0, 420.0], ...},
        'current': {...},          # dernier exercice, mêmes clés qu'avant
        'missing_fields': [...],   # jamais renseignés sur aucun exercice
        'warnings': [...],
        'sector': sector,
    }

    Compatible avec l'ancien format à une seule colonne `Column | Value`
    (dans ce cas `years == [None]`, un seul exercice sans année connue).
    """
    bs = pd.read_excel(file, sheet_name='Balance Sheet')
    income = pd.read_excel(file, sheet_name='Income Statement')
    cf = pd.read_excel(file, sheet_name='Cash Flow')
    shareholders = _load_shareholders(file)

    bs_by_year = _parse_sheet_by_year(bs)
    income_by_year = _parse_sheet_by_year(income)
    cf_by_year = _parse_sheet_by_year(cf)
    sheet_maps = {'bs': bs_by_year, 'income': income_by_year, 'cf': cf_by_year}

    real_years = sorted({
        y for d in sheet_maps.values() for y in d if y is not _SINGLE_COLUMN
    })

    truncated_years = []
    if len(real_years) > MAX_HISTORY_YEARS:
        truncated_years = real_years[:-MAX_HISTORY_YEARS]
        real_years = real_years[-MAX_HISTORY_YEARS:]

    anchor_year = real_years[-1] if real_years else None
    years = real_years if real_years else [None]

    def resolve(sheet_by_year, year):
        """Dict {row_key: value} de la sheet pour `year`, en retombant sur
        les données au format ancienne (une seule colonne) si elles existent
        et que `year` correspond à l'exercice le plus récent (ancre)."""
        if year in sheet_by_year:
            return sheet_by_year[year]
        if year == anchor_year and _SINGLE_COLUMN in sheet_by_year:
            return sheet_by_year[_SINGLE_COLUMN]
        return {}

    def series_for(sheets, aliases):
        values = []
        for y in years:
            val = None
            for s in sheets:
                val = _get_from(resolve(sheet_maps[s], y), *aliases)
                if val is not None:
                    break
            values.append(val)
        return values

    series = {key: series_for(sheets, aliases) for key, (sheets, aliases) in _FIELD_SOURCES.items()}

    # Lignes "N-1" explicites, cherchées uniquement sur l'exercice le plus
    # récent (c'est là que l'ancien format à une colonne les plaçait).
    explicit_prior = {}
    for key, (sheets, aliases) in _EXPLICIT_PRIOR_SOURCES.items():
        val = None
        for s in sheets:
            val = _get_from(resolve(sheet_maps[s], anchor_year), *aliases)
            if val is not None:
                break
        explicit_prior[key] = val

    # --- current : dernier exercice disponible, mêmes clés qu'avant ---
    current = {key: (values[-1] if values else None) for key, values in series.items()}

    for n1_key, base_key in _DERIVED_PRIOR_PAIRS.items():
        if explicit_prior.get(n1_key) is not None:
            current[n1_key] = explicit_prior[n1_key]
        else:
            base_series = series.get(base_key) or []
            current[n1_key] = base_series[-2] if len(base_series) >= 2 else None

    current['secteur'] = sector
    # Bénéfices non répartis : jamais fourni par le template Excel (pas de
    # ligne "Retained Earnings"). Non consommé par ratios.py aujourd'hui ;
    # gardé à None plutôt que reconstitué par heuristique (net_income * 0.5).
    current['benefices_non_repartis'] = None

    # --- missing_fields : champs jamais renseignés, sur aucun exercice ---
    missing_fields = [key for key, values in series.items() if all(v is None for v in values)]

    # --- warnings ---
    warnings = []
    if truncated_years:
        warnings.append(
            f"Le fichier fournit plus de {MAX_HISTORY_YEARS} exercices ; seuls les "
            f"{MAX_HISTORY_YEARS} plus récents ({real_years[0]}-{real_years[-1]}) sont conservés."
        )
    if years == [None]:
        warnings.append(
            f"Historique incomplet : 1 exercice fourni sur {MAX_HISTORY_YEARS} attendus "
            "(année non renseignée dans le fichier, format Column | Value)."
        )
    elif len(years) < MAX_HISTORY_YEARS:
        warnings.append(
            f"Historique incomplet : {len(years)} exercice(s) fourni(s) sur {MAX_HISTORY_YEARS} attendus."
        )

    for key in missing_fields:
        warnings.append(f"Champ '{_FIELD_LABELS.get(key, key)}' absent de tous les exercices fournis.")

    last_year_label = years[-1] if years[-1] is not None else "l'exercice courant"
    for key in _REQUIRED_FIELDS:
        if key not in missing_fields and current.get(key) is None:
            warnings.append(
                f"Champ obligatoire '{_FIELD_LABELS.get(key, key)}' absent sur le dernier "
                f"exercice ({last_year_label}) bien que renseigné sur un exercice antérieur."
            )

    return {
        'years': years,
        'series': series,
        'current': current,
        'missing_fields': missing_fields,
        'warnings': warnings,
        'sector': sector,
        'shareholders': shareholders,
    }


def process_excel(file, sector):
    """
    Point d'entrée historique, conservé pour compatibilité avec app.py /
    ratios.py / rating_engine.py : parse le fichier Excel (Key-Value ou
    multi-exercices) et retourne un dict plat "exercice courant" avec les
    mêmes clés qu'avant cette refonte.

    En interne, délègue à `extract_financial_history()` et retourne
    `history['current']`. En cas d'échec de parsing, retourne
    `{'error': str(e)}` (comportement inchangé).
    """
    try:
        print(f"Parsing Excel pour secteur: {sector}")
        history = extract_financial_history(file, sector)
        if history['warnings']:
            print(f"Avertissements data_processing: {history['warnings']}")
        print("Financials extraits avec succes")
        return history['current']

    except Exception as e:
        print(f"Erreur data_processing: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'error': str(e)}
