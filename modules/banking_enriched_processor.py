# modules/banking_enriched_processor.py
"""
Lecteur du template bancaire enrichi (8 onglets) — module autonome, non
branché sur le pipeline générique de l'app (modules/data_processing.py reste
l'unique source pour la route /analyze).

Cible un template Excel dédié BANKING_TEMPLATE_ENRICHI_V2.xlsx, à structure
fixe et 100% banque :
    1. Bilan            (labels en colonne A, 2021-2025 en colonnes B-F)
    2. P&L               (idem)
    3. Flux               (idem)
    4. Portefeuille       (tableau par secteur économique)
    5. Actionnariat       (tableau actionnaires + section MANAGEMENT)
    6. Ratios             (ratios clés vs benchmark BAM)
    7. Qualitatives       (paires libellé/texte)
    8. Traçabilité        (source/page/statut de vérification par donnée)

Contrairement au parseur générique, une ligne, une colonne ou un onglet
absent ne fait jamais planter le chargement : la valeur reste `None` (ou la
structure reste vide) et un message est ajouté à `self.warnings`.
"""

from pathlib import Path

import numpy as np
import pandas as pd

YEARS = [2021, 2022, 2023, 2024, 2025]
# Colonne Excel (0-indexée, header=None) associée à chaque année dans les
# onglets Bilan / P&L / Flux : colonne A = labels (0), B-F = 2021-2025 (1-5).
_YEAR_COLUMNS = {year: i + 1 for i, year in enumerate(YEARS)}


class BankingDataProcessor:
    """
    Traite les données bancaires enrichies du template Excel.
    Lit 8 onglets, valide, calcule ratios, prépare pour scoring.
    """

    def __init__(self, excel_path):
        self.excel_path = Path(excel_path)
        self.data = {}
        self.years = YEARS
        self.current_year = YEARS[-1]  # Année d'analyse
        self.warnings = []

    # ------------------------------------------------------------------
    # Entrée principale
    # ------------------------------------------------------------------

    def load_all_sheets(self):
        """Charge les 8 onglets, valide leur cohérence et calcule les
        indicateurs. Ne lève que si le fichier lui-même est illisible
        (chemin invalide, fichier corrompu) ; les données manquantes à
        l'intérieur d'un onglet ne font que générer des warnings."""
        if not self.excel_path.exists():
            raise ValueError(f"Fichier introuvable : {self.excel_path}")

        self.warnings = []

        self.data = {
            'bilan': self._load_labeled_series('1. Bilan', {
                'total_actif': 'TOTAL ACTIF',
                'credits': 'Crédits à la clientèle',
                'total_passif': 'TOTAL PASSIF',
                'deposits': 'Dépôts de la clientèle',
                'equity': 'TOTAL CAPITAUX PROPRES',
            }),
            'pl': self._load_labeled_series('2. P&L', {
                'pnb': 'Produit Net Bancaire',
                'fees': 'Frais généraux',
                'cost_of_risk': 'Coût du risque',
                'net_income': 'RÉSULTAT NET',
            }, absolute_keys={'fees', 'cost_of_risk'}),
            'cf': self._load_labeled_series('3. Flux', {
                'operating_cf': 'FLUX EXPLOITATION',
                'cash_end': 'Trésorerie fin',
            }),
            'portfolio': self._load_portfolio(),
            'shareholders': self._load_shareholders(),
            'management': self._load_management(),
            'benchmarks': self._load_benchmarks(),
            'qualitative': self._load_qualitative(),
            'traceability': self._load_traceability(),
        }

        self._validate_data()
        self._calculate_indicators()
        self.data['warnings'] = self.warnings

        return self.data

    # ------------------------------------------------------------------
    # Helpers bas niveau (lecture résiliente)
    # ------------------------------------------------------------------

    def _read_sheet(self, sheet_name, **kwargs):
        try:
            return pd.read_excel(self.excel_path, sheet_name=sheet_name, **kwargs)
        except Exception as e:
            self.warnings.append(f"Onglet '{sheet_name}' illisible : {e}")
            return None

    @staticmethod
    def _to_float(val):
        if val is None or pd.isna(val):
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _find_row(self, df, label_substr):
        """Index de la première ligne dont la colonne 0 contient
        `label_substr`, ou None si absente/onglet illisible."""
        if df is None or df.empty or 0 not in df.columns:
            return None
        mask = df[0].astype(str).str.contains(label_substr, na=False, regex=False)
        matches = df.index[mask]
        return matches[0] if len(matches) else None

    def _year_values(self, df, idx):
        """Dict {année: float|None} pour la ligne `idx` d'un onglet
        Bilan/P&L/Flux (colonnes B-F = 2021-2025)."""
        values = {}
        for year, col in _YEAR_COLUMNS.items():
            val = None
            if idx is not None and df is not None and col in df.columns:
                val = self._to_float(df.loc[idx, col])
            values[year] = val
        return values

    def _missing_columns(self, df, sheet_name, required_cols):
        if df is None:
            return True
        missing = required_cols - set(df.columns)
        if missing:
            self.warnings.append(
                f"Onglet '{sheet_name}' : colonnes manquantes {sorted(missing)}."
            )
            return True
        return False

    # ------------------------------------------------------------------
    # LOADERS (un par onglet)
    # ------------------------------------------------------------------

    def _load_labeled_series(self, sheet_name, label_map, absolute_keys=None):
        """Onglets 1/2/3 (Bilan, P&L, Flux) : lignes identifiées par un
        libellé en colonne A, valeurs 2021-2025 en colonnes B-F."""
        absolute_keys = absolute_keys or set()
        df = self._read_sheet(sheet_name, header=None)

        series = {}
        for key, label in label_map.items():
            idx = self._find_row(df, label)
            if idx is None and df is not None:
                self.warnings.append(f"Ligne '{label}' introuvable dans l'onglet '{sheet_name}'.")
            values = self._year_values(df, idx)
            if key in absolute_keys:
                values = {y: (abs(v) if v is not None else None) for y, v in values.items()}
            series[key] = values
        return series

    def _load_portfolio(self):
        """Onglet 4 : Portefeuille Crédit par Secteur."""
        sheet_name = '4. Portefeuille'
        df = self._read_sheet(sheet_name, header=2)
        portfolio = {}
        required = {'Secteur économique', 'Montant (MDH)', '% Portefeuille', 'NPL (%)', 'Provision (MDH)'}
        if self._missing_columns(df, sheet_name, required):
            return portfolio

        for _, row in df.iterrows():
            sector = row['Secteur économique']
            if pd.isna(sector) or str(sector).strip().upper() == 'TOTAL':
                continue
            portfolio[sector] = {
                'amount': self._to_float(row['Montant (MDH)']),
                'pct': self._to_float(row['% Portefeuille']),
                'npl': self._to_float(row['NPL (%)']),
                'provision': self._to_float(row['Provision (MDH)']),
            }
        return portfolio

    def _load_shareholders(self):
        """Onglet 5 : Actionnariat (3 lignes attendues)."""
        sheet_name = '5. Actionnariat'
        df = self._read_sheet(sheet_name, header=2, nrows=3)
        shareholders = []
        required = {'Actionnaire', '% Détention', 'Montant (MDH)', 'Nature', 'Depuis'}
        if self._missing_columns(df, sheet_name, required):
            return shareholders

        for _, row in df.iterrows():
            if pd.isna(row['Actionnaire']):
                continue
            shareholders.append({
                'name': row['Actionnaire'],
                'pct': self._to_float(row['% Détention']),
                'amount': self._to_float(row['Montant (MDH)']),
                'nature': row['Nature'],
                'since': row['Depuis'],
            })
        return shareholders

    def _load_management(self):
        """Onglet 5 (suite) : équipe de direction, sous la section
        'MANAGEMENT' (2 lignes plus bas, 4 lignes de données)."""
        sheet_name = '5. Actionnariat'
        df = self._read_sheet(sheet_name, header=None)
        management = []

        mgmt_idx = self._find_row(df, 'MANAGEMENT')
        if mgmt_idx is None:
            if df is not None:
                self.warnings.append(f"Section 'MANAGEMENT' introuvable dans l'onglet '{sheet_name}'.")
            return management

        start = mgmt_idx + 2
        for i in range(start, start + 4):
            if i not in df.index:
                continue
            post = df.loc[i, 0] if 0 in df.columns else None
            if pd.isna(post):
                continue
            management.append({
                'post': post,
                'name': df.loc[i, 1] if 1 in df.columns else None,
                'experience': df.loc[i, 2] if 2 in df.columns else None,
                'since': df.loc[i, 3] if 3 in df.columns else None,
            })
        return management

    def _load_benchmarks(self):
        """Onglet 6 : Ratios Clés (références BAM)."""
        sheet_name = '6. Ratios'
        df = self._read_sheet(sheet_name, header=2)
        benchmarks = {}
        required = {'Ratio', '2025', 'Benchmark BAM'}
        if self._missing_columns(df, sheet_name, required):
            return benchmarks

        for _, row in df.iterrows():
            ratio_name = row['Ratio']
            if pd.isna(ratio_name):
                continue
            benchmarks[ratio_name] = {
                '2025': self._to_float(row['2025']),
                'benchmark': self._to_float(row['Benchmark BAM']),
            }
        return benchmarks

    def _load_qualitative(self):
        """Onglet 7 : Données Qualitatives (paires libellé/texte)."""
        sheet_name = '7. Qualitatives'
        df = self._read_sheet(sheet_name, header=None)
        qualitative = {}
        if df is None or 0 not in df.columns or 1 not in df.columns:
            return qualitative

        for _, row in df.iterrows():
            label, value = row[0], row[1]
            if pd.notna(label) and pd.notna(value):
                qualitative[label] = value
        return qualitative

    def _load_traceability(self):
        """Onglet 8 : Traçabilité (source + page par donnée)."""
        sheet_name = '8. Traçabilité'
        df = self._read_sheet(sheet_name, header=2)
        traceability = {}
        required = {'Donnée', 'Source (Note/Section)', 'Page', 'Vérifiée'}
        if self._missing_columns(df, sheet_name, required):
            return traceability

        for _, row in df.iterrows():
            data_label = row['Donnée']
            if pd.isna(data_label):
                continue
            traceability[data_label] = {
                'source': row['Source (Note/Section)'],
                'page': row['Page'],
                'verified': row['Vérifiée'],
            }
        return traceability

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------

    def _validate_data(self):
        """Valide la cohérence du bilan. N'importe quelle valeur manquante
        est simplement ignorée (déjà signalée par les loaders)."""
        bilan = self.data['bilan']
        for year in self.years:
            actif = bilan['total_actif'].get(year)
            passif = bilan['total_passif'].get(year)
            equity = bilan['equity'].get(year)
            credits = bilan['credits'].get(year)

            if actif is not None and passif is not None and equity is not None:
                if abs(actif - (passif + equity)) > abs(actif) * 0.01:
                    self.warnings.append(
                        f"Bilan {year} non équilibré : Actif={actif}, Passif+Capitaux={passif + equity}"
                    )

            if actif is not None and credits is not None and credits > actif:
                self.warnings.append(f"Crédits {year} > Actif total ({credits} > {actif}).")

    # ------------------------------------------------------------------
    # CALCUL INDICATEURS
    # ------------------------------------------------------------------

    def _calculate_indicators(self):
        """Calcule les indicateurs consommés par le moteur de scoring.
        Un indicateur reste absent (clé non renseignée dans le dict année)
        si une des données sources manque, plutôt que d'être calculé à
        partir d'une valeur inventée."""
        bilan, pl = self.data['bilan'], self.data['pl']
        indicators = {'roa': {}, 'roe': {}, 'cost_of_risk_ratio': {}, 'coex': {}, 'loan_to_deposit': {}}

        for year in self.years:
            net_income = pl['net_income'].get(year)
            avg_actif = self._average(bilan['total_actif'].get(year), bilan['total_actif'].get(year - 1))
            avg_equity = self._average(bilan['equity'].get(year), bilan['equity'].get(year - 1))

            if net_income is not None and avg_actif:
                indicators['roa'][year] = (net_income / avg_actif) * 100
            if net_income is not None and avg_equity:
                indicators['roe'][year] = (net_income / avg_equity) * 100

            pnb = pl['pnb'].get(year)
            cor = pl['cost_of_risk'].get(year)
            if pnb and cor is not None:
                indicators['cost_of_risk_ratio'][year] = (cor / pnb) * 100

            fees = pl['fees'].get(year)
            if pnb and fees is not None:
                indicators['coex'][year] = (fees / pnb) * 100

            credits = bilan['credits'].get(year)
            deposits = bilan['deposits'].get(year)
            if deposits and credits is not None:
                indicators['loan_to_deposit'][year] = credits / deposits

        indicators['tcam_pnb'] = self._calculate_tcam(pl['pnb'].get(2021), pl['pnb'].get(2025), years=4)
        indicators['tcam_credits'] = self._calculate_tcam(
            bilan['credits'].get(2021), bilan['credits'].get(2025), years=4)

        indicators['sector_concentration'] = self._calculate_concentration()

        npl_values = [v['npl'] for v in self.data['portfolio'].values() if v.get('npl') is not None]
        indicators['avg_npl'] = float(np.mean(npl_values)) if npl_values else None

        self.data['indicators'] = indicators

    @staticmethod
    def _average(current, prior):
        """Moyenne (année, année-1). Si l'année précédente manque (ex: 2021,
        pas de 2020), retombe sur la valeur de l'année courante seule plutôt
        que de fausser la moyenne avec un 0 inventé."""
        if current is None:
            return None
        if prior is None:
            return current
        return (current + prior) / 2

    @staticmethod
    def _calculate_tcam(value_start, value_end, years):
        """Calcule le TCAM (Taux de Croissance Annuel Moyen)."""
        if not value_start or value_start <= 0 or value_end is None:
            return None
        return ((value_end / value_start) ** (1 / years) - 1) * 100

    def _calculate_concentration(self):
        """Concentration crédit (top 5 + top 10 secteurs)."""
        amounts = [s['amount'] for s in self.data['portfolio'].values() if s.get('amount') is not None]
        if not amounts:
            return {'top5_pct': None, 'top10_pct': None}

        total = sum(amounts)
        sorted_amounts = sorted(amounts, reverse=True)
        top5 = sum(sorted_amounts[:5])
        top10 = sum(sorted_amounts[:10])

        return {
            'top5_pct': (top5 / total * 100) if total else None,
            'top10_pct': (top10 / total * 100) if total else None,
        }

    # ------------------------------------------------------------------
    # EXPORTS (pour scoring)
    # ------------------------------------------------------------------

    def get_ratios_series(self):
        """Export ratios pour charts/scoring."""
        ind = self.data['indicators']
        return {
            'roa': ind['roa'],
            'roe': ind['roe'],
            'cost_of_risk': ind['cost_of_risk_ratio'],
            'coex': ind['coex'],
            'loan_to_deposit': ind['loan_to_deposit'],
        }

    def get_financial_summary(self):
        """Export résumé financier (année courante)."""
        y = self.current_year
        bilan, pl = self.data['bilan'], self.data['pl']
        return {
            'total_actif': bilan['total_actif'].get(y),
            'credits': bilan['credits'].get(y),
            'deposits': bilan['deposits'].get(y),
            'equity': bilan['equity'].get(y),
            'pnb': pl['pnb'].get(y),
            'net_income': pl['net_income'].get(y),
            'cost_of_risk': pl['cost_of_risk'].get(y),
        }

    def get_portfolio_summary(self):
        """Export portefeuille crédit."""
        return self.data['portfolio']

    def get_governance_summary(self):
        """Export actionnariat + management."""
        return {
            'shareholders': self.data['shareholders'],
            'management': self.data['management'],
        }

    def get_warnings(self):
        """Liste des anomalies rencontrées pendant le chargement (lignes,
        colonnes ou onglets manquants, bilan déséquilibré, etc.)."""
        return self.warnings

    def get_all_data(self):
        """Export complet (pour scoring avancé)."""
        return self.data


# ---------------------------------------------------------------------------
# Adaptateurs vers le moteur de notation existant (modules/rating_engine.py,
# modules/sectors.py) : traduisent les indicateurs du template enrichi vers
# les clés de ratios attendues par SectorConfig.SECTORS['banking']['ratios'],
# pour réutiliser RatingEngine/build_rating tel quel (score inchangé — seule
# la source des ratios change). Un indicateur sans équivalent réel dans le
# template enrichi (margin_intermediation, ratio_liquidite) reste `None` et
# est simplement exclu du score pondéré, comme n'importe quel ratio manquant
# ailleurs dans l'application (cf. RatingEngine.calculate_financial_score) —
# jamais une valeur reconstituée par heuristique.
# ---------------------------------------------------------------------------

def _require_loaded(processor):
    if not processor.data:
        raise ValueError("load_all_sheets() doit être appelé avant d'utiliser cet adaptateur.")


def _pnb_growth(pl, year):
    prev, cur = pl['pnb'].get(year - 1), pl['pnb'].get(year)
    if not prev or cur is None:
        return None
    return (cur - prev) / abs(prev) * 100


def _benchmark_value(benchmarks, *labels):
    """Valeur '2025' du premier libellé trouvé dans l'onglet '6. Ratios'
    (seule source réelle pour taux_souffrance/ratio_solvabilite_t1 : ces
    deux indicateurs ne sont pas dérivables du Bilan/P&L/Flux du template)."""
    for label in labels:
        entry = benchmarks.get(label)
        if entry and entry.get('2025') is not None:
            return entry['2025']
    return None


def map_to_sector_ratios(processor):
    """Instantané (exercice courant) des ratios sectoriels bancaires, au
    format attendu par `rating_engine.build_rating(sector, ratios,
    sector_ratios)`."""
    _require_loaded(processor)
    y = processor.current_year
    pl, ind, benchmarks = processor.data['pl'], processor.data['indicators'], processor.data['benchmarks']

    return {
        'pnb_growth': _pnb_growth(pl, y),
        'coex': ind['coex'].get(y),
        'margin_intermediation': None,
        'ratio_liquidite': None,
        'taux_souffrance': _benchmark_value(benchmarks, 'Taux de souffrance'),
        'cout_risque': ind['cost_of_risk_ratio'].get(y),
        'ratio_solvabilite_t1': _benchmark_value(benchmarks, 'Ratio de solvabilité T1'),
        'roa': ind['roa'].get(y),
    }


def map_to_sector_ratio_series(processor):
    """Équivalent multi-exercices de `map_to_sector_ratios()`, pour la
    détection de tendance (cf. `risk_drivers.identify_risk_drivers`).
    'taux_souffrance'/'ratio_solvabilite_t1' n'existent que pour l'exercice
    courant dans l'onglet '6. Ratios' (pas d'historique dans le template) :
    la série ne contient donc qu'un seul point non-None plutôt qu'une valeur
    reconduite artificiellement sur 5 ans."""
    _require_loaded(processor)
    years = processor.years
    pl, ind, benchmarks = processor.data['pl'], processor.data['indicators'], processor.data['benchmarks']

    def _series(indicator_dict):
        return [indicator_dict.get(yr) for yr in years]

    def _single_point(value):
        return [value if yr == processor.current_year else None for yr in years]

    return {
        'pnb_growth': [_pnb_growth(pl, yr) for yr in years],
        'coex': _series(ind['coex']),
        'margin_intermediation': [None] * len(years),
        'ratio_liquidite': [None] * len(years),
        'taux_souffrance': _single_point(_benchmark_value(benchmarks, 'Taux de souffrance')),
        'cout_risque': _series(ind['cost_of_risk_ratio']),
        'ratio_solvabilite_t1': _single_point(_benchmark_value(benchmarks, 'Ratio de solvabilité T1')),
        'roa': _series(ind['roa']),
    }
