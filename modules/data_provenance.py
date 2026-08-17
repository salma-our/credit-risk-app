# modules/data_provenance.py
"""
Traçabilité des données : annote chaque valeur affichée (ratio, poste
financier, benchmark) avec sa provenance — donnée réelle du fichier Excel,
ratio calculé, proxy (approximation faute de donnée réelle) ou benchmark. Le
but est qu'aucune valeur ne s'affiche dans le rapport sans que son origine
soit connue et vérifiable, et qu'un proxy ne soit jamais présenté comme une
donnée réelle.

Ce module ne calcule rien : il enveloppe une valeur déjà calculée ailleurs
(ratios.py, data_processing.py) dans une structure homogène.
"""


class DataProvenance:
    """Annote une valeur avec sa provenance (data réelle / proxy / benchmark)."""

    TYPES = {
        'real_data': 'Donnée réelle (fichier Excel)',
        'calculated_ratio': 'Ratio calculé',
        'benchmark': 'Valeur de référence',
        'proxy': 'Approximation (donnée réelle indisponible)',
        'na': 'Donnée indisponible',
    }

    @staticmethod
    def create(value, type_, source_desc=None, benchmark_info=None):
        """
        Returns:
        {
            'value': float or None,
            'type': str ('real_data' | 'calculated_ratio' | 'benchmark' | 'proxy' | 'na'),
            'source': str (ex: "Fichier Excel — Colonne Revenue"),
            'benchmark': {
                'value': float,
                'source_type': str ('internal' | 'sectoral' | 'regulatory'),
                'label': str (ex: "Benchmark interne — provisoire"),
                'year': int,
            } or None,
        }
        """
        return {
            'value': value,
            'type': type_,
            'source': source_desc,
            'benchmark': benchmark_info,
        }

    @staticmethod
    def mark_real_data(value, source_desc):
        """Donnée extraite du fichier Excel."""
        return DataProvenance.create(value, 'real_data', source_desc)

    @staticmethod
    def mark_calculated(value, formula_desc):
        """Ratio calculé (ex: "Net Income / Total Assets")."""
        return DataProvenance.create(value, 'calculated_ratio', formula_desc)

    @staticmethod
    def mark_proxy(value, original_data_type, alternative_used):
        """Proxy : donnée réelle indisponible, approximation utilisée."""
        source = f"Proxy — {original_data_type} indisponible, {alternative_used} utilisé"
        return DataProvenance.create(value, 'proxy', source)

    @staticmethod
    def mark_na(reason=None):
        """Donnée complètement indisponible."""
        return DataProvenance.create(None, 'na', reason or 'Donnée non disponible')

    @staticmethod
    def is_proxy(entry):
        return bool(entry) and entry.get('type') == 'proxy'

    @staticmethod
    def is_available(entry):
        return bool(entry) and entry.get('value') is not None and entry.get('type') != 'na'
