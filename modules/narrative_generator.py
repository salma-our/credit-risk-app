# modules/narrative_generator.py
"""
Génération de texte factuel pour le rapport : interprétation de tendance
(1-2 phrases par graphique) et synthèse de la Synthèse Exécutive.

Principe directeur : toute phrase générée ici ne décrit que des chiffres
réellement observés dans les séries transmises (direction, amplitude,
momentum, position par rapport à un benchmark) — jamais d'extrapolation ni
d'explication causale inventée ("car la conjoncture...", etc.).
"""

# KPI affichés en Synthèse Exécutive, par secteur : (clé dans sector_ratios
# ou financials, libellé, unité). 'primes_emises' n'est pas un ratio calculé
# mais un poste brut du fichier Excel (financials), les autres viennent de
# `calculate_sector_ratios`.
KPI_SPECS = {
    'banking': [
        ('roa', 'sector_ratios', 'ROA', '%'),
        ('ratio_solvabilite_t1', 'sector_ratios', 'Ratio Solvabilité Tier 1', '%'),
        ('ratio_liquidite', 'sector_ratios', 'Ratio Liquidité', 'x'),
    ],
    'industry': [
        ('revenue_growth', 'sector_ratios', 'Croissance du CA', '%'),
        ('roe', 'sector_ratios', 'ROE', '%'),
        ('debt_to_equity', 'sector_ratios', 'Debt-to-Equity', 'x'),
    ],
    'insurance': [
        ('primes_emises', 'financials', 'Primes Émises', 'MDH'),
        ('combined_ratio', 'sector_ratios', 'Loss Ratio', '%'),
        ('solvency_margin', 'sector_ratios', 'Marge de Solvabilité', '%'),
    ],
}


def _sector_key(sector):
    s = str(sector or '').strip().lower()
    if 'bank' in s or 'banq' in s:
        return 'banking'
    if 'insur' in s or 'assur' in s:
        return 'insurance'
    return 'industry'


class NarrativeGenerator:
    """Génère des interprétations factuelles 1-2 phrases par graphique et la synthèse exécutive."""

    @staticmethod
    def skip_narrative_for_missing_data(series):
        """Retourne True si la série n'a pas assez de points pour une narration (< 2 valeurs non-None)."""
        valid_points = [v for v in (series or []) if v is not None]
        return len(valid_points) < 2

    @staticmethod
    def _trend_fragment(indicator_name, series, years, unit=''):
        """
        Fragment factuel commun à `interpret_trend` (1 série) et
        `interpret_dual_trend` (2 séries sur le même graphique, ex: ROA vs
        ROE) : direction + amplitude + momentum, sans le point final ni la
        comparaison benchmark (ajoutés séparément par l'appelant selon le
        cas d'usage).

        Returns:
            (phrase, last_y, last_v, delta) ou (None, None, None, None) si
            pas assez de données (cf. `skip_narrative_for_missing_data`).
        """
        if NarrativeGenerator.skip_narrative_for_missing_data(series):
            return None, None, None, None

        pairs = [(y, v) for y, v in zip(years or [], series or []) if v is not None]
        first_y, first_v = pairs[0]
        last_y, last_v = pairs[-1]
        delta = last_v - first_v

        if abs(delta) < 1e-9:
            trend_txt = "reste stable"
        else:
            verb = "progresse" if delta > 0 else "recule"
            rel = abs(delta) / abs(first_v) if first_v not in (0, None) else None
            if rel is None:
                amplitude = ""
            elif rel < 0.05:
                amplitude = "légèrement"
            elif rel < 0.20:
                amplitude = "modérément"
            else:
                amplitude = "fortement"
            trend_txt = f"{verb} {amplitude}".strip()

        phrase = (f"{indicator_name} {trend_txt} de {first_v:,.2f}{unit} ({first_y}) "
                  f"à {last_v:,.2f}{unit} ({last_y})")

        # Momentum : le dernier mouvement confirme-t-il ou inverse-t-il la
        # tendance d'ensemble ? (seulement si un 3e point permet de le dire)
        if len(pairs) >= 3 and abs(delta) > 1e-9:
            prev_v = pairs[-2][1]
            recent_delta = last_v - prev_v
            if abs(recent_delta) > 1e-9:
                same_direction = (recent_delta > 0) == (delta > 0)
                phrase += ", confirmé sur le dernier exercice" if same_direction \
                    else ", mais s'inverse sur le dernier exercice"

        return phrase, last_y, last_v, delta

    @staticmethod
    def interpret_trend(indicator_name, series, years, benchmark=None, unit=''):
        """
        Génère 1-2 phrases factuelles sur la tendance d'un indicateur.

        Args:
            indicator_name: "ROA", "Coût du Risque", etc.
            series: [val_annee_1, ..., val_annee_n] (None si absent cette année-là)
            years: [annee_1, ..., annee_n], aligné sur `series`
            benchmark: {'value': X, ...} optionnel (cf. sectors.py 'benchmarks')
            unit: '%', 'MDH', 'x', ''

        Returns:
            str, ou None si pas assez de données pour une narration factuelle
            (cf. `skip_narrative_for_missing_data`).
        """
        phrase, last_y, last_v, _delta = NarrativeGenerator._trend_fragment(indicator_name, series, years, unit)
        if phrase is None:
            return None
        phrase += "."

        if benchmark and benchmark.get('value') is not None:
            bv = benchmark['value']
            if abs(last_v - bv) < 1e-9:
                position = "au niveau du"
            elif last_v > bv:
                position = "au-dessus du"
            else:
                position = "en-dessous du"
            phrase += f" Dernière valeur ({last_y}) {position} benchmark ({bv:,.2f}{unit})."

        return phrase

    @staticmethod
    def interpret_dual_trend(label1, series1, label2, series2, years, unit=''):
        """
        Génère 1-2 phrases factuelles comparant l'évolution de 2 indicateurs
        tracés sur le MÊME graphique (ex: ROA vs ROE) — contrairement à
        `interpret_trend` qui ne mentionne qu'une série, décrit la tendance
        des deux et, si elles divergent nettement, laquelle varie le plus
        (comparaison factuelle d'amplitude — jamais d'explication causale
        inventée, cf. principe directeur du module).

        Returns:
            str, ou None si aucune des deux séries n'a assez de données.
        """
        frag1, _y1, _v1, d1 = NarrativeGenerator._trend_fragment(label1, series1, years, unit)
        frag2, _y2, _v2, d2 = NarrativeGenerator._trend_fragment(label2, series2, years, unit)

        if frag1 is None and frag2 is None:
            return None
        if frag2 is None:
            return frag1 + "."
        if frag1 is None:
            return frag2 + "."

        phrase = f"{frag1}, tandis que {frag2[0].lower()}{frag2[1:]}."

        a1, a2 = abs(d1), abs(d2)
        if a1 > a2 * 1.5 and a1 > 1e-9:
            phrase += f" La variation est plus marquée pour {label1} que pour {label2}."
        elif a2 > a1 * 1.5 and a2 > 1e-9:
            phrase += f" La variation est plus marquée pour {label2} que pour {label1}."

        return phrase

    @staticmethod
    def _extract_kpi(sector, sector_ratios, financials, sector_ratios_provenance=None):
        """
        Sélectionne les 2-3 KPI du secteur. Pour un KPI sourcé depuis
        `sector_ratios` dont la provenance (si fournie) indique un proxy
        (ex: Loss Ratio recalculé via EBIT faute de primes/sinistres réels),
        la valeur est traitée comme indisponible ('N/A') plutôt qu'affichée
        sans qualification : la Synthèse Exécutive est le premier élément lu
        du rapport et ne doit jamais y présenter une approximation comme un
        chiffre réel sans un contexte suffisant pour le signaler (contrairement
        aux graphiques analytiques, où un proxy reste visible mais hachuré/annoté).
        """
        sector_ratios = sector_ratios or {}
        financials = financials or {}
        sector_ratios_provenance = sector_ratios_provenance or {}
        specs = KPI_SPECS.get(_sector_key(sector), KPI_SPECS['industry'])
        kpi = {}
        for key, source, label, unit in specs:
            if source == 'sector_ratios':
                prov = sector_ratios_provenance.get(key)
                if isinstance(prov, dict) and prov.get('type') == 'proxy':
                    value = None
                else:
                    value = sector_ratios.get(key)
            else:
                value = financials.get(key)
            kpi[key] = {'label': label, 'value': value, 'unit': unit}
        return kpi

    @staticmethod
    def generate_for_executive_summary(final_rating, risk_drivers, sector_ratios, financials, sector,
                                        sector_ratios_provenance=None, top_n=3):
        """
        Génère le contenu texte de la Synthèse Exécutive à partir de la note
        finale déjà calculée (`build_rating`), des risk drivers déjà classés
        (`identify_risk_drivers`, Phase 3) et des ratios sectoriels courants.
        Ne recalcule aucun score : ne fait que sélectionner et mettre en
        phrase des éléments déjà produits ailleurs.

        Returns:
        {
            'note': 3.32, 'category': 3, 'rating_label': 'Risque Moyen',
            'recommendation': 'APPROUVER SOUS CONDITIONS STRICTES',
            'positive_factors': ['Solvabilité Tier 1 — Note 4.20/5 (poids 4) ; ...', ...],
            'negative_factors': [...],
            'kpi': {'roa': {'label': 'ROA', 'value': 1.2, 'unit': '%'}, ...},
        }
        """
        final_rating = final_rating or {}
        risk_drivers = risk_drivers or {}
        rec = final_rating.get('recommendation') or {}

        def _factor_lines(entries):
            lines = []
            for d in (entries or [])[:top_n]:
                label = d.get('label', '')
                comment = d.get('commentaire', '')
                lines.append(f"{label} — {comment}" if comment else label)
            return lines

        return {
            'note': final_rating.get('final_score'),
            'category': final_rating.get('category'),
            'rating_label': final_rating.get('rating'),
            'recommendation': rec.get('decision'),
            'positive_factors': _factor_lines(risk_drivers.get('positifs')),
            'negative_factors': _factor_lines(risk_drivers.get('negatifs')),
            'kpi': NarrativeGenerator._extract_kpi(sector, sector_ratios, financials, sector_ratios_provenance),
        }
