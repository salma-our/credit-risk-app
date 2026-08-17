# modules/reports.py - VERSION 7 (NOTATION SECTORIELLE /5, style ATW)
"""
Génération du rapport PDF de notation de crédit sectorielle, avec ReportLab +
matplotlib. Structure inspirée des grilles de notation bancaires (type
Attijariwafa Bank) : couverture, contexte sectoriel, ratios financiers,
tendances, tableau de notation pondérée détaillé, recommandation — 6
sections logiques ; le nombre de pages *physiques* réel (parfois 7 si une
section déborde) est calculé dynamiquement, voir CreditReportGeneratorV7.generate.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                 Spacer, PageBreak, Image as RLImage)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.utils import ImageReader
from datetime import datetime
from io import BytesIO
from werkzeug.utils import secure_filename
import os

from modules.charts_generator import AnalyticalChartsGenerator
from modules.narrative_generator import NarrativeGenerator
from modules.sectors import SectorConfig

# Nombre de pages "logique" (6 sections). Sert uniquement de valeur de secours
# si, pour une raison quelconque, le passage de comptage dynamique échoue :
# le vrai total affiché en pied de page est désormais calculé à chaque
# génération (cf. CreditReportGeneratorV7.generate), car le contenu peut
# déborder au-delà de 6 pages physiques (ex: tableaux longs sur un dossier
# Banque) et un total figé désynchronise le "Page X/N" affiché.
FALLBACK_TOTAL_PAGES = 6
LOGO_PATH = os.path.join('static', 'logo.png')


class CreditReportGeneratorV7:
    """Générateur de rapport PDF de notation de crédit sectorielle (6 pages, /5)."""

    def __init__(self, results, output_path):
        self.results = results or {}
        self.output_path = output_path

        # Thème Wafa Gestion (orange/rouge) — mêmes clés/attributs qu'avant
        # (self.PRIMARY, self.SECONDARY, ...) pour ne rien casser dans le
        # reste du fichier, mais rôles redéfinis : 'primary' porte désormais
        # le texte foncé (titres H1/H2 — jamais l'orange, réservé aux accents
        # : numéros de section, bordures, séparateurs, valeurs mises en
        # avant), 'accent' est l'orange de marque, 'danger'/'secondary'
        # couvrent le rouge. Palette identique à static/css/variables.css
        # (Phase 5A) pour une cohérence visuelle web <-> PDF.
        self.HEX = {
            'primary': '#2c3e50',      # texte foncé (titres, tableaux)
            'secondary': '#e67e22',    # orange foncé (accent secondaire)
            'accent': '#f39c12',       # orange Wafa (accent principal)
            'success': '#27ae60',
            'warning': '#f39c12',
            'danger': '#e74c3c',       # rouge Wafa
            'neutral': '#7f8c8d',
            'light_bg': '#ecf0f1',
            'gray_lighter': '#f5f7fa',
        }
        self.PRIMARY = colors.HexColor(self.HEX['primary'])
        self.SECONDARY = colors.HexColor(self.HEX['secondary'])
        self.ACCENT = colors.HexColor(self.HEX['accent'])
        self.SUCCESS = colors.HexColor(self.HEX['success'])
        self.WARNING = colors.HexColor(self.HEX['warning'])
        self.DANGER = colors.HexColor(self.HEX['danger'])
        self.NEUTRAL = colors.HexColor(self.HEX['neutral'])
        self.LIGHT_BG = colors.HexColor(self.HEX['light_bg'])
        self.LIGHT_BG2 = colors.HexColor(self.HEX['gray_lighter'])

        self.charts = AnalyticalChartsGenerator(self.HEX, self.results.get('sector', 'industry'))

        # Numéros de section (badge orange affiché par _page_title) : extrait
        # en dict plutôt que des littéraux figés dans chaque _add_*_page pour
        # que EnrichedBankingReportGenerator (page "Données Enrichies" au lieu
        # d'"Actionnariat" + "Analyse Graphique") puisse renuméroter sans
        # dupliquer les méthodes Méthodologie/Notation/Recommandation,
        # héritées telles quelles.
        self._section_numbers = {
            'exec': 1, 'shareholders': 2, 'charts': 3,
            'methodology': 4, 'rating': 5, 'recommendation': 6,
        }

        self._doc_kwargs = dict(
            pagesize=A4, topMargin=1.0 * inch, bottomMargin=0.6 * inch,
            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        )
        self.doc = None
        self.elements = []
        self.styles = getSampleStyleSheet()
        self._setup_styles()
        self._total_pages = FALLBACK_TOTAL_PAGES

    # ------------------------------------------------------------------
    # Helpers sûrs (gestion des None / valeurs manquantes)
    # ------------------------------------------------------------------
    def _safe_format(self, value, decimals=2, suffix=''):
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            return "N/A"

    def _safe_money_m(self, value):
        """Formate un montant déjà exprimé en MDH (Millions de Dirhams) - pas
        de division supplémentaire, cf. en-tête de modules/data_processing.py."""
        if value is None:
            return "N/A"
        try:
            return f"{float(value):,.1f} MDH"
        except (TypeError, ValueError):
            return "N/A"

    def _rec_hex(self, key):
        return {
            'success': self.HEX['success'],
            'warning': self.HEX['warning'],
            'danger': self.HEX['danger'],
            'dark': self.HEX['danger'],
        }.get(key, self.HEX['neutral'])

    def _note_hex(self, note):
        if note is None:
            return self.HEX['neutral']
        if note >= 3.5:
            return self.HEX['success']
        if note >= 2.5:
            return self.HEX['warning']
        return self.HEX['danger']

    def _note_pct(self, note):
        """Convertit une note /5 en pourcentage (0-100) pour les barres de progression."""
        if note is None:
            return 0
        return max(0, min(100, (note / 5.0) * 100))

    # Libellés/qualificatifs neutres par catégorie — remplacent toute
    # formulation de décision d'octroi ("APPROUVER...") sur les pages
    # Synthèse Exécutive et Recommandation & Conclusion : la plateforme
    # évalue le risque, le comité de crédit décide (cf. commande "FINAL
    # Correction Pages 2 & 10").
    _SECTOR_LABELS = {'banking': 'banque', 'insurance': "compagnie d'assurance",
                       'industry': 'entreprise industrielle'}
    _CATEGORY_QUALIFIER = {
        1: "un profil de risque faible",
        2: "un profil de risque contenu",
        3: "un profil de risque modéré nécessitant une vigilance particulière",
        4: "un profil de risque élevé",
    }
    _CATEGORY_NEUTRAL_NOTE = {
        1: "Profil compatible avec un financement standard.",
        2: "Profil globalement favorable, avec quelques points à examiner.",
        3: "Profil nécessitant un examen approfondi avant toute décision.",
        4: "Profil présentant des signaux de risque élevés nécessitant une analyse renforcée.",
    }

    def _sector_label(self, sector):
        s = str(sector or '').strip().lower()
        if 'bank' in s or 'banq' in s:
            return self._SECTOR_LABELS['banking']
        if 'insur' in s or 'assur' in s:
            return self._SECTOR_LABELS['insurance']
        return self._SECTOR_LABELS['industry']

    def _generate_profile_summary(self, sector, category, risk_drivers):
        """1-2 phrases factuelles de profil (Page 2, Zone 1) : qualificatif
        de risque tiré de la catégorie déjà calculée par `RatingEngine`, puis
        les libellés réels des principaux facteurs positifs/négatifs déjà
        classés par `identify_risk_drivers` — jamais de texte inventé
        indépendamment des données de CE dossier (cf. principe directeur de
        `narrative_generator.py`, appliqué ici à l'identique)."""
        qualifier = self._CATEGORY_QUALIFIER.get(category, self._CATEGORY_QUALIFIER[4])
        sentence = (f"Cette {self._sector_label(sector)} présente {qualifier} au regard de la "
                    f"grille de notation sectorielle appliquée.")
        positives = (risk_drivers or {}).get('positifs') or []
        negatives = (risk_drivers or {}).get('negatifs') or []
        if positives:
            top_pos = ', '.join(d.get('label', '') for d in positives[:2])
            sentence += f" Principaux points forts : {top_pos}."
        if negatives:
            sentence += f" Point de vigilance principal : {negatives[0].get('label', '')}."
        return sentence

    def _short_factor_descriptor(self, d):
        """Descripteur court (1 ligne) pour un facteur Secteur/Ratios
        Financiers/Gouvernance affiché en Zone 2 de la Synthèse Exécutive —
        dérivé du `commentaire` déjà calculé par `identify_risk_drivers`
        (tendance amélioration/dégradation si présente, sinon origine de la
        note ou simple positionnement /5), jamais une appréciation inventée."""
        commentaire = d.get('commentaire') or ''
        if 'amélioration' in commentaire:
            return "Tendance : amélioration sur l'historique disponible."
        if 'dégradation' in commentaire:
            return "Tendance : dégradation sur l'historique disponible."
        if d.get('is_override') is False:
            return "Valeur de référence par défaut du secteur (non personnalisée)."
        note = d.get('note')
        if note is None:
            return ''
        if note >= 4:
            return 'Position favorable.'
        if note <= 2:
            return 'Position à renforcer.'
        return 'Position modérée.'

    def _factor_entry_flowables(self, d):
        label_style = ParagraphStyle(name='FactorLabel', fontSize=9.5, leading=12.5,
                                      fontName='Helvetica-Bold', textColor=self.PRIMARY)
        desc_style = ParagraphStyle(name='FactorDesc', fontSize=8.5, leading=11,
                                     fontName='Helvetica-Oblique', textColor=self.NEUTRAL)
        note = d.get('note')
        note_txt = f"{note:.2f}/5" if note is not None else "N/A"
        title = Paragraph(f"{d.get('label', '')} — {note_txt}", label_style)
        desc = Paragraph(self._short_factor_descriptor(d), desc_style)
        return [title, desc, Spacer(1, 0.08 * inch)]

    def _add_factors_columns(self, risk_drivers):
        """Zone 2 Synthèse Exécutive : 2 colonnes (Facteurs Favorables /
        Points de Vigilance), top 3 de chaque liste déjà classée par
        `identify_risk_drivers` (aucun recalcul, aucune sélection propre à
        l'affichage)."""
        positives = (risk_drivers or {}).get('positifs') or []
        negatives = (risk_drivers or {}).get('negatifs') or []

        head_style = lambda hex_color: ParagraphStyle(
            name=f'FactorsHead_{hex_color}', fontSize=10.5, leading=13,
            fontName='Helvetica-Bold', textColor=colors.HexColor(hex_color))

        left = [Paragraph("FACTEURS FAVORABLES", head_style(self.HEX['success'])), Spacer(1, 0.06 * inch)]
        if positives:
            for d in positives[:3]:
                left.extend(self._factor_entry_flowables(d))
        else:
            left.append(Paragraph("<i>Aucun facteur positif identifiable.</i>", self.styles['Small']))

        right = [Paragraph("POINTS DE VIGILANCE", head_style(self.HEX['danger'])), Spacer(1, 0.06 * inch)]
        if negatives:
            for d in negatives[:3]:
                right.extend(self._factor_entry_flowables(d))
        else:
            right.append(Paragraph("<i>Aucun facteur négatif identifiable.</i>", self.styles['Small']))

        table = Table([[left, right]], colWidths=[3.5 * inch, 3.5 * inch])
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEAFTER', (0, 0), (0, -1), 0.75, colors.HexColor('#D9D9D9')),
            ('LEFTPADDING', (1, 0), (1, 0), 14), ('RIGHTPADDING', (0, 0), (0, 0), 14),
            ('LEFTPADDING', (0, 0), (0, 0), 0), ('RIGHTPADDING', (1, 0), (1, 0), 0),
        ]))
        self.elements.append(table)

    def _kpi_trend(self, key, unit, years):
        """Tendance factuelle (Hausse/Baisse/Stable + amplitude) d'un KPI
        entre le 1er et le dernier exercice réellement disponibles — cherche
        d'abord dans les ratios sectoriels (`sector_ratio_series`), sinon
        dans les postes bruts (`financial_series`, ex: Primes Émises).
        Jamais de valeur interpolée : un seul exercice exploitable -> None
        (pas de tendance affichée)."""
        r = self.results
        series = (r.get('sector_ratio_series') or {}).get(key)
        if series is None:
            series = (r.get('financial_series') or {}).get(key)
        if not series or not years:
            return None
        pairs = [(y, v) for y, v in zip(years, series) if v is not None]
        if len(pairs) < 2:
            return None
        first_v, last_v = pairs[0][1], pairs[-1][1]
        delta = last_v - first_v
        if abs(delta) < 1e-9:
            return "Stable"
        sign_word = 'Hausse' if delta > 0 else 'Baisse'
        if unit == 'MDH':
            return f"{sign_word} {delta:+,.1f} MDH"
        return f"{sign_word} {delta:+.2f}{unit}"

    def _kpi_card_trend(self, value_text, label, trend_text, width=2.3 * inch):
        val = Paragraph(f"<b>{value_text}</b>", ParagraphStyle(
            name='KpiValue', alignment=TA_CENTER, fontSize=19, leading=23,
            fontName='Helvetica-Bold', textColor=self.ACCENT))
        lab = Paragraph(label, ParagraphStyle(
            name='KpiLabel', alignment=TA_CENTER, fontSize=9.5, leading=12,
            fontName='Helvetica-Bold', textColor=self.PRIMARY))
        trend = Paragraph(trend_text or '', ParagraphStyle(
            name='KpiTrend', alignment=TA_CENTER, fontSize=8.5, leading=11, textColor=self.NEUTRAL))
        card = Table([[val], [lab], [trend]], colWidths=[width])
        card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), self.LIGHT_BG),
            ('BOX', (0, 0), (-1, -1), 1.2, self.ACCENT),
            ('TOPPADDING', (0, 0), (0, 0), 12), ('BOTTOMPADDING', (0, 0), (0, 0), 2),
            ('BOTTOMPADDING', (0, 2), (0, 2), 10),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        return card

    def _add_kpi_cards(self, kpi, years):
        """Zone 3 Synthèse Exécutive : 1 carte par KPI secteur-spécifique
        (cf. `NarrativeGenerator.KPI_SPECS`), valeur courante + tendance
        1er -> dernier exercice disponible."""
        self.elements.append(Paragraph("KPI Clés", self.styles['SubHeading']))
        if not kpi:
            return
        cell_width = (7.0 / len(kpi)) * inch
        cards = []
        for key, info in kpi.items():
            val = info.get('value')
            unit = info.get('unit', '')
            label = info.get('label', '')
            if val is None:
                value_text, trend_text = "N/A", "(indisponible)"
            else:
                unit_disp = f' {unit}' if unit == 'MDH' else unit
                value_text = f"{val:,.1f}{unit_disp}"
                trend_text = self._kpi_trend(key, unit, years)
            cards.append(self._kpi_card_trend(value_text, label, trend_text, width=cell_width))
        row = Table([cards], colWidths=[cell_width] * len(cards))
        row.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        self.elements.append(row)

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------
    def _setup_styles(self):
        self.styles.add(ParagraphStyle(
            name='CoverTitle', fontSize=22, leading=26, fontName='Helvetica-Bold',
            textColor=self.PRIMARY, alignment=TA_CENTER, spaceAfter=6,
        ))
        self.styles.add(ParagraphStyle(
            name='CoverCompany', fontSize=14, fontName='Helvetica',
            textColor=self.NEUTRAL, alignment=TA_CENTER, leading=18,
        ))
        self.styles.add(ParagraphStyle(
            name='PageTitle', fontSize=18, leading=22, fontName='Helvetica-Bold',
            textColor=self.PRIMARY, spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            name='SubHeading', fontSize=13, leading=16, fontName='Helvetica-Bold',
            textColor=self.PRIMARY, spaceBefore=6, spaceAfter=6,
        ))
        self.styles.add(ParagraphStyle(
            name='Body', fontSize=10, fontName='Helvetica',
            leading=14, alignment=TA_JUSTIFY, textColor=self.PRIMARY,
        ))
        self.styles.add(ParagraphStyle(
            name='Small', fontSize=9, fontName='Helvetica',
            leading=12, textColor=self.NEUTRAL,
        ))

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------
    def _build_pages(self, target):
        """(Re)construit la liste d'éléments et le ``SimpleDocTemplate`` pointant
        vers `target` (chemin fichier ou buffer mémoire). Appelée deux fois par
        `generate()` : une première fois "à blanc" pour compter le nombre réel
        de pages, une seconde fois pour produire le PDF final avec ce total
        injecté dans le pied de page."""
        self.elements = []
        self.doc = SimpleDocTemplate(target, **self._doc_kwargs)
        self._add_cover_page()                  # Page 1
        self.elements.append(PageBreak())
        self._add_executive_summary_page()       # Page 2
        self.elements.append(PageBreak())
        self._add_shareholders_page()             # Page 3 : Structure Actionnariale
        self.elements.append(PageBreak())
        self._add_analytical_charts_pages()         # Pages 4+ (sauts de page internes)
        self.elements.append(PageBreak())
        self._add_methodology_page()                  # Page suivante : Notes Méthodologiques
        self.elements.append(PageBreak())
        self._add_rating_table_page()              # Page suivante : Tableau de Notation
        self.elements.append(PageBreak())
        self._add_recommendation_page()             # Dernière page : Recommandation & Conclusion

    def _count_pages_decoration(self, canvas, doc):
        """Callback utilisé uniquement lors du passage de comptage : ne dessine
        rien, se contente de retenir le numéro de la page en cours. À la fin du
        build, cette valeur correspond au nombre total de pages physiques."""
        self._page_count_probe = canvas.getPageNumber()

    def generate(self):
        try:
            # 1) Passage de comptage : le contenu peut déborder au-delà des 6
            #    sections "logiques" (ex: un tableau de ratios plus long fait
            #    passer le rapport Banque à 7 pages physiques) ; on construit
            #    donc une première fois dans un buffer mémoire jetable pour
            #    déterminer le vrai nombre de pages, sans écrire de fichier.
            self._page_count_probe = FALLBACK_TOTAL_PAGES
            self._build_pages(BytesIO())
            self.doc.build(
                self.elements,
                onFirstPage=self._count_pages_decoration,
                onLaterPages=self._count_pages_decoration,
            )
            self._total_pages = self._page_count_probe or FALLBACK_TOTAL_PAGES

            # 2) Passage final : même contenu, régénéré à l'identique, cette
            #    fois écrit sur le fichier de sortie avec le vrai total en
            #    pied de page ("Page X/N" toujours synchronisé).
            self._build_pages(self.output_path)
            self.doc.build(
                self.elements,
                onFirstPage=self._page_decorations,
                onLaterPages=self._page_decorations,
            )
            print(f"[OK] Rapport PDF V7 genere avec succes: {os.path.basename(self.output_path)} "
                  f"({self._total_pages} pages)")
            return self.output_path

        except Exception as e:
            print(f"[ERREUR] Erreur generation rapport V7: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    # ------------------------------------------------------------------
    # Header / Footer (logo + numérotation + confidentialité)
    # ------------------------------------------------------------------
    # Palette chevrons (arrière-plan géométrique) : taupe / gris / beige,
    # distincte de la palette orange/rouge Wafa (self.HEX) — décoration
    # neutre, pas un accent de marque.
    _CHEVRON_COLORS = ['#b8a89e', '#a8a8a8', '#f5e6d3']

    def _draw_chevron(self, canvas, x, y, color_hex, opacity, size):
        """Chevron décoratif (triangle pointant vers la gauche). Dessiné en
        premier (sous le contenu) à chaque page via `_page_decorations` :
        Platypus dessine le texte du frame par-dessus après ce callback, le
        chevron reste donc toujours entièrement sous le texte, quelle que
        soit son opacité."""
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(color_hex))
        canvas.setFillAlpha(opacity)
        p = canvas.beginPath()
        p.moveTo(x, y)
        p.lineTo(x + size, y + size / 2)
        p.lineTo(x + size, y - size / 2)
        p.close()
        canvas.drawPath(p, fill=1, stroke=0)
        canvas.restoreState()

    def _draw_geometric_background(self, canvas, width, height):
        """Arrière-plan décoratif : 3 chevrons empilés (coin haut-droit) +
        bande latérale discrète (bord droit), sur toutes les pages."""
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(self._CHEVRON_COLORS[2]))
        canvas.setFillAlpha(0.18)
        canvas.rect(width - 0.55 * inch, 0, 0.55 * inch, height, fill=1, stroke=0)
        canvas.restoreState()

        chevrons = [
            (width - 100, height - 55, self._CHEVRON_COLORS[0], 0.45),
            (width - 95, height - 120, self._CHEVRON_COLORS[1], 0.38),
            (width - 90, height - 185, self._CHEVRON_COLORS[2], 0.32),
        ]
        for x, y, color_hex, opacity in chevrons:
            self._draw_chevron(canvas, x, y, color_hex, opacity, size=60)

    def _page_decorations(self, canvas, doc):
        canvas.saveState()
        width, height = A4
        page_num = canvas.getPageNumber()

        self._draw_geometric_background(canvas, width, height)

        logo_x, logo_y, logo_size = 0.6 * inch, height - 0.95 * inch, 0.55 * inch
        logo_w = logo_size
        if os.path.isfile(LOGO_PATH):
            try:
                logo_w, _ = self._logo_dimensions(logo_size)
                canvas.drawImage(LOGO_PATH, logo_x, logo_y, width=logo_w, height=logo_size,
                                  preserveAspectRatio=True, mask='auto')
            except Exception:
                logo_w = logo_size
                self._draw_logo_placeholder(canvas, logo_x, logo_y, logo_size)
        else:
            self._draw_logo_placeholder(canvas, logo_x, logo_y, logo_size)

        # Titre du document en en-tête, à côté du logo — sur les pages de
        # contenu uniquement (la couverture porte déjà son propre grand
        # titre centré, cf. _add_cover_page, pour éviter la redondance).
        if page_num > 1:
            canvas.setFont('Helvetica-Bold', 9)
            canvas.setFillColor(self.PRIMARY)
            canvas.drawString(logo_x + logo_w + 0.15 * inch, logo_y + logo_size * 0.55,
                               "ANALYSE DE RISQUE DE CRÉDIT SECTORIELLE")
            canvas.setFont('Helvetica', 7.5)
            canvas.setFillColor(self.NEUTRAL)
            canvas.drawString(logo_x + logo_w + 0.15 * inch, logo_y + logo_size * 0.15,
                               str(self.results.get('company_name', '')))

        canvas.setStrokeColor(self.ACCENT)
        canvas.setLineWidth(1.5)
        canvas.line(0.6 * inch, 0.55 * inch, width - 0.6 * inch, 0.55 * inch)

        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(self.NEUTRAL)
        canvas.drawString(0.6 * inch, 0.38 * inch, "CONFIDENTIEL - Usage interne uniquement")
        canvas.drawRightString(width - 0.6 * inch, 0.38 * inch, f"Page {page_num}/{self._total_pages}")
        canvas.restoreState()

    def _logo_dimensions(self, target_height):
        """(width, height) pour dessiner LOGO_PATH à `target_height` points
        en conservant ses proportions réelles. Le logo officiel Wafa Gestion
        est un lockup horizontal (~3:1, icône + texte), pas une icône carrée
        — dessiner avec width=height comme l'ancien placeholder l'écraserait.
        Repli sur un carré si la taille du fichier ne peut pas être lue."""
        try:
            img_w, img_h = ImageReader(LOGO_PATH).getSize()
            return target_height * (img_w / img_h), target_height
        except Exception:
            return target_height, target_height

    def _draw_logo_placeholder(self, canvas, x, y, size):
        """Marque vectorielle de substitution (pas de dépendance à un fichier
        image externe) : carré orange arrondi + flèche de tendance blanche,
        même motif que static/images/logo.svg (Phase 5A) pour rester
        cohérent entre le PDF et l'interface web."""
        canvas.saveState()
        canvas.setFillColor(self.ACCENT)
        canvas.roundRect(x, y, size, size, radius=size * 0.22, fill=1, stroke=0)
        canvas.setStrokeColor(colors.white)
        canvas.setLineWidth(size * 0.09)
        canvas.setLineCap(1)
        canvas.setLineJoin(1)
        p = canvas.beginPath()
        p.moveTo(x + size * 0.20, y + size * 0.32)
        p.lineTo(x + size * 0.42, y + size * 0.58)
        p.lineTo(x + size * 0.56, y + size * 0.44)
        p.lineTo(x + size * 0.80, y + size * 0.72)
        canvas.drawPath(p, fill=0, stroke=1)
        canvas.restoreState()

    def _add_separator(self, color=None, thickness=2, width=7.0 * inch):
        line = Table([['']], colWidths=[width])
        line.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), thickness, color or self.ACCENT)]))
        self.elements.append(Spacer(1, 0.05 * inch))
        self.elements.append(line)
        self.elements.append(Spacer(1, 0.12 * inch))

    def _page_title(self, text, number=None):
        """Titre de page. Si `number` est fourni, affiche un badge carré
        orange numéroté devant le titre (sections logiques 1-5 du rapport,
        cf. Phase 5A+ — les pages de continuation type "(suite)" passent
        number=None pour ne pas répéter le même numéro)."""
        if number is not None:
            badge = Paragraph(f"<font color='white'><b>{number}</b></font>", ParagraphStyle(
                name='SectionBadge', alignment=TA_CENTER, fontSize=13, leading=16,
                fontName='Helvetica-Bold'))
            badge_cell = Table([[badge]], colWidths=[0.32 * inch], rowHeights=[0.32 * inch])
            badge_cell.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), self.ACCENT),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            title_cell = Paragraph(text, self.styles['PageTitle'])
            row = Table([[badge_cell, title_cell]], colWidths=[0.44 * inch, 6.56 * inch])
            row.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (1, 0), (1, 0), 8),
                ('LEFTPADDING', (0, 0), (0, 0), 0),
            ]))
            self.elements.append(row)
        else:
            self.elements.append(Paragraph(text, self.styles['PageTitle']))
        self._add_separator()

    # ------------------------------------------------------------------
    # Petits composants visuels réutilisables
    # ------------------------------------------------------------------
    def _table_cell(self, text, bold=False, color_hex=None, size=9.5, align=TA_LEFT):
        style = ParagraphStyle(
            name='TCell', fontName='Helvetica-Bold' if bold else 'Times-Roman',
            fontSize=size, leading=size + 3.5, alignment=align,
            textColor=colors.HexColor(color_hex) if color_hex else colors.black)
        return Paragraph(str(text), style)

    def _progress_bar(self, pct, color_hex, width=3.2 * inch, height=0.15 * inch):
        pct = max(0, min(100, pct or 0))
        filled = max(3, min(width - 3, width * (pct / 100.0)))
        remainder = width - filled
        t = Table([['', '']], colWidths=[filled, remainder], rowHeights=[height])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor(color_hex)),
            ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#E0E0E0')),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        return t

    def _note_row(self, label, note):
        bar = self._progress_bar(self._note_pct(note), self._note_hex(note))
        label_p = Paragraph(f"<b>{label}</b>", ParagraphStyle(name='RL', fontSize=9, fontName='Helvetica'))
        display = f"{note:.2f}/5" if note is not None else "N/A"
        value_p = Paragraph(f"<font color='{self._note_hex(note)}'><b>{display}</b></font>",
                             ParagraphStyle(name='RV', fontSize=9, alignment=TA_RIGHT))
        row = Table([[label_p, bar, value_p]], colWidths=[2.3 * inch, 2.8 * inch, 1.6 * inch])
        row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        return row

    def _info_box(self, text):
        """Boîte d'information : bordure gauche orange, fond gris très clair,
        icône '►' orange — pour une note qui mérite d'être visuellement
        détachée du corps de texte courant (cf. Phase 5A+)."""
        body = Paragraph(f"<font color='{self.HEX['accent']}'><b>&gt;</b></font>&nbsp; {text}",
                          ParagraphStyle(name='InfoBoxText', fontSize=9, leading=13,
                                         fontName='Helvetica', textColor=self.PRIMARY))
        box = Table([[body]], colWidths=[7 * inch])
        box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), self.LIGHT_BG),
            ('LINEBEFORE', (0, 0), (0, -1), 3, self.ACCENT),
            ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        return box

    def _append_override_note(self, details):
        """Ajoute une note transparente sur l'origine des notes Secteur/Gouvernance.

        Ces deux blocs (contrairement aux Ratios Financiers, calculés depuis le
        dossier Excel) utilisent par défaut des notes de référence fixes
        (`sector_weights`/`governance_weights` dans sectors.py) tant qu'aucune
        évaluation qualitative réelle n'a été fournie via `overrides` — voir
        `RatingEngine._weighted_block`. Sans cette précision, un score comme
        "Gouvernance 4.0/5" peut être lu à tort comme une évaluation réelle du
        dossier plutôt que comme une valeur de référence générique.
        """
        if not details:
            return
        overridden = [d['label'] for d in details if d.get('is_override')]
        if not overridden:
            note = ("Valeurs de référence par défaut du secteur — aucune évaluation "
                    "qualitative spécifique à ce dossier n'a été fournie pour ce bloc.")
        elif len(overridden) < len(details):
            note = (f"Personnalisé(s) pour ce dossier : {', '.join(overridden)}. "
                    "Les autres critères de ce bloc utilisent la valeur de référence par défaut.")
        else:
            note = "Toutes les valeurs de ce bloc ont été personnalisées pour ce dossier."
        self.elements.append(Spacer(1, 0.04 * inch))
        self.elements.append(self._info_box(note))
        self.elements.append(Spacer(1, 0.04 * inch))

    # ========================
    # PAGE 1 : COUVERTURE
    # ========================
    def _add_cover_page(self):
        r = self.results
        fr = r.get('final_rating', {}) or {}
        self.elements.append(Spacer(1, 0.6 * inch))
        self.elements.append(Paragraph("NOTE DE CRÉDIT SECTORIELLE", self.styles['CoverTitle']))
        self.elements.append(Spacer(1, 0.1 * inch))
        self._add_separator(thickness=3)
        self.elements.append(Spacer(1, 0.3 * inch))

        company_name = r.get('company_name', 'N/A')
        sector_name = r.get('sector_name', str(r.get('sector', 'N/A')).capitalize())
        self.elements.append(Paragraph(
            f"<b>{str(company_name).upper()}</b><br/>{sector_name}",
            self.styles['CoverCompany']))
        self.elements.append(Spacer(1, 0.5 * inch))

        score = fr.get('final_score')
        score_display = f"{score:.2f}" if score is not None else "N/A"
        rec_hex = self._rec_hex((fr.get('recommendation') or {}).get('color'))
        category = fr.get('category')
        rating_label = fr.get('rating', 'N/A')

        # Encadré note + catégorie : fond gris clair, bordure orange (thème
        # Wafa) — remplace l'ancien pavé bleu plein avec texte blanc.
        score_para = Paragraph(
            f"<font color='{self.HEX['accent']}'><b>{score_display}</b></font>"
            f"<font color='{self.HEX['neutral']}' size=16> / 5.0</font>",
            ParagraphStyle(name='ScoreBig', alignment=TA_CENTER, fontSize=48,
                           leading=56, fontName='Helvetica-Bold'))
        score_sub = Paragraph(f"<font color='{self.HEX['primary']}'>NOTE FINALE</font>",
                               ParagraphStyle(name='ScoreSub', alignment=TA_CENTER, fontSize=11, leading=14))
        cat_para = Paragraph(
            f"<font color='{rec_hex}'><b>CATÉGORIE {category} — {rating_label}</b></font>",
            ParagraphStyle(name='CatCover', fontSize=15, leading=19, alignment=TA_CENTER,
                           fontName='Helvetica-Bold'))
        score_table = Table([[score_sub], [score_para], [cat_para]], colWidths=[4.8 * inch])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), self.LIGHT_BG),
            ('BOX', (0, 0), (-1, -1), 2, self.ACCENT),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (0, 0), 18), ('BOTTOMPADDING', (0, 0), (0, 0), 0),
            ('TOPPADDING', (0, 2), (0, 2), 6), ('BOTTOMPADDING', (0, 2), (0, 2), 18),
        ]))
        wrap = Table([[score_table]], colWidths=[7 * inch])
        wrap.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        self.elements.append(wrap)
        self.elements.append(Spacer(1, 0.4 * inch))
        breakdown = [
            ['Secteur (20%)', f"{fr.get('sector_score', 'N/A')}/5"],
            ['Ratios Financiers (60%)', f"{fr.get('financial_score', 'N/A')}/5"],
            ['Gouvernance (20%)', f"{fr.get('governance_score', 'N/A')}/5"],
        ]
        bt = Table([['Composante', 'Score']] + breakdown, colWidths=[3.5 * inch, 1.5 * inch])
        bt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.LIGHT_BG), ('TEXTCOLOR', (0, 0), (-1, 0), self.PRIMARY),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        centered = Table([[bt]], colWidths=[7 * inch])
        centered.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        self.elements.append(centered)

        self.elements.append(Spacer(1, 0.6 * inch))
        self.elements.append(Paragraph(
            f"<i>Date d'émission : {datetime.now().strftime('%d %B %Y')}</i>",
            ParagraphStyle(name='DateCover', fontSize=10, leading=13, alignment=TA_CENTER, textColor=self.NEUTRAL)))

    # ========================
    # PAGE 2 : SYNTHÈSE EXÉCUTIVE
    # ========================
    def _add_executive_summary_page(self):
        """Synthèse Exécutive : 4 zones — (1) Note & Profil factuel [pas de
        décision d'octroi, cf. commande "FINAL Correction Pages 2 & 10" :
        la plateforme évalue le risque, le comité de crédit décide], (2)
        Facteurs favorables / Points de vigilance (2 colonnes), (3) KPI
        secteur-spécifiques avec tendance, (4) radar des 3 blocs (secondaire)."""
        r = self.results
        self._page_title("SYNTHÈSE EXÉCUTIVE", number=self._section_numbers['exec'])

        fr = r.get('final_rating', {}) or {}
        risk_drivers = r.get('risk_drivers') or {}
        category = fr.get('category')
        rating_hex = self._rec_hex((fr.get('recommendation') or {}).get('color'))

        # [1] Note & Profil
        score = fr.get('final_score')
        score_display = f"{score:.2f} / 5.0" if score is not None else "N/A"
        self.elements.append(Paragraph(
            f"<font color='{self.HEX['accent']}'><b>NOTE FINALE — {score_display}</b></font>",
            ParagraphStyle(name='ExecNoteBig', fontSize=26, leading=30, fontName='Helvetica-Bold')))
        self.elements.append(Paragraph(
            f"<font color='{rating_hex}'><b>CATÉGORIE {category} — "
            f"{str(fr.get('rating', 'N/A')).upper()}</b></font>",
            ParagraphStyle(name='ExecCat', fontSize=13.5, leading=17, fontName='Helvetica-Bold')))
        self.elements.append(Spacer(1, 0.1 * inch))
        self.elements.append(Paragraph(
            self._generate_profile_summary(r.get('sector'), category, risk_drivers),
            self.styles['Body']))
        self.elements.append(Spacer(1, 0.2 * inch))

        # [2] Facteurs favorables / Points de vigilance (2 colonnes)
        self._add_factors_columns(risk_drivers)
        self.elements.append(Spacer(1, 0.2 * inch))

        # [3] KPI clés secteur-spécifiques + tendance
        kpi = NarrativeGenerator.generate_for_executive_summary(
            fr, risk_drivers, r.get('sector_ratios') or {}, r.get('financials') or {}, r.get('sector'),
            sector_ratios_provenance=r.get('sector_ratios_provenance') or {},
        ).get('kpi') or {}
        self._add_kpi_cards(kpi, r.get('years') or [])
        self.elements.append(Spacer(1, 0.18 * inch))

        # [4] Radar des 3 blocs — secondaire, texte prioritaire ci-dessus
        self.elements.append(Paragraph(
            "<i>Répartition de la note entre les 3 blocs (secondaire — détail page Notation) :</i>",
            self.styles['Small']))
        radar_buf = self.charts.radar_chart(
            (r.get('sector_result') or {}).get('score'),
            (r.get('financial_result') or {}).get('score'),
            (r.get('governance_result') or {}).get('score'),
        )
        radar_row = Table([[RLImage(radar_buf, width=2.6 * inch, height=2.6 * inch)]], colWidths=[7 * inch])
        radar_row.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        self.elements.append(radar_row)

    # ========================
    # PAGES 3-5 : GRAPHIQUES ANALYTIQUES (historique 1-5 exercices)
    # ========================
    def _add_analytical_charts_pages(self):
        r = self.results
        sector_ratio_series = r.get('sector_ratio_series_provenance') or {}
        generic_ratio_series = r.get('ratio_series_provenance') or {}
        raw_series = r.get('financial_series') or {}
        years = r.get('years') or []
        sector_cfg = SectorConfig.get_sector_config(r.get('sector'))
        benchmarks = sector_cfg.get('benchmarks', {})

        charts = self.charts.generate_all_charts(
            sector_ratio_series, generic_ratio_series, raw_series, years, benchmarks)

        self._page_title("ANALYSE GRAPHIQUE — HISTORIQUE FINANCIER", number=self._section_numbers['charts'])
        n_years = len([y for y in years if y is not None]) or len(years)
        self.elements.append(Paragraph(
            f"<i>{n_years} exercice(s) exploité(s) dans le dossier transmis. Une interruption dans un "
            f"graphique signale une donnée absente du dossier pour cette année — jamais une valeur "
            f"comblée. Les points marqués « Proxy » (hachures / marqueur évidé) sont des approximations "
            f"faute de donnée réelle disponible.</i>", self.styles['Small']))
        self.elements.append(Spacer(1, 0.1 * inch))

        # 2 graphiques par page : le nombre de pages réellement nécessaires
        # (3 pour Assurance [5 graphiques], 4 pour Banque/Industrie [7]) est
        # calculé dynamiquement par le mécanisme de pagination à 2 passes de
        # `generate()` (cf. `_count_pages_decoration`) — la numérotation
        # "Page X/N" en pied de page reste donc toujours synchronisée, même
        # si le total dépasse le budget nominal de 3 pages "Analyse graphique".
        per_page = 2
        groups = [charts[i:i + per_page] for i in range(0, len(charts), per_page)]
        for idx, group in enumerate(groups):
            if idx > 0:
                self.elements.append(PageBreak())
                self._page_title("ANALYSE GRAPHIQUE (suite)")
            self._render_chart_pair(group)

    def _render_chart_pair(self, chart_group):
        for c in chart_group:
            img = RLImage(c['chart'], width=5.8 * inch, height=3.05 * inch)
            img_row = Table([[img]], colWidths=[7 * inch])
            img_row.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
            self.elements.append(img_row)
            if c.get('narrative'):
                self.elements.append(Paragraph(c['narrative'], self.styles['Small']))
            else:
                self.elements.append(Paragraph(
                    "<i>Historique insuffisant pour une interprétation factuelle (moins de 2 exercices "
                    "disponibles pour cet indicateur).</i>", self.styles['Small']))
            self.elements.append(Spacer(1, 0.12 * inch))

    # ========================
    # NOTES MÉTHODOLOGIQUES (après les graphiques, avant la Notation)
    # ========================
    _BENCHMARK_LABEL_OVERRIDES = {'roa': 'ROA', 'roe': 'ROE', 'ebit_margin': 'Marge EBIT'}

    def _benchmark_indicator_label(self, key, ratios_cfg):
        """Libellé lisible pour un indicateur de `benchmarks` (cf.
        sectors.py) : reprend la description du ratio sectoriel du même nom
        si elle existe, sinon un intitulé explicite pour les quelques clés
        de référence qui n'ont pas d'équivalent dans `ratios` (ex : ROA/ROE,
        génériques aux 3 secteurs), sinon la clé mise en forme."""
        cfg = ratios_cfg.get(key)
        if cfg:
            return cfg['description']
        if key in self._BENCHMARK_LABEL_OVERRIDES:
            return self._BENCHMARK_LABEL_OVERRIDES[key]
        return key.replace('_', ' ').capitalize()

    def _add_benchmark_sources_block(self, results):
        """Tableau des références marocaines sourcées (BAM / AMMC / Office
        des Changes / ...) configurées pour le secteur de CE dossier — cf.
        Phase 5A+ "Intégration Benchmarks Marocains". Ne liste que les
        benchmarks du secteur analysé (pas les 3 secteurs à la fois : un
        rapport donné ne porte que sur l'un d'eux)."""
        sector_cfg = SectorConfig.get_sector_config(results.get('sector'))
        ratios_cfg = sector_cfg.get('ratios', {})
        benchmarks = sector_cfg.get('benchmarks', {})
        sourced = [(k, b) for k, b in benchmarks.items() if b.get('source')]

        if not sourced:
            self.elements.append(Paragraph(
                "<b>Statut actuel</b> : valeurs de référence internes, provisoires — aucune n'est "
                "sourcée à ce jour auprès d'un référentiel sectoriel ou réglementaire externe cité "
                "dans ce dossier.", self.styles['Body']))
            return

        self.elements.append(Paragraph(
            "Références marocaines officielles retenues pour ce secteur :", self.styles['Body']))
        self.elements.append(Spacer(1, 0.06 * inch))

        # Cellules en Paragraph (pas de simples chaînes) : les sources
        # marocaines sont des libellés longs qui doivent pouvoir passer à la
        # ligne dans leur colonne — même mécanisme que _table_cell ailleurs
        # dans ce fichier (une chaîne brute trop longue déborde sur les
        # colonnes voisines au lieu de se répartir sur plusieurs lignes).
        header = lambda t, align=TA_LEFT: self._table_cell(t, bold=True, color_hex=self.HEX['primary'],
                                                              size=8.5, align=align)
        rows = [[header('Indicateur'), header('Valeur', TA_CENTER), header('Source'), header('Année', TA_CENTER)]]
        for key, b in sourced:
            val = f"{b['value']:.2f}{b.get('unit', '')}" if b.get('value') is not None else 'N/A'
            rows.append([
                self._table_cell(self._benchmark_indicator_label(key, ratios_cfg), size=8.5),
                self._table_cell(val, size=8.5, align=TA_CENTER),
                self._table_cell(b.get('source', ''), size=8.5),
                self._table_cell(str(b.get('year', '—')), size=8.5, align=TA_CENTER),
            ])

        table = Table(rows, colWidths=[1.9 * inch, 0.8 * inch, 3.4 * inch, 0.6 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.LIGHT_BG),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, self.LIGHT_BG2]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        self.elements.append(table)

        urls = sorted({b['source_url'] for _, b in sourced if b.get('source_url')})
        if urls:
            self.elements.append(Spacer(1, 0.05 * inch))
            self.elements.append(Paragraph(f"<i>{' | '.join(urls)}</i>", self.styles['Small']))

        regulatory_n = sum(1 for _, b in sourced if b.get('source_type') == 'regulatory')
        if regulatory_n:
            self.elements.append(Spacer(1, 0.04 * inch))
            self.elements.append(Paragraph(
                f"<i>{regulatory_n} référence(s) réglementaire(s) (seuil BAM/AMMC opposable) ; "
                f"les autres sont des moyennes/médianes sectorielles statistiques, non opposables.</i>",
                self.styles['Small']))
        self.elements.append(Spacer(1, 0.1 * inch))

    def _add_methodology_page(self):
        r = self.results
        self._page_title("NOTES MÉTHODOLOGIQUES", number=self._section_numbers['methodology'])

        self.elements.append(Paragraph("Sources des Données", self.styles['SubHeading']))
        self.elements.append(Paragraph(
            "<b>Données réelles</b> : extraites directement du fichier Excel transmis pour ce dossier.",
            self.styles['Body']))
        self.elements.append(Paragraph(
            "<b>Ratios calculés</b> : formules sectorielles appliquées aux données réelles "
            "(détail page « Tableau de Notation Détaillé »).", self.styles['Body']))
        self.elements.append(Paragraph(
            "<b>Proxies</b> : approximations utilisées quand une donnée réelle spécifique est "
            "indisponible — ex : le PNB est estimé à partir des Revenus si la ligne « PNB » est "
            "absente du dossier. Chaque proxy est signalé visuellement (barre/point hachuré) "
            "<b>et</b> annoté en toutes lettres sous le graphique concerné (ex : « Proxy — PNB "
            "indisponible, Revenus utilisé ») — jamais présenté comme une donnée réelle.",
            self.styles['Body']))
        self.elements.append(Paragraph(
            "<b>N/A</b> : données manquantes, jamais remplacées par une valeur inventée. Un "
            "graphique sans aucune donnée exploitable affiche « Données indisponibles » ; un "
            "exercice isolé manquant au sein d'un historique par ailleurs disponible est marqué "
            "d'un repère « N/A » sur le graphique, en plus de l'interruption visuelle de la "
            "courbe ou de l'absence de barre.", self.styles['Body']))
        self.elements.append(Spacer(1, 0.16 * inch))

        self.elements.append(Paragraph("Benchmarks Sectoriels", self.styles['SubHeading']))
        self._add_benchmark_sources_block(r)
        self.elements.append(Paragraph(
            "<b>Utilisation</b> : comparaison visuelle indicative uniquement — les benchmarks "
            "n'entrent pas dans le calcul de la note finale (Secteur 20% / Ratios Financiers 60% "
            "/ Gouvernance 20%, cf. page « Tableau de Notation Détaillé »).", self.styles['Body']))
        self.elements.append(Spacer(1, 0.16 * inch))

        self.elements.append(Paragraph("Historique", self.styles['SubHeading']))
        years = r.get('years') or []
        real_years = [y for y in years if y is not None]
        n_years = len(real_years) if real_years else len(years)
        coverage_txt = (f"{real_years[0]}-{real_years[-1]} ({n_years} exercices)" if len(real_years) > 1
                         else f"{n_years} exercice (année non renseignée dans le fichier)" if not real_years
                         else f"{n_years} exercice ({real_years[0]})")
        self.elements.append(Paragraph(
            f"<b>Couverture de ce dossier</b> : {coverage_txt} sur un maximum de 5 exercices "
            "exploités (1 à 5 selon la disponibilité dans le fichier transmis).", self.styles['Body']))
        self.elements.append(Paragraph(
            "<b>Analyse</b> : les tendances (direction, amplitude, momentum) sont calculées "
            "uniquement à partir des exercices réellement présents dans le dossier — aucune "
            "extrapolation au-delà des données disponibles.", self.styles['Body']))
        self.elements.append(Paragraph(
            "<b>Alertes</b> : un historique incomplet est signalé directement sur chaque "
            "graphique concerné (barre absente, ligne interrompue, repère « N/A »), sans "
            "nécessiter de s'y référer ailleurs dans le rapport.", self.styles['Body']))

    # ========================
    # PAGE 6 : TABLEAU DE NOTATION DÉTAILLÉ (style ATW)
    # ========================
    def _block_table(self, title, details, weight_pct, block_score, show_override_note=False):
        """Tableau style Wafa : en-tête gris clair + texte foncé (pas de
        couleurs flashy), alternance de lignes blanc / gris très clair."""
        rows = [['Critère', 'Poids', 'Note /5', 'Contribution']]
        for d in details:
            note = d.get('note')
            note_display = f"{note:.2f}" if note is not None else "N/A"
            contrib = f"{(note * d['weight']):.1f}" if note is not None else "—"
            rows.append([d['label'], str(d['weight']), note_display, contrib])

        table = Table(rows, colWidths=[3.1 * inch, 0.8 * inch, 0.9 * inch, 1.2 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.LIGHT_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.PRIMARY),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, self.LIGHT_BG2]),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))

        heading = Paragraph(
            f"<font color='{self.HEX['accent']}'><b>{title}</b></font>"
            f"<b> — {weight_pct}% — Score : {block_score:.2f}/5</b>",
            ParagraphStyle(name=f'BlockHead_{title}', fontSize=11, leading=14,
                           fontName='Helvetica-Bold', textColor=self.PRIMARY,
                           spaceBefore=8, spaceAfter=4))
        self.elements.append(heading)
        self.elements.append(table)
        if show_override_note:
            self._append_override_note(details)
        self.elements.append(Spacer(1, 0.12 * inch))

    def _add_rating_table_page(self):
        self._page_title("TABLEAU DE NOTATION DÉTAILLÉ", number=self._section_numbers['rating'])
        r = self.results
        sector_result = r.get('sector_result', {}) or {}
        financial_result = r.get('financial_result', {}) or {}
        governance_result = r.get('governance_result', {}) or {}
        fr = r.get('final_rating', {}) or {}

        # Secteur/Gouvernance : notes de référence par défaut sauf overrides
        # qualitatifs fournis (cf. _append_override_note) ; Ratios Financiers :
        # toujours calculé depuis le dossier Excel, donc pas de note d'origine.
        self._block_table("SECTEUR", sector_result.get('details', []), 20,
                           sector_result.get('score', 0), show_override_note=True)
        self._block_table("RATIOS FINANCIERS", financial_result.get('details', []), 60,
                           financial_result.get('score', 0))
        self._block_table("GOUVERNANCE", governance_result.get('details', []), 20,
                           governance_result.get('score', 0), show_override_note=True)

        self.elements.append(Spacer(1, 0.1 * inch))
        summary = [
            ['Bloc', 'Pondération', 'Score /5', 'Contribution'],
            ['Secteur', '20%', f"{fr.get('sector_score', 0):.2f}", f"{fr.get('sector_score', 0) * 0.20:.2f}"],
            ['Ratios Financiers', '60%', f"{fr.get('financial_score', 0):.2f}", f"{fr.get('financial_score', 0) * 0.60:.2f}"],
            ['Gouvernance', '20%', f"{fr.get('governance_score', 0):.2f}", f"{fr.get('governance_score', 0) * 0.20:.2f}"],
            ['NOTE FINALE', '100%', '', f"{fr.get('final_score', 0):.2f}/5"],
        ]
        st = Table(summary, colWidths=[2.3 * inch, 1.3 * inch, 1.3 * inch, 1.4 * inch])
        st.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.PRIMARY), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor(self._rec_hex((fr.get('recommendation') or {}).get('color')))),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('FONTSIZE', (0, -1), (-1, -1), 11),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        self.elements.append(st)

    # ========================
    # PAGE 3 : STRUCTURE ACTIONNARIALE (narration + pie chart + table)
    # ========================
    def _add_shareholders_page(self):
        """Actionnariat (onglet Excel optionnel, commun aux 3 secteurs
        Banking/Industrie/Assurance, cf. modules/data_processing.py). Pure
        visibilité : n'entre dans aucun calcul de score — cf. critère
        "Type d'actionnariat" du bloc Gouvernance (page Notation), qui
        continue d'utiliser sa note de référence/override indépendamment de
        ce qui est affiché ici.

        Non appelée par EnrichedBankingReportGenerator (sa propre page
        « Données Enrichies » montre déjà l'actionnariat, avec le
        Management en plus) — pas de doublon possible entre les 2 gabarits."""
        self._page_title("STRUCTURE ACTIONNARIALE", number=self._section_numbers['shareholders'])
        shareholders = self.results.get('shareholders') or []

        if not shareholders:
            self.elements.append(Paragraph(
                "<i>Données d'actionnariat non disponibles (onglet « Actionnariat » absent du "
                "fichier transmis).</i>", self.styles['Small']))
            return

        self.elements.append(Paragraph(
            self._generate_shareholder_narration(shareholders), self.styles['Body']))
        self.elements.append(Spacer(1, 0.16 * inch))

        pie_buf = self.charts.shareholders_pie_chart(shareholders)
        img_row = Table([[RLImage(pie_buf, width=3.3 * inch, height=3.3 * inch)]], colWidths=[7 * inch])
        img_row.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        self.elements.append(img_row)
        self.elements.append(Spacer(1, 0.16 * inch))

        self.elements.append(Paragraph("Détail des Actionnaires", self.styles['SubHeading']))
        self._add_shareholders_table(shareholders)

    def _generate_shareholder_narration(self, shareholders):
        """Narration factuelle (1-3 phrases) : ne décrit que des valeurs
        réellement présentes dans `shareholders` (nombre d'actionnaires,
        poids du 1er actionnaire, nature) — jamais un jugement inventé
        indépendamment des données de CE dossier (même principe directeur
        que narrative_generator.py)."""
        n = len(shareholders)
        ranked = sorted(
            (s for s in shareholders if s.get('pct') is not None),
            key=lambda s: s['pct'], reverse=True)

        if not ranked:
            return (f"Structure actionnariale composée de {n} actionnaire(s) recensé(s) "
                    "(pourcentages de détention non renseignés dans le fichier transmis).")

        top = ranked[0]
        top_pct, top_name = top['pct'], top.get('name', 'N/A')
        if top_pct >= 50:
            concentration = f"un actionnaire majoritaire, {top_name} ({top_pct:.1f}%)"
        elif top_pct >= 33.34:
            concentration = (f"un actionnaire de référence disposant d'une minorité de "
                              f"blocage, {top_name} ({top_pct:.1f}%)")
        elif top_pct >= 20:
            concentration = f"un actionnaire de référence, {top_name} ({top_pct:.1f}%)"
        else:
            concentration = (f"un actionnariat dispersé, sans actionnaire dominant "
                              f"(premier rang : {top_name}, {top_pct:.1f}%)")

        sentence = f"Structure actionnariale composée de {n} actionnaire(s) recensé(s), avec {concentration}."

        if len(ranked) >= 2:
            top_n = ranked[:3]
            top_n_pct = sum(s['pct'] for s in top_n)
            names = ', '.join(f"{s.get('name', '')} ({s['pct']:.1f}%)" for s in top_n)
            sentence += (f" Les {len(top_n)} principaux actionnaires ({names}) "
                         f"totalisent {top_n_pct:.1f}% du capital.")

        natures = sorted({str(s['nature']).strip() for s in shareholders if s.get('nature')})
        if len(natures) > 1:
            sentence += f" Nature de l'actionnariat diversifiée : {', '.join(natures)}."

        total_pct = sum(s['pct'] for s in ranked)
        if abs(total_pct - 100) > 1.0:
            sentence += (f" Note : les pourcentages de détention renseignés totalisent "
                         f"{total_pct:.1f}% (écart possible avec le fichier transmis).")

        return sentence

    def _add_shareholders_table(self, shareholders):
        """Table détaillée Actionnariat — cf. `_add_shareholders_page`."""
        header = lambda t, align=TA_LEFT: self._table_cell(t, bold=True, color_hex=self.HEX['primary'],
                                                              size=8.5, align=align)
        rows = [[header('Actionnaire'), header('% Détention', TA_CENTER), header('Montant (MDH)', TA_RIGHT),
                 header('Nature'), header('Depuis', TA_CENTER), header('Notes')]]
        for sh in shareholders:
            rows.append([
                self._table_cell(sh.get('name', ''), size=8.5),
                self._table_cell(self._safe_format(sh.get('pct'), 1, '%'), size=8.5, align=TA_CENTER),
                self._table_cell(self._safe_money_m(sh.get('amount')), size=8.5, align=TA_RIGHT),
                self._table_cell(sh.get('nature') or '', size=8.5),
                self._table_cell(sh.get('since') or '', size=8.5, align=TA_CENTER),
                self._table_cell(sh.get('notes') or '', size=8),
            ])
        table = Table(rows, colWidths=[1.6 * inch, 0.9 * inch, 1.1 * inch, 1.3 * inch, 0.7 * inch, 1.4 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.LIGHT_BG),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, self.LIGHT_BG2]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        self.elements.append(table)

    # ========================
    # PAGE 6 : RECOMMANDATION & CONCLUSION
    # ========================
    def _add_category_and_profile(self):
        """Bloc principal Page 10 : catégorie + note, et un qualificatif
        neutre par catégorie — jamais de décision d'octroi (contrairement à
        l'ancien "APPROUVER AVEC CONDITIONS" affiché ici)."""
        r = self.results
        fr = r.get('final_rating', {}) or {}
        category = fr.get('category', 4)
        rec_hex = self._rec_hex((fr.get('recommendation') or {}).get('color'))
        neutral_note = self._CATEGORY_NEUTRAL_NOTE.get(category, self._CATEGORY_NEUTRAL_NOTE[4])

        box_text = Paragraph(
            f"<font color='white'><b>CATÉGORIE {category} — {str(fr.get('rating', 'N/A')).upper()} "
            f"(Note : {fr.get('final_score', 'N/A')}/5)</b></font><br/>"
            f"<font color='white' size=10.5>{neutral_note} Décision et conditions restent de la "
            f"responsabilité du comité de crédit.</font>",
            ParagraphStyle(name='RecBig', alignment=TA_CENTER, fontSize=15, fontName='Helvetica-Bold', leading=19))
        box = Table([[box_text]], colWidths=[7 * inch])
        box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(rec_hex)),
            ('TOPPADDING', (0, 0), (-1, -1), 16), ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
            ('LEFTPADDING', (0, 0), (-1, -1), 16), ('RIGHTPADDING', (0, 0), (-1, -1), 16),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        self.elements.append(box)
        self.elements.append(Spacer(1, 0.22 * inch))

    def _add_key_factors_to_monitor(self):
        """Facteurs clés à surveiller : croise les facteurs négatifs déjà
        classés (`risk_drivers['negatifs']`) avec les seuils de référence
        marocains sourcés (`sectors.py` -> 'benchmarks', BAM/AMMC/...) —
        seuil réel, jamais inventé ; un facteur négatif sans benchmark
        sourcé pour ce secteur n'est simplement pas listé ici."""
        self.elements.append(Paragraph("Facteurs Clés à Surveiller", self.styles['SubHeading']))
        r = self.results
        sector_cfg = SectorConfig.get_sector_config(r.get('sector'))
        ratios_cfg = sector_cfg.get('ratios', {})
        benchmarks = sector_cfg.get('benchmarks', {})
        negatives = (r.get('risk_drivers') or {}).get('negatifs') or []

        lines, seen_keys = [], set()
        for d in negatives:
            key = d.get('key')
            bm = benchmarks.get(key)
            if not bm or bm.get('value') is None or key in seen_keys:
                continue
            seen_keys.add(key)
            higher_is_better = ratios_cfg.get(key, {}).get('higher_is_better', True)
            verb = 'maintenir au-dessus de' if higher_is_better else 'contenir sous'
            unit = bm.get('unit', '')
            label = self._benchmark_indicator_label(key, ratios_cfg)
            source_txt = f" ({bm['source']})" if bm.get('source') else ''
            lines.append(f"{label} : {verb} {bm['value']:.2f}{unit}{source_txt}")
            if len(lines) >= 4:
                break

        if not lines:
            self.elements.append(Paragraph(
                "<i>Aucun seuil de référence sourcé disponible pour les facteurs de vigilance "
                "identifiés sur ce dossier.</i>", self.styles['Small']))
            return
        for line in lines:
            self.elements.append(Paragraph(f"• {line}", self.styles['Body']))

    def _add_analytical_conclusion(self):
        """Conclusion analytique neutre : constat factuel (note, catégorie,
        forces/points de vigilance déjà identifiés) — sans branche
        prescriptive par catégorie (l'ancienne version recommandait
        implicitement l'octroi ou la restructuration selon la catégorie)."""
        self.elements.append(Paragraph("Conclusion Analytique", self.styles['SubHeading']))
        r = self.results
        fr = r.get('final_rating', {}) or {}
        category = fr.get('category', 4)
        company_name = r.get('company_name', 'Cette entité')
        sector_name = r.get('sector_name', 'son secteur')
        risk_drivers = r.get('risk_drivers') or {}
        positives = risk_drivers.get('positifs') or []
        negatives = risk_drivers.get('negatifs') or []

        conclusion = (
            f"Sur la base de la grille de notation sectorielle appliquée (Secteur 20%, Ratios Financiers "
            f"60%, Gouvernance 20%), {company_name} obtient une note finale de "
            f"<b>{fr.get('final_score', 'N/A')}/5</b>, la classant en <b>catégorie {category} "
            f"({fr.get('rating', 'N/A')})</b> au sein du {sector_name.lower()}. "
        )
        if positives:
            conclusion += (f"Les forces du profil incluent : "
                            f"{', '.join(d.get('label', '') for d in positives[:3])}. ")
        if negatives:
            conclusion += (f"Les points de vigilance concernent : "
                            f"{', '.join(d.get('label', '') for d in negatives[:3])}.")
        self.elements.append(Paragraph(conclusion, self.styles['Body']))

    def _add_disclaimer(self):
        self.elements.append(Paragraph("Décharge de Responsabilité", self.styles['SubHeading']))
        self.elements.append(Paragraph(
            "Cette analyse évalue le risque de crédit selon la méthodologie sectorielle définie. Elle "
            "constitue un avis analytique uniquement. La décision d'octroi du crédit, les conditions de "
            "financement (montant, durée, taux d'intérêt, covenants, garanties) et la structuration du "
            "crédit restent la responsabilité exclusive du comité de crédit et de la direction générale.",
            ParagraphStyle(name='Disclaimer', fontSize=8.5, leading=11.5, fontName='Helvetica-Oblique',
                           textColor=self.NEUTRAL, alignment=TA_JUSTIFY)))

    def _add_recommendation_page(self):
        """Page 10 : Recommandation & Conclusion — analyse de risque, pas
        décision d'octroi (cf. commande "FINAL Correction Pages 2 & 10").
        Remplace l'ancien bloc "Conditions Proposées" (montant/durée/taux/
        covenants/garanties, décision implicite de la plateforme) par des
        facteurs de vigilance sourcés, une conclusion neutre et une décharge
        de responsabilité explicite."""
        self._page_title("RECOMMANDATION & CONCLUSION", number=self._section_numbers['recommendation'])
        self._add_category_and_profile()
        self._add_key_factors_to_monitor()
        self.elements.append(Spacer(1, 0.18 * inch))
        self._add_analytical_conclusion()
        self.elements.append(Spacer(1, 0.2 * inch))
        self._add_disclaimer()
        self.elements.append(Spacer(1, 0.16 * inch))

        self.elements.append(Paragraph("Comité de Crédit", self.styles['SubHeading']))
        for c in ["Analyste Crédit : Direction des Risques",
                  "Manager Relation Client : Direction Commerciale",
                  "Décision finale : Comité de Crédit / Direction Générale"]:
            self.elements.append(Paragraph(f"• {c}", self.styles['Body']))


def generate_pdf_report(results):
    """Fonction wrapper pour générer le PDF de notation sectorielle (V7)."""
    os.makedirs('uploads/reports', exist_ok=True)

    # `secure_filename` ici (pas seulement au téléchargement) pour que le nom
    # écrit sur disque corresponde exactement à celui que `download_report()`
    # recherche après l'avoir lui-même passé par `secure_filename` — sinon un
    # nom d'entreprise contenant des espaces ou accents ne se retrouve jamais
    # (404 au clic sur "Télécharger le rapport PDF").
    safe_company = secure_filename(results['company_name']) or 'Company'
    filename = f"Note_Credit_{safe_company}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join('uploads/reports', filename)

    try:
        generator = CreditReportGeneratorV7(results, output_path)
        generator.generate()
        return output_path, filename
    except Exception as e:
        print(f"Erreur génération PDF: {str(e)}")
        raise


# ============================================================================
# Variante : template bancaire enrichi (8 onglets)
# ============================================================================

class EnrichedBankingReportGenerator(CreditReportGeneratorV7):
    """Variante du rapport V7 pour le template bancaire enrichi (8 onglets,
    cf. modules/banking_enriched_processor.py) : remplace la page « Analyse
    Graphique » (qui suppose les séries génériques Bilan/P&L/Flux du
    parseur historique — absentes de ce template) par une page « Données
    Enrichies » (portefeuille crédit par secteur, actionnariat, management,
    données qualitatives, traçabilité). Les 5 autres pages (couverture,
    synthèse exécutive, méthodologie, notation, recommandation) sont
    héritées à l'identique : elles ne dépendent que de `final_rating` /
    `sector_result` / `financial_result` / `governance_result` /
    `risk_drivers`, produits par la MÊME grille de notation
    (RatingEngine/build_rating, 20/60/20) que /analyze — le score n'est pas
    affecté par ce changement de mise en page."""

    def __init__(self, results, output_path):
        super().__init__(results, output_path)
        # Renumérotation propre à ce gabarit (pas de page "Structure
        # Actionnariale" ni "Analyse Graphique" ici — remplacées par la
        # page unique "Données Enrichies", qui montre déjà l'actionnariat).
        self._section_numbers = {
            'exec': 1, 'enriched': 2,
            'methodology': 3, 'rating': 4, 'recommendation': 5,
        }

    def _build_pages(self, target):
        self.elements = []
        self.doc = SimpleDocTemplate(target, **self._doc_kwargs)
        self._add_cover_page()                    # Page 1
        self.elements.append(PageBreak())
        self._add_executive_summary_page()          # Page 2
        self.elements.append(PageBreak())
        self._add_enriched_data_page()                # Page(s) 3 : Données Enrichies
        self.elements.append(PageBreak())
        self._add_methodology_page()                    # Notes Méthodologiques
        self.elements.append(PageBreak())
        self._add_rating_table_page()                     # Tableau de Notation
        self.elements.append(PageBreak())
        self._add_recommendation_page()                     # Recommandation & Conclusion

    # ========================
    # DONNÉES ENRICHIES
    # ========================
    def _add_enriched_data_page(self):
        self._page_title("DONNÉES ENRICHIES", number=self._section_numbers['enriched'])
        enriched = self.results.get('enriched') or {}
        self._add_portfolio_section(enriched.get('portfolio') or {}, enriched.get('indicators') or {})
        self.elements.append(Spacer(1, 0.14 * inch))
        self._add_governance_section(enriched.get('governance') or {})
        self.elements.append(Spacer(1, 0.14 * inch))
        self._add_qualitative_section(enriched.get('qualitative') or {})
        self.elements.append(PageBreak())
        self._page_title("DONNÉES ENRICHIES (suite)")
        self._add_traceability_section(enriched.get('traceability') or {})

    def _enriched_table(self, rows, col_widths):
        table = Table(rows, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.LIGHT_BG),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, self.LIGHT_BG2]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        return table

    def _th(self, text, align=TA_LEFT):
        return self._table_cell(text, bold=True, color_hex=self.HEX['primary'], size=8.5, align=align)

    def _add_portfolio_section(self, portfolio, indicators):
        self.elements.append(Paragraph("Portefeuille Crédit par Secteur", self.styles['SubHeading']))
        if not portfolio:
            self.elements.append(Paragraph(
                "<i>Aucune donnée de portefeuille sectoriel disponible dans le fichier transmis.</i>",
                self.styles['Small']))
            return

        rows = [[self._th('Secteur'), self._th('Montant (MDH)', TA_RIGHT), self._th('% Portefeuille', TA_CENTER),
                 self._th('NPL (%)', TA_CENTER), self._th('Provision (MDH)', TA_RIGHT)]]
        for sector, d in sorted(portfolio.items(), key=lambda kv: (kv[1].get('amount') or 0), reverse=True):
            rows.append([
                self._table_cell(sector, size=8.5),
                self._table_cell(self._safe_money_m(d.get('amount')), size=8.5, align=TA_RIGHT),
                self._table_cell(self._safe_format(d.get('pct'), 1, '%'), size=8.5, align=TA_CENTER),
                self._table_cell(self._safe_format(d.get('npl'), 1, '%'), size=8.5, align=TA_CENTER),
                self._table_cell(self._safe_money_m(d.get('provision')), size=8.5, align=TA_RIGHT),
            ])
        self.elements.append(self._enriched_table(
            rows, [1.8 * inch, 1.3 * inch, 1.1 * inch, 0.9 * inch, 1.3 * inch]))

        conc = indicators.get('sector_concentration') or {}
        top5, top10, avg_npl = conc.get('top5_pct'), conc.get('top10_pct'), indicators.get('avg_npl')
        note_parts = []
        if top5 is not None:
            note_parts.append(f"Concentration top 5 secteurs : {top5:.1f}% du portefeuille")
        if top10 is not None:
            note_parts.append(f"top 10 : {top10:.1f}%")
        if avg_npl is not None:
            note_parts.append(f"NPL moyen (non pondéré) : {avg_npl:.2f}%")
        if note_parts:
            self.elements.append(Spacer(1, 0.06 * inch))
            self.elements.append(self._info_box(" ; ".join(note_parts) + "."))

    def _add_governance_section(self, governance):
        self.elements.append(Paragraph("Actionnariat & Management", self.styles['SubHeading']))
        shareholders = governance.get('shareholders') or []
        management = governance.get('management') or []

        if shareholders:
            rows = [[self._th('Actionnaire'), self._th('% Détention', TA_CENTER),
                     self._th('Montant (MDH)', TA_RIGHT), self._th('Nature'), self._th('Depuis', TA_CENTER)]]
            for s in shareholders:
                rows.append([
                    self._table_cell(s.get('name', ''), size=8.5),
                    self._table_cell(self._safe_format(s.get('pct'), 1, '%'), size=8.5, align=TA_CENTER),
                    self._table_cell(self._safe_money_m(s.get('amount')), size=8.5, align=TA_RIGHT),
                    self._table_cell(s.get('nature', ''), size=8.5),
                    self._table_cell(s.get('since', ''), size=8.5, align=TA_CENTER),
                ])
            self.elements.append(self._enriched_table(
                rows, [2.2 * inch, 1.0 * inch, 1.3 * inch, 1.3 * inch, 0.7 * inch]))
        else:
            self.elements.append(Paragraph("<i>Aucune donnée d'actionnariat disponible.</i>", self.styles['Small']))

        self.elements.append(Spacer(1, 0.1 * inch))
        if management:
            rows = [[self._th('Poste'), self._th('Nom'), self._th('Expérience', TA_CENTER),
                     self._th('Depuis', TA_CENTER)]]
            for m in management:
                rows.append([
                    self._table_cell(m.get('post', ''), size=8.5),
                    self._table_cell(m.get('name', ''), size=8.5),
                    self._table_cell(self._safe_format(m.get('experience'), 0, ' ans'), size=8.5, align=TA_CENTER),
                    self._table_cell(m.get('since', ''), size=8.5, align=TA_CENTER),
                ])
            self.elements.append(self._enriched_table(rows, [2.0 * inch, 2.0 * inch, 1.2 * inch, 1.3 * inch]))
        else:
            self.elements.append(Paragraph("<i>Aucune donnée de management disponible.</i>", self.styles['Small']))

    def _add_qualitative_section(self, qualitative):
        self.elements.append(Paragraph("Données Qualitatives", self.styles['SubHeading']))
        if not qualitative:
            self.elements.append(Paragraph("<i>Aucune donnée qualitative disponible.</i>", self.styles['Small']))
            return
        for label, value in qualitative.items():
            self.elements.append(Paragraph(f"<b>{label}</b> : {value}", self.styles['Body']))
            self.elements.append(Spacer(1, 0.04 * inch))

    def _add_traceability_section(self, traceability):
        self.elements.append(Paragraph("Traçabilité des Données", self.styles['SubHeading']))
        if not traceability:
            self.elements.append(Paragraph("<i>Aucune donnée de traçabilité disponible.</i>", self.styles['Small']))
            return
        rows = [[self._th('Donnée'), self._th('Source'), self._th('Page', TA_CENTER),
                 self._th('Vérifiée', TA_CENTER)]]
        for data_label, d in traceability.items():
            rows.append([
                self._table_cell(data_label, size=8.5),
                self._table_cell(d.get('source', ''), size=8.5),
                self._table_cell(str(d.get('page', '')), size=8.5, align=TA_CENTER),
                self._table_cell(d.get('verified', ''), size=8.5, align=TA_CENTER),
            ])
        self.elements.append(self._enriched_table(rows, [2.0 * inch, 3.0 * inch, 0.7 * inch, 0.9 * inch]))


def generate_enriched_pdf_report(results):
    """Fonction wrapper pour générer le PDF de notation bancaire enrichie
    (template 8 onglets). Même mécanique que `generate_pdf_report()`
    (nommage de fichier, dossier de sortie), mais utilise
    `EnrichedBankingReportGenerator` pour inclure la page « Données
    Enrichies » (portefeuille, actionnariat, management, qualitatif,
    traçabilité)."""
    os.makedirs('uploads/reports', exist_ok=True)
    safe_company = secure_filename(results['company_name']) or 'Banque'
    filename = f"Note_Credit_Enrichie_{safe_company}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join('uploads/reports', filename)

    try:
        generator = EnrichedBankingReportGenerator(results, output_path)
        generator.generate()
        return output_path, filename
    except Exception as e:
        print(f"Erreur génération PDF enrichi: {str(e)}")
        raise