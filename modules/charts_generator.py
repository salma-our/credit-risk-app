# modules/charts_generator.py
"""
Génération des graphiques analytiques (historique 1-5 exercices, par
secteur) pour le rapport PDF de notation de crédit.

Principe directeur : ce module ne fabrique jamais de donnée. Il ne trace que
des points réellement présents dans `sector_ratio_series` / `raw_series`
(produits par `ratios.py` / `data_processing.py`) ; une année sans donnée
est un TROU dans le graphique (barre absente, ligne interrompue), marqué en
plus d'un repère "N/A" discret sur les graphiques à une série (cf.
`_mark_missing_points`) — jamais une valeur interpolée ou extrapolée. Un
point marqué comme provenant d'un proxy (cf. `modules.data_provenance`) est
visuellement distingué (hachures / marqueur évidé) ET annoté en toutes
lettres sous le graphique (texte `source`, ex: "Proxy — PNB indisponible,
Revenus utilisé") plutôt que présenté comme une donnée réelle. Sans aucun
point exploitable, le graphique affiche "Données indisponibles".
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
from io import BytesIO

from modules.narrative_generator import NarrativeGenerator


def _extract_plain(entry):
    """Dévoile `(valeur, type, source)` d'une entrée `DataProvenance` (dict
    {'value','type','source',...}) ou d'une valeur brute (float/None,
    traitée comme donnée réelle / indisponible, sans texte source)."""
    if isinstance(entry, dict) and 'value' in entry and 'type' in entry:
        return entry.get('value'), entry.get('type'), entry.get('source')
    if entry is None:
        return None, 'na', None
    return entry, 'real_data', None


def _unwrap(entries, n):
    entries = entries if entries is not None else [None] * n
    values, types, sources = [], [], []
    for e in entries:
        v, t, s = _extract_plain(e)
        values.append(v)
        types.append(t)
        sources.append(s)
    return values, types, sources


def _first_proxy_source(types, sources):
    """Premier texte `source` disponible parmi les points de type 'proxy'
    (le même motif de substitution s'applique en général à tous les points
    proxy d'une série donnée, ex: 'PNB indisponible, Revenus utilisé' pour
    tous les exercices où le PNB réel manque) — utilisé pour l'annotation
    FIX 1 sous le graphique. None si la série ne contient aucun proxy."""
    if not sources:
        return None
    for t, s in zip(types, sources):
        if t == 'proxy' and s:
            return s
    return None


class AnalyticalChartsGenerator:
    """
    Génère les graphiques analytiques historiques par secteur.

    Écart volontaire par rapport au squelette d'architecture initial :
    `generate_all_charts` prend 3 séries en entrée, pas une seule, car les
    graphiques demandés mélangent des postes bruts (PNB, Crédits, Primes,
    CA — présents seulement dans `raw_series`, jamais dans les ratios
    sectoriels) et des ratios génériques dont l'équivalent sectoriel n'existe
    pas dans tous les secteurs (ROA absent des ratios `insurance`, ROE absent
    des ratios `banking` — cf. modules/sectors.py) :

      - `sector_ratio_series` : `ratios.calculate_sector_ratios_series(...,
        include_provenance=True)` — ratios sectoriels (celui qui alimente
        `financial_result`), enveloppés en `DataProvenance`.
      - `generic_ratio_series` : `ratios.calculate_ratios_series(...,
        include_provenance=True)` — les 15 ratios génériques, utilisés
        uniquement pour ROA/ROE (même formule dans les 3 secteurs) et la
        marge EBIT industrie (absente des ratios sectoriels industrie).
      - `raw_series` : `history['series']` brut (PAS de provenance : ce sont
        déjà des valeurs Excel telles quelles, ou None) — pour PNB, Crédits
        Bancaires, Primes Émises, Chiffre d'Affaires.

    Chaque graphique retourné : `{'title': str, 'chart': BytesIO (PNG),
    'narrative': str or None}`. (`'chart'` plutôt que `'figure'` de
    l'esquisse initiale : un buffer PNG s'insère directement dans le PDF via
    `reportlab.platypus.Image`, une `Figure` matplotlib brute non.)
    """

    def __init__(self, hex_colors, sector):
        self.HEX = hex_colors
        self.sector = str(sector or '').strip().lower()

    # ------------------------------------------------------------------
    # Helpers bas niveau
    # ------------------------------------------------------------------
    def _style_axes(self, ax, labelsize=7.5, grid_alpha=0.2):
        ax.grid(alpha=grid_alpha)
        ax.set_axisbelow(True)
        for spine in ('top', 'right'):
            ax.spines[spine].set_visible(False)
        ax.tick_params(labelsize=labelsize)

    def _to_buffer(self, fig):
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf

    def _no_data_chart(self, label, figsize):
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "Données indisponibles", ha='center', va='center',
                 fontsize=9.5, color=self.HEX['neutral'])
        ax.axis('off')
        ax.set_title(label, fontsize=10, fontweight='bold', color=self.HEX['primary'])
        return self._to_buffer(fig)

    def _display_years(self, years):
        """Convertit `years` en positions x numériques + libellés d'axe. Cas
        particulier : fichier ancien format à 1 seul exercice sans année
        connue (`years == [None]`) -> position 0, libellé 'Exercice unique'."""
        if years and len(years) == 1 and years[0] is None:
            return [0], ['Exercice\nunique']
        return list(years), [str(y) for y in years]

    def _benchmark_label(self, benchmark):
        """Construit le texte de traçabilité affiché sous le graphique pour
        un `benchmark` (cf. `sectors.py` -> 'benchmarks'). Si le benchmark
        porte une source réelle (`source`, depuis l'intégration des
        références marocaines BAM/AMMC/Office des Changes), l'annotation
        devient « Benchmark <source> » (réglementaire) ou « Référence
        <source> » (statistique) — remplace l'ancien texte générique
        « Benchmark interne — provisoire ». Sans `source` (anciens
        benchmarks non enrichis), retombe sur le champ statique `label`
        pour rester rétrocompatible."""
        source = benchmark.get('source')
        if source:
            prefix = 'Benchmark' if benchmark.get('source_type') == 'regulatory' else 'Référence'
            return f"{prefix} {source}"
        return benchmark.get('label', 'Référence')

    def _draw_benchmark_line(self, ax, benchmark):
        """Trace uniquement la ligne (ou bande) de référence `benchmark`
        (cf. `sectors.py` -> 'benchmarks') si fournie ; ne dessine aucun
        texte ici. Retourne le libellé à afficher via `_draw_footnotes`
        (mutualisé avec l'annotation proxy pour éviter 2 textes superposés
        sous le même graphique), ou None si `benchmark` est absent."""
        if not benchmark:
            return None
        label = self._benchmark_label(benchmark)
        if benchmark.get('value_range'):
            lo, hi = benchmark['value_range']
            ax.axhspan(lo, hi, color='orange', alpha=0.12, zorder=0)
        elif benchmark.get('value') is not None:
            ax.axhline(y=benchmark['value'], color='orange', linestyle='--', linewidth=2, zorder=4)
        else:
            return None
        return label

    def _draw_footnotes(self, ax, lines):
        """FIX 1 : empile sous le graphique les notes factuelles (source du
        proxy, libellé du benchmark) — jamais en légende in-plot, pour ne
        jamais recouvrir une barre/un point de donnée."""
        lines = [l for l in lines if l]
        if not lines:
            return
        ax.text(0.5, -0.24, "\n".join(lines), ha='center', va='top', fontsize=7,
                 style='italic', color=self.HEX['neutral'], transform=ax.transAxes,
                 linespacing=1.6)

    def _mark_missing_points(self, ax, x_years, values):
        """FIX 3 : marque explicitement chaque année sans donnée par un
        repère "N/A" discret, en plus du trou visuel (barre absente / ligne
        interrompue). Limité aux graphiques à une seule série (barres /
        courbe + benchmark) : sur les graphiques à 2 axes ou 2 séries
        groupées, déjà denses (2 couleurs, légende, parfois 2 benchmarks),
        ce marquage systématique surchargerait la lecture — l'interruption
        visuelle plus la note méthodologique générale (page dédiée)
        suffisent dans ce cas."""
        missing_x = [x for x, v in zip(x_years, values) if v is None]
        if not missing_x or len(missing_x) == len(x_years):
            return
        ymin, ymax = ax.get_ylim()
        y_pos = ymin + (ymax - ymin) * 0.03
        for x in missing_x:
            ax.text(x, y_pos, 'N/A', ha='center', va='bottom', fontsize=7,
                     color=self.HEX['neutral'], style='italic', zorder=5)

    def _cagr_text(self, x_years, values):
        pts = [(y, v) for y, v in zip(x_years, values) if v is not None]
        if len(pts) < 2:
            return None
        y0, v0 = pts[0]
        y1, v1 = pts[-1]
        n = y1 - y0
        if not n or v0 is None or v0 <= 0:
            return None
        rate = ((v1 / v0) ** (1.0 / n) - 1) * 100
        return f"TCAM {y0}-{y1} : {rate:+.1f}%"

    # ------------------------------------------------------------------
    # Primitives de tracé
    # ------------------------------------------------------------------
    def _plot_bars(self, ax, x_years, values, types, color, width=0.6, annotate=True):
        pts = [(x, v, t) for x, v, t in zip(x_years, values, types) if v is not None]
        for x, v, t in pts:
            is_proxy = (t == 'proxy')
            ax.bar(x, v, width=width, zorder=2,
                    color=color if not is_proxy else self.HEX['light_bg'],
                    edgecolor=color, linewidth=1.2,
                    hatch=None if not is_proxy else '///',
                    alpha=1.0 if not is_proxy else 0.85)
            if annotate:
                ax.annotate(f'{v:,.1f}', (x, v), textcoords='offset points',
                             xytext=(0, 5 if v >= 0 else -12), ha='center',
                             fontsize=7.5, fontweight='bold', color=color)
        return pts

    def _plot_line_with_gaps(self, ax, x_years, values, types, color, marker_size=5):
        """Trace une ligne en interrompant le tracé sur chaque trou (année
        sans donnée) plutôt que de relier deux points réels à travers une
        année manquante — une ligne continue impliquerait visuellement une
        valeur interpolée qui n'existe pas dans le dossier."""
        runs, current = [], []
        for x, v, t in zip(x_years, values, types):
            if v is None:
                if current:
                    runs.append(current)
                    current = []
                continue
            current.append((x, v, t))
        if current:
            runs.append(current)

        all_pts = []
        for run in runs:
            xs = [p[0] for p in run]
            ys = [p[1] for p in run]
            ax.plot(xs, ys, color=color, linewidth=2.0, marker='o',
                     markersize=marker_size, markerfacecolor=color,
                     markeredgecolor=color, zorder=3)
            for x, v, t in run:
                if t == 'proxy':
                    ax.plot(x, v, marker='o', markersize=marker_size + 1.5,
                             markerfacecolor='white', markeredgecolor=color,
                             markeredgewidth=1.6, zorder=4)
            all_pts.extend(run)
        return all_pts

    def _widen_narrow_range(self, ax, values, benchmark=None, min_span_ratio=0.05, min_window_ratio=0.20):
        """Élargit l'axe Y quand la variation réelle des données est minime
        par rapport à leur échelle (< `min_span_ratio` — ex : Ratio de
        Liquidité Générale 2.00x->2.16x, Asset Turnover 0.837x->0.858x) :
        l'autoscale matplotlib par défaut cadre toujours un graphique en
        courbe sur toute la hauteur disponible, ce qui exagère visuellement
        un mouvement négligeable en variation "dramatique" (cf. Correction
        3, Graphique Liquidité). Dans ce cas, la fenêtre Y est fixée à
        `min_window_ratio` de l'échelle (nettement plus large que la
        variation réelle, pour qu'elle apparaisse visuellement plate) plutôt
        qu'à peine plus large que les données elles-mêmes. Laisse
        l'autoscale standard dès que la variation dépasse `min_span_ratio`
        (ex : Solvabilité Tier1, +110 pdb sur 5 ans -> mouvement réellement
        notable, doit rester bien visible)."""
        pts = [v for v in values if v is not None]
        if len(pts) < 2:
            return
        vmin, vmax = min(pts), max(pts)
        scale = max(abs(vmax), abs(vmin), 1e-9)
        span = vmax - vmin
        if span >= scale * min_span_ratio:
            return
        center = (vmax + vmin) / 2.0
        half = scale * min_window_ratio / 2.0
        lo, hi = center - half, center + half
        if benchmark is not None:
            lo = min(lo, benchmark - half * 0.3)
            hi = max(hi, benchmark + half * 0.3)
        ax.set_ylim(lo, hi)

    # ------------------------------------------------------------------
    # Graphiques génériques réutilisés par les 3 secteurs
    # ------------------------------------------------------------------
    def _chart_bar(self, title, x_years, year_labels, values, types, unit, color,
                    cagr=False, benchmark=None, sources=None, figsize=(6.0, 3.3)):
        pts = [(x, v, t) for x, v, t in zip(x_years, values, types) if v is not None]
        if not pts:
            return self._no_data_chart(title, figsize)

        fig, ax = plt.subplots(figsize=figsize)
        self._plot_bars(ax, x_years, values, types, color)
        ax.set_xticks(x_years)
        ax.set_xticklabels(year_labels, fontsize=8)
        ax.set_ylabel(unit, fontsize=9, color=self.HEX['neutral'])
        self._style_axes(ax)

        if cagr:
            txt = self._cagr_text(x_years, values)
            if txt:
                ax.text(0.02, 0.96, txt, transform=ax.transAxes, fontsize=8,
                         fontweight='bold', color=self.HEX['primary'], va='top')

        bm_label = self._draw_benchmark_line(ax, benchmark)
        self._mark_missing_points(ax, x_years, values)
        proxy_note = _first_proxy_source(types, sources)
        self._draw_footnotes(ax, [proxy_note, bm_label])

        ax.set_title(title, fontsize=10.5, fontweight='bold', color=self.HEX['primary'])
        plt.tight_layout()
        return self._to_buffer(fig)

    def _chart_line_benchmark(self, title, x_years, year_labels, values, types, unit,
                                color, cagr=False, benchmark=None, sources=None, figsize=(6.0, 3.3)):
        if not any(v is not None for v in values):
            return self._no_data_chart(title, figsize)

        fig, ax = plt.subplots(figsize=figsize)
        self._plot_line_with_gaps(ax, x_years, values, types, color)
        ax.set_xticks(x_years)
        ax.set_xticklabels(year_labels, fontsize=8)
        ax.set_ylabel(unit, fontsize=9, color=self.HEX['neutral'])
        self._style_axes(ax)
        self._widen_narrow_range(ax, values, benchmark.get('value') if benchmark else None)

        if cagr:
            txt = self._cagr_text(x_years, values)
            if txt:
                ax.text(0.02, 0.96, txt, transform=ax.transAxes, fontsize=8,
                         fontweight='bold', color=self.HEX['primary'], va='top')

        bm_label = self._draw_benchmark_line(ax, benchmark)
        self._mark_missing_points(ax, x_years, values)
        proxy_note = _first_proxy_source(types, sources)
        self._draw_footnotes(ax, [proxy_note, bm_label])

        ax.set_title(title, fontsize=10.5, fontweight='bold', color=self.HEX['primary'])
        plt.tight_layout()
        return self._to_buffer(fig)

    def _chart_dual_axis(self, title, x_years, year_labels,
                          s1_values, s1_types, s1_label, s1_unit, s1_color, s1_kind,
                          s2_values, s2_types, s2_label, s2_unit, s2_color, s2_kind,
                          benchmark1=None, benchmark2=None,
                          s1_sources=None, s2_sources=None, figsize=(6.4, 3.5)):
        has1 = any(v is not None for v in s1_values)
        has2 = any(v is not None for v in s2_values)
        if not has1 and not has2:
            return self._no_data_chart(title, figsize)

        fig, ax1 = plt.subplots(figsize=figsize)
        ax2 = ax1.twinx()

        if s1_kind == 'bar':
            self._plot_bars(ax1, x_years, s1_values, s1_types, s1_color, width=0.32, annotate=False)
        else:
            self._plot_line_with_gaps(ax1, x_years, s1_values, s1_types, s1_color)
            self._widen_narrow_range(ax1, s1_values, benchmark1.get('value') if benchmark1 else None)

        if s2_kind == 'bar':
            self._plot_bars(ax2, x_years, s2_values, s2_types, s2_color, width=0.32, annotate=False)
        else:
            self._plot_line_with_gaps(ax2, x_years, s2_values, s2_types, s2_color)
            self._widen_narrow_range(ax2, s2_values, benchmark2.get('value') if benchmark2 else None)

        ax1.set_xticks(x_years)
        ax1.set_xticklabels(year_labels, fontsize=8)
        ax1.set_ylabel(s1_unit, fontsize=9, color=s1_color)
        ax2.set_ylabel(s2_unit, fontsize=9, color=s2_color)
        ax1.tick_params(axis='y', labelcolor=s1_color, labelsize=7.5)
        ax2.tick_params(axis='y', labelcolor=s2_color, labelsize=7.5)
        self._style_axes(ax1, grid_alpha=0.15)
        ax2.spines['top'].set_visible(False)

        bm1_label = self._draw_benchmark_line(ax1, benchmark1)
        bm2_label = self._draw_benchmark_line(ax2, benchmark2)

        # FIX 1 : notes de provenance, préfixées par le nom de la série
        # concernée (2 séries sur ce type de graphique -> ambiguïté sinon).
        footnote_lines = []
        proxy1 = _first_proxy_source(s1_types, s1_sources)
        proxy2 = _first_proxy_source(s2_types, s2_sources)
        if proxy1:
            footnote_lines.append(f"{s1_label} — {proxy1}")
        if proxy2:
            footnote_lines.append(f"{s2_label} — {proxy2}")
        if bm1_label:
            footnote_lines.append(f"{s1_label} : {bm1_label}")
        if bm2_label:
            footnote_lines.append(f"{s2_label} : {bm2_label}")
        self._draw_footnotes(ax1, footnote_lines)

        h1 = Line2D([0], [0], color=s1_color, marker='s' if s1_kind == 'bar' else 'o',
                     linestyle='' if s1_kind == 'bar' else '-', label=s1_label)
        h2 = Line2D([0], [0], color=s2_color, marker='s' if s2_kind == 'bar' else 'o',
                     linestyle='' if s2_kind == 'bar' else '-', label=s2_label)
        ax1.legend(handles=[h1, h2], fontsize=6.8, loc='upper left', frameon=True,
                    framealpha=0.85, edgecolor='none')

        ax1.set_title(title, fontsize=10.5, fontweight='bold', color=self.HEX['primary'])
        plt.tight_layout()
        return self._to_buffer(fig)

    def _chart_dual_line_same_axis(self, title, x_years, year_labels,
                                    s1_values, s1_types, s1_label, s1_color,
                                    s2_values, s2_types, s2_label, s2_color,
                                    unit, benchmark=None, s1_sources=None, s2_sources=None,
                                    figsize=(6.0, 3.3)):
        """2 séries temporelles sur le MÊME axe Y (même unité) — ex. ROA vs
        ROE. Remplace `_chart_grouped_bar` pour ce cas d'usage : une série
        temporelle se lit en tendance (courbe), pas en comparaison
        catégorielle (barres) — cf. principe directeur du module. Valeur
        annotée sur chaque point (comme demandé pour ROA/ROE) ; une année
        sans donnée pour l'une des 2 séries reste un trou dans SA courbe,
        jamais une valeur comblée."""
        if not any(v is not None for v in s1_values) and not any(v is not None for v in s2_values):
            return self._no_data_chart(title, figsize)

        fig, ax = plt.subplots(figsize=figsize)
        pts1 = self._plot_line_with_gaps(ax, x_years, s1_values, s1_types, s1_color)
        pts2 = self._plot_line_with_gaps(ax, x_years, s2_values, s2_types, s2_color)

        for x, v, t in pts1:
            ax.annotate(f'{v:,.1f}{unit}', (x, v), textcoords='offset points',
                         xytext=(0, 7), ha='center', fontsize=8, color=s1_color)
        for x, v, t in pts2:
            ax.annotate(f'{v:,.1f}{unit}', (x, v), textcoords='offset points',
                         xytext=(0, -11), ha='center', fontsize=8, color=s2_color)

        ax.set_xticks(x_years)
        ax.set_xticklabels(year_labels, fontsize=8)
        ax.set_ylabel(unit, fontsize=9, color=self.HEX['neutral'])
        self._style_axes(ax)

        bm_label = self._draw_benchmark_line(ax, benchmark)

        footnote_lines = []
        proxy1 = _first_proxy_source(s1_types, s1_sources)
        proxy2 = _first_proxy_source(s2_types, s2_sources)
        if proxy1:
            footnote_lines.append(f"{s1_label} — {proxy1}")
        if proxy2:
            footnote_lines.append(f"{s2_label} — {proxy2}")
        if bm_label:
            footnote_lines.append(bm_label)
        self._draw_footnotes(ax, footnote_lines)

        h1 = Line2D([0], [0], color=s1_color, marker='o', linestyle='-', label=s1_label)
        h2 = Line2D([0], [0], color=s2_color, marker='o', linestyle='-', label=s2_label)
        ax.legend(handles=[h1, h2], fontsize=7, loc='upper left', frameon=True,
                   framealpha=0.85, edgecolor='none')

        ax.set_title(title, fontsize=10.5, fontweight='bold', color=self.HEX['primary'])
        plt.tight_layout()
        return self._to_buffer(fig)

    # ------------------------------------------------------------------
    # Radar (Synthèse Exécutive) — petit, secondaire (cf. reports.py)
    # ------------------------------------------------------------------
    def radar_chart(self, sector_score, financial_score, governance_score, figsize=(3.5, 3.5)):
        labels = ['Secteur\n(20%)', 'Ratios Financiers\n(60%)', 'Gouvernance\n(20%)']
        values = [sector_score if sector_score is not None else 0,
                   financial_score if financial_score is not None else 0,
                   governance_score if governance_score is not None else 0]
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        values_c = values + values[:1]
        angles_c = angles + angles[:1]

        fig, ax = plt.subplots(figsize=figsize, subplot_kw=dict(polar=True))
        ax.plot(angles_c, values_c, color=self.HEX['primary'], linewidth=2, marker='o', markersize=5, zorder=3)
        ax.fill(angles_c, values_c, color=self.HEX['primary'], alpha=0.2, zorder=2)
        ax.set_xticks(angles)
        ax.set_xticklabels(labels, fontsize=7.5)
        ax.set_ylim(0, 5)
        ax.set_yticks([1, 2, 3, 4, 5])
        ax.set_yticklabels(['1', '2', '3', '4', '5'], fontsize=6, color=self.HEX['neutral'])
        for angle, val in zip(angles, values):
            ax.annotate(f'{val:.2f}', xy=(angle, val), textcoords='offset points', xytext=(0, 9),
                         ha='center', fontsize=7.5, fontweight='bold', color=self.HEX['primary'])
        ax.set_title('Répartition des 3 blocs', fontsize=9, fontweight='bold',
                      color=self.HEX['primary'], pad=16)
        plt.tight_layout()
        return self._to_buffer(fig)

    # ------------------------------------------------------------------
    # Actionnariat (Structure Actionnariale) — indépendant du secteur
    # ------------------------------------------------------------------
    # Palette catégorielle dédiée (pas self.HEX) : validée CVD-safe via
    # scripts/validate_palette.js du skill dataviz (--pairs all, ALL CHECKS
    # PASS, orange en tête pour rester dans l'esprit Wafa) -- self.HEX ne
    # passe pas ces contrôles pour un usage catégoriel (primary/neutral trop
    # sombres/désaturés, danger/success trop proches en vision daltonienne).
    # Au-delà de 3 actionnaires nommés, le surplus est replié dans "Autres"
    # (gris neutre) plutôt que d'ajouter une 4e teinte non validée.
    _SHAREHOLDER_PALETTE = ['#eb6834', '#2a78d6', '#1baf7a']
    _SHAREHOLDER_OTHER_COLOR = '#898781'

    def shareholders_pie_chart(self, shareholders, figsize=(4.2, 4.2)):
        """Pie chart de la répartition du capital (% Détention), page
        Structure Actionnariale. N'inclut que les actionnaires avec un %
        renseigné ; jamais de part inventée pour combler un total < 100%.
        Au-delà de 3 entrées nommées, les suivantes (déjà triées par %
        décroissant) sont regroupées dans une part "Autres" plutôt que
        d'ajouter une teinte supplémentaire non validée CVD-safe."""
        entries = [(str(s.get('name') or 'N/A'), s.get('pct')) for s in (shareholders or [])
                   if s.get('pct') is not None and s.get('pct') > 0]
        if not entries:
            return self._no_data_chart("Répartition du Capital", figsize)

        entries.sort(key=lambda e: e[1], reverse=True)
        labels = [name for name, _ in entries[:3]]
        values = [pct for _, pct in entries[:3]]
        colors_cycle = list(self._SHAREHOLDER_PALETTE[:len(values)])

        if len(entries) > 3:
            labels.append('Autres')
            values.append(sum(pct for _, pct in entries[3:]))
            colors_cycle.append(self._SHAREHOLDER_OTHER_COLOR)

        fig, ax = plt.subplots(figsize=figsize)
        ax.pie(
            values, colors=colors_cycle, autopct='%1.1f%%', pctdistance=0.75,
            startangle=90, counterclock=False,
            wedgeprops=dict(edgecolor='white', linewidth=1.5),
            textprops=dict(fontsize=9, fontweight='bold', color='white'))
        ax.legend(labels, loc='center left', bbox_to_anchor=(1.0, 0.5),
                   fontsize=8.5, frameon=False)
        ax.set_title("Répartition du Capital", fontsize=10.5, fontweight='bold',
                      color=self.HEX['primary'])
        ax.axis('equal')
        plt.tight_layout()
        return self._to_buffer(fig)

    # ------------------------------------------------------------------
    # Point d'entrée
    # ------------------------------------------------------------------
    def generate_all_charts(self, sector_ratio_series, generic_ratio_series, raw_series,
                             years, sector_benchmarks=None):
        """
        Retourne la liste complète des graphiques analytiques pour le
        secteur : [{'title', 'chart' (buffer PNG), 'narrative'}, ...].
        """
        sector_benchmarks = sector_benchmarks or {}
        x_years, year_labels = self._display_years(years)

        if 'bank' in self.sector or 'banq' in self.sector:
            return self._banking_charts(sector_ratio_series, generic_ratio_series, raw_series,
                                          years, x_years, year_labels, sector_benchmarks)
        if 'insur' in self.sector or 'assur' in self.sector:
            return self._insurance_charts(sector_ratio_series, generic_ratio_series, raw_series,
                                            years, x_years, year_labels, sector_benchmarks)
        return self._industry_charts(sector_ratio_series, generic_ratio_series, raw_series,
                                       years, x_years, year_labels, sector_benchmarks)

    # ------------------------------------------------------------------
    # BANQUE — 7 graphiques (Revenus -> Marges -> Profitabilité -> Solvabilité -> Liquidité)
    # ------------------------------------------------------------------
    def _banking_charts(self, sr, gr, raw, years, x_years, year_labels, bm):
        n = len(years)
        charts = []

        # 1. PNB (ou fallback Revenus, proxy annoté) — 4/5 ans. Fallback
        # décidé ici (pas dans ratios.py: 'pnb'/'revenus' sont des postes
        # bruts de `raw_series`, pas des ratios) -> source FIX 1 construite
        # avec le même format que `DataProvenance.mark_proxy`.
        pnb_v, pnb_t, pnb_s = [], [], []
        pnb_raw = raw.get('pnb') or [None] * n
        rev_raw = raw.get('revenus') or [None] * n
        for p, r in zip(pnb_raw, rev_raw):
            if p is not None:
                pnb_v.append(p); pnb_t.append('real_data'); pnb_s.append(None)
            elif r is not None:
                pnb_v.append(r); pnb_t.append('proxy')
                pnb_s.append("Proxy — PNB indisponible, Revenus utilisé")
            else:
                pnb_v.append(None); pnb_t.append('na'); pnb_s.append(None)
        title = "Produit Net Bancaire (PNB)"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, pnb_v, pnb_t, 'MDH',
                                       self.HEX['primary'], cagr=True, sources=pnb_s),
            'narrative': NarrativeGenerator.interpret_trend('Le PNB', pnb_v, years, unit=' MDH'),
        })

        # 2. Coût du Risque vs Taux de Souffrance (2 axes, données réelles uniquement)
        cr_v, cr_t, cr_s = _unwrap(sr.get('cout_risque'), n)
        ts_v, ts_t, ts_s = _unwrap(sr.get('taux_souffrance'), n)
        ts_bm = bm.get('taux_souffrance')
        title = "Coût du Risque vs Taux de Souffrance"
        charts.append({
            'title': title,
            'chart': self._chart_dual_axis(
                title, x_years, year_labels,
                ts_v, ts_t, 'Taux de Souffrance', '%', self.HEX['warning'], 'line',
                cr_v, cr_t, 'Coût du Risque', '%', self.HEX['danger'], 'line',
                benchmark1=ts_bm, s1_sources=ts_s, s2_sources=cr_s),
            'narrative': NarrativeGenerator.interpret_trend('Le taux de souffrance', ts_v, years,
                                                              benchmark=ts_bm, unit='%'),
        })

        # 3. Marge d'Intermédiation vs COEX (2 axes)
        mi_v, mi_t, mi_s = _unwrap(sr.get('margin_intermediation'), n)
        coex_v, coex_t, coex_s = _unwrap(sr.get('coex'), n)
        title = "Marge d'Intermédiation vs Coefficient d'Exploitation"
        charts.append({
            'title': title,
            'chart': self._chart_dual_axis(
                title, x_years, year_labels,
                mi_v, mi_t, "Marge d'Intermédiation", '%', self.HEX['secondary'], 'line',
                coex_v, coex_t, 'COEX', '%', self.HEX['accent'], 'line',
                s1_sources=mi_s, s2_sources=coex_s),
            'narrative': NarrativeGenerator.interpret_trend("La marge d'intermédiation", mi_v, years, unit='%'),
        })

        # 4. Solvabilité Tier 1 vs Benchmark
        t1_v, t1_t, t1_s = _unwrap(sr.get('ratio_solvabilite_t1'), n)
        t1_bm = bm.get('ratio_solvabilite_t1')
        title = "Solvabilité Tier 1 vs Benchmark"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, t1_v, t1_t, '%',
                                                  self.HEX['secondary'], benchmark=t1_bm, sources=t1_s),
            'narrative': NarrativeGenerator.interpret_trend('Le ratio de solvabilité Tier 1', t1_v, years,
                                                              benchmark=t1_bm, unit='%'),
        })

        # 5. ROA vs ROE (ratios génériques : ROE absent des ratios sectoriels banque)
        roa_v, roa_t, roa_s = _unwrap(gr.get('roa'), n)
        roe_v, roe_t, roe_s = _unwrap(gr.get('roe'), n)
        roa_pct = [v * 100 if v is not None else None for v in roa_v]
        roe_pct = [v * 100 if v is not None else None for v in roe_v]
        title = "ROA vs ROE"
        charts.append({
            'title': title,
            'chart': self._chart_dual_line_same_axis(title, x_years, year_labels,
                                               roa_pct, roa_t, 'ROA', self.HEX['success'],
                                               roe_pct, roe_t, 'ROE', self.HEX['primary'], '%',
                                               s1_sources=roa_s, s2_sources=roe_s),
            'narrative': NarrativeGenerator.interpret_dual_trend('Le ROA', roa_pct, 'Le ROE', roe_pct, years, unit='%'),
        })

        # 6. Ratio de Liquidité Bancaire (seuil 1.0)
        liq_v, liq_t, liq_s = _unwrap(sr.get('ratio_liquidite'), n)
        title = "Ratio de Liquidité Bancaire"
        charts.append({
            'title': title,
            'chart': self._chart_bar(title, x_years, year_labels, liq_v, liq_t, 'x',
                                       self.HEX['secondary'], benchmark=bm.get('ratio_liquidite'), sources=liq_s),
            'narrative': NarrativeGenerator.interpret_trend('Le ratio de liquidité bancaire', liq_v, years,
                                                              benchmark=bm.get('ratio_liquidite'), unit='x'),
        })

        # 7. Crédits Bancaires vs Taux de Souffrance (2 axes)
        credits_v, credits_t, credits_s = _unwrap(raw.get('credits_bancaires'), n)
        title = "Crédits Bancaires vs Taux de Souffrance"
        charts.append({
            'title': title,
            'chart': self._chart_dual_axis(
                title, x_years, year_labels,
                credits_v, credits_t, 'Crédits Bancaires', 'MDH', self.HEX['primary'], 'bar',
                ts_v, ts_t, 'Taux de Souffrance', '%', self.HEX['warning'], 'line',
                s1_sources=credits_s, s2_sources=ts_s),
            'narrative': NarrativeGenerator.interpret_trend('Le portefeuille de crédits', credits_v, years, unit=' MDH'),
        })

        return charts

    # ------------------------------------------------------------------
    # INDUSTRIE — 7 graphiques (Croissance -> Marges -> Rentabilité -> Endettement -> Couverture -> Liquidité/Efficacité)
    # ------------------------------------------------------------------
    def _industry_charts(self, sr, gr, raw, years, x_years, year_labels, bm):
        n = len(years)
        charts = []

        # 1. Chiffre d'Affaires (CA) avec TCAM
        ca_v, ca_t, ca_s = _unwrap(raw.get('revenus'), n)
        title = "Chiffre d'Affaires"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, ca_v, ca_t, 'MDH',
                                       self.HEX['primary'], cagr=True, sources=ca_s),
            'narrative': NarrativeGenerator.interpret_trend('Le chiffre d\'affaires', ca_v, years, unit=' MDH'),
        })

        # 2. Marge EBIT (ratio générique : absent des ratios sectoriels industrie)
        ebit_margin_v, ebit_margin_t, ebit_margin_s = _unwrap(gr.get('operating_margin'), n)
        ebit_margin_pct = [v * 100 if v is not None else None for v in ebit_margin_v]
        title = "Marge EBIT"
        ebit_bm = bm.get('ebit_margin')
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, ebit_margin_pct, ebit_margin_t, '%',
                                       self.HEX['secondary'], benchmark=ebit_bm, sources=ebit_margin_s),
            'narrative': NarrativeGenerator.interpret_trend("La marge EBIT", ebit_margin_pct, years,
                                                              benchmark=ebit_bm, unit='%'),
        })

        # 3. Marge Nette
        npm_v, npm_t, npm_s = _unwrap(sr.get('net_profit_margin'), n)
        title = "Marge Nette"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, npm_v, npm_t, '%', self.HEX['success'],
                                       sources=npm_s),
            'narrative': NarrativeGenerator.interpret_trend('La marge nette', npm_v, years, unit='%'),
        })

        # 4. ROA vs ROE (ratios génériques, cohérent avec les 2 autres secteurs)
        roa_v, roa_t, roa_s = _unwrap(gr.get('roa'), n)
        roe_v, roe_t, roe_s = _unwrap(gr.get('roe'), n)
        roa_pct = [v * 100 if v is not None else None for v in roa_v]
        roe_pct = [v * 100 if v is not None else None for v in roe_v]
        title = "ROA vs ROE"
        charts.append({
            'title': title,
            'chart': self._chart_dual_line_same_axis(title, x_years, year_labels,
                                               roa_pct, roa_t, 'ROA', self.HEX['success'],
                                               roe_pct, roe_t, 'ROE', self.HEX['primary'], '%',
                                               s1_sources=roa_s, s2_sources=roe_s),
            'narrative': NarrativeGenerator.interpret_dual_trend('Le ROA', roa_pct, 'Le ROE', roe_pct, years, unit='%'),
        })

        # 5. Debt-to-Equity vs Benchmark
        de_v, de_t, de_s = _unwrap(sr.get('debt_to_equity'), n)
        de_bm = bm.get('debt_to_equity')
        title = "Debt-to-Equity vs Benchmark"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, de_v, de_t, 'x',
                                                  self.HEX['danger'], benchmark=de_bm, sources=de_s),
            'narrative': NarrativeGenerator.interpret_trend("L'endettement (Dettes / Capitaux Propres)", de_v, years,
                                                              benchmark=de_bm, unit='x'),
        })

        # 6. Interest Coverage Ratio (seuil d'alerte 2.0)
        ic_v, ic_t, ic_s = _unwrap(sr.get('interest_coverage'), n)
        title = "Interest Coverage Ratio"
        charts.append({
            'title': title,
            'chart': self._chart_bar(title, x_years, year_labels, ic_v, ic_t, 'x', self.HEX['secondary'],
                                       benchmark=bm.get('interest_coverage'), sources=ic_s),
            'narrative': NarrativeGenerator.interpret_trend('La couverture des intérêts', ic_v, years,
                                                              benchmark=bm.get('interest_coverage'), unit='x'),
        })

        # 7. Ratio de Liquidité vs Asset Turnover (2 axes)
        cur_v, cur_t, cur_s = _unwrap(sr.get('current_ratio'), n)
        at_v, at_t, at_s = _unwrap(sr.get('asset_turnover'), n)
        title = "Ratio de Liquidité vs Asset Turnover"
        charts.append({
            'title': title,
            'chart': self._chart_dual_axis(
                title, x_years, year_labels,
                cur_v, cur_t, 'Ratio de Liquidité', 'x', self.HEX['secondary'], 'line',
                at_v, at_t, 'Asset Turnover', 'x', self.HEX['accent'], 'line',
                s1_sources=cur_s, s2_sources=at_s),
            'narrative': NarrativeGenerator.interpret_trend('Le ratio de liquidité générale', cur_v, years, unit='x'),
        })

        return charts

    # ------------------------------------------------------------------
    # ASSURANCE — 5 graphiques (Activité -> Sinistralité -> Rentabilité -> Solvabilité -> Résultat technique)
    # ------------------------------------------------------------------
    def _insurance_charts(self, sr, gr, raw, years, x_years, year_labels, bm):
        n = len(years)
        charts = []

        # 1. Primes Émises (Gross Written Premiums) avec TCAM
        primes_v, primes_t, primes_s = _unwrap(raw.get('primes_emises'), n)
        title = "Primes Émises"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, primes_v, primes_t, 'MDH',
                                       self.HEX['primary'], cagr=True, sources=primes_s),
            'narrative': NarrativeGenerator.interpret_trend('Les primes émises', primes_v, years, unit=' MDH'),
        })

        # 2. Loss Ratio (Sinistres / Primes) — données réelles uniquement : un
        # 'combined_ratio' de type proxy (calculé via EBIT faute de
        # primes/sinistres) est traité comme absent sur CE graphique
        # spécifique, conformément à la donnée demandée ("si primes_emises
        # et sinistres dispo") ; il reste visible avec son proxy sur le
        # graphique Résultat Technique (#5) ci-dessous. Pas de `sources` ici
        # par cohérence : ce graphique ne montre jamais de proxy, donc pas
        # d'annotation "Proxy" à afficher.
        loss_raw_v, loss_raw_t, _loss_raw_s = _unwrap(sr.get('combined_ratio'), n)
        loss_v = [v if t != 'proxy' else None for v, t in zip(loss_raw_v, loss_raw_t)]
        loss_t = [t if t != 'proxy' else 'na' for t in loss_raw_t]
        title = "Loss Ratio (Sinistres / Primes)"
        loss_bm = bm.get('combined_ratio')
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, loss_v, loss_t, '%',
                                       self.HEX['danger'], benchmark=loss_bm),
            'narrative': NarrativeGenerator.interpret_trend('Le loss ratio', loss_v, years,
                                                              benchmark=loss_bm, unit='%'),
        })

        # 3. ROA vs ROE (ratios génériques : ROA absent des ratios sectoriels assurance)
        roa_v, roa_t, roa_s = _unwrap(gr.get('roa'), n)
        roe_v, roe_t, roe_s = _unwrap(gr.get('roe'), n)
        roa_pct = [v * 100 if v is not None else None for v in roa_v]
        roe_pct = [v * 100 if v is not None else None for v in roe_v]
        title = "ROA vs ROE"
        charts.append({
            'title': title,
            'chart': self._chart_dual_line_same_axis(title, x_years, year_labels,
                                               roa_pct, roa_t, 'ROA', self.HEX['success'],
                                               roe_pct, roe_t, 'ROE', self.HEX['primary'], '%',
                                               s1_sources=roa_s, s2_sources=roe_s),
            'narrative': NarrativeGenerator.interpret_dual_trend('Le ROA', roa_pct, 'Le ROE', roe_pct, years, unit='%'),
        })

        # 4. Solvency Margin vs seuil réglementaire
        sm_v, sm_t, sm_s = _unwrap(sr.get('solvency_margin'), n)
        sm_bm = bm.get('solvency_margin')
        title = "Solvency Margin vs Seuil Réglementaire"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, sm_v, sm_t, '%',
                                                  self.HEX['secondary'], benchmark=sm_bm, sources=sm_s),
            'narrative': NarrativeGenerator.interpret_trend('La marge de solvabilité', sm_v, years,
                                                              benchmark=sm_bm, unit='%'),
        })

        # 5. Résultat Technique (%, réel si primes-sinistres dispo, sinon
        # proxy via EBIT/Revenus — annoté par hachures + source, cf. Fix 1)
        tr_v, tr_t, tr_s = _unwrap(sr.get('technical_result'), n)
        title = "Résultat Technique"
        charts.append({
            'title': title,
            'chart': self._chart_line_benchmark(title, x_years, year_labels, tr_v, tr_t, '%', self.HEX['success'],
                                       sources=tr_s),
            'narrative': NarrativeGenerator.interpret_trend('Le résultat technique', tr_v, years, unit='%'),
        })

        return charts
