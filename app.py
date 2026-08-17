# app.py - VERSION AVEC PDF

from flask import Flask, render_template, request, jsonify, send_file
import os
import json
import base64
import sqlite3
import uuid
from io import BytesIO
from datetime import datetime
from werkzeug.utils import secure_filename

# Importer vos modules
from modules.data_processing import extract_financial_history
from modules.ratios import calculate_ratios, calculate_sector_ratios, calculate_ratios_series, calculate_sector_ratios_series
from modules.rating_engine import build_rating
from modules.risk_drivers import identify_risk_drivers
from modules.narrative_generator import NarrativeGenerator
from modules.charts_generator import AnalyticalChartsGenerator
from modules.sectors import SectorConfig
from modules.reports import generate_pdf_report, generate_enriched_pdf_report
from modules.banking_enriched_processor import (
    BankingDataProcessor, map_to_sector_ratios, map_to_sector_ratio_series,
)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/files'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Historique des analyses (SQLite local, pas de sync multi-utilisateurs).
DB_PATH = 'analysis_history.db'


def init_database():
    """Crée la table `analyses` si absente. Appelée au chargement du module
    (pas seulement sous `if __name__ == '__main__'`) pour que la table
    existe aussi quand l'app est servie via un serveur WSGI externe
    (gunicorn, etc.) plutôt que `python app.py`."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            sector TEXT NOT NULL,
            sub_sector TEXT,
            score REAL NOT NULL,
            category INTEGER NOT NULL,
            rating TEXT NOT NULL,
            analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            results_json TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def save_analysis_to_history(company_name, sector, sub_sector, final_rating, results):
    """Sauvegarde une analyse réussie dans l'historique. ID généré via uuid4
    (pas de collision possible, contrairement à un ID `nom_horodatage` -- 2
    analyses soumises la même seconde pour la même entreprise ne s'écrasent
    pas)."""
    analysis_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO analyses (id, company_name, sector, sub_sector, score, category, rating, results_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        analysis_id, company_name, sector, sub_sector,
        final_rating['final_score'], final_rating['category'], final_rating['rating'],
        json.dumps(results, default=str),
    ))
    conn.commit()
    conn.close()
    print(f"Analyse sauvegardée dans l'historique : {analysis_id}")
    return analysis_id


init_database()

ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

# Palette web (orange/rouge) utilisée uniquement pour les graphiques affichés
# dans l'interface — indépendante de la palette bleue du PDF (modules/reports.py),
# qui reste inchangée.
WEB_CHART_HEX = {
    'primary': '#f39c12',
    'secondary': '#e74c3c',
    'accent': '#e67e22',
    'success': '#27ae60',
    'warning': '#f39c12',
    'danger': '#e74c3c',
    'neutral': '#7f8c8d',
    'light_bg': '#ecf0f1',
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def build_web_charts(sector, sector_ratio_series_provenance, ratio_series_provenance,
                      financial_series, years):
    """Génère les graphiques analytiques (mêmes données que le PDF) encodés
    en PNG base64 pour affichage direct dans le navigateur (page Résultats +
    modal détail), avec la palette orange/rouge de l'interface web."""
    sector_cfg = SectorConfig.get_sector_config(sector)
    benchmarks = sector_cfg.get('benchmarks', {})
    charts_gen = AnalyticalChartsGenerator(WEB_CHART_HEX, sector)
    raw_charts = charts_gen.generate_all_charts(
        sector_ratio_series_provenance, ratio_series_provenance, financial_series, years, benchmarks)

    web_charts = []
    for c in raw_charts:
        encoded = base64.b64encode(c['chart'].getvalue()).decode('ascii')
        web_charts.append({
            'title': c['title'],
            'narrative': c['narrative'],
            'image': f'data:image/png;base64,{encoded}',
        })
    return web_charts

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """Route principale pour analyse crédit"""
    try:
        # 1. Récupérer données du formulaire
        sector = request.form.get('sector')
        sub_sector = request.form.get('sub_sector') or None
        company_name = request.form.get('company_name')
        file = request.files.get('file')

        if not all([sector, company_name, file]):
            # Diagnostic explicite : cette route attend sector/company_name/file
            # en champs multipart (request.form / request.files), PAS en query
            # string (request.args) — une requête qui met 'sector' dans l'URL
            # (?sector=banking) ou omet 'company_name' finit ici avec un
            # message générique ; ce log montre immédiatement laquelle des 3
            # valeurs manque, plutôt que de devoir deviner depuis le 400 seul.
            print(
                "Analyse rejetée (Données incomplètes) — "
                f"sector={sector!r} company_name={company_name!r} "
                f"file={file.filename if file else None!r} | "
                f"form_keys={list(request.form.keys())} "
                f"args_keys={list(request.args.keys())} "
                f"files_keys={list(request.files.keys())}"
            )
            return jsonify({'success': False, 'error': 'Données incomplètes'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Fichier doit être .xlsx'}), 400
        
        print(f"Analyse: {company_name}, Secteur: {sector}")
        
        # 2. Traiter Excel : historique complet (1 à 5 exercices). `financials`
        # (l'exercice courant) garde exactement le même contrat qu'avant pour
        # ne rien casser en aval (ratios.py, reports.py).
        try:
            history = extract_financial_history(file, sector)
        except Exception as e:
            print(f"Erreur data_processing: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 400

        financials = history['current']

        print(f"Financials extraits: {list(financials.keys())}")
        if history['warnings']:
            print(f"Avertissements data_processing: {history['warnings']}")

        # 3. Calculer les ratios génériques + les ratios spécifiques au secteur
        # (sur l'exercice courant, comme avant) et sur toute la série
        # historique (pour les graphiques de tendance / risk drivers).
        ratios = calculate_ratios(financials)
        sector_ratios = calculate_sector_ratios(financials, sector)
        ratio_series = calculate_ratios_series(history['series'], history['years'])
        sector_ratio_series = calculate_sector_ratios_series(history['series'], history['years'], sector)

        # Mêmes séries, mais avec traçabilité (donnée réelle / calculée /
        # proxy / indisponible) — consommées uniquement par les graphiques
        # analytiques (modules/charts_generator.py) ; le scoring ci-dessous
        # continue d'utiliser les séries "brutes" (float) ci-dessus, comme
        # avant (aucun changement de comportement pour build_rating/risk_drivers).
        ratio_series_provenance = calculate_ratios_series(history['series'], history['years'],
                                                            include_provenance=True)
        sector_ratio_series_provenance = calculate_sector_ratios_series(
            history['series'], history['years'], sector, include_provenance=True)
        # Instantané "exercice courant" avec provenance : utilisé par la
        # Synthèse Exécutive (KPI) pour ne jamais afficher un proxy comme un
        # chiffre réel sans qualification (cf. narrative_generator.py).
        sector_ratios_provenance = calculate_sector_ratios(financials, sector, include_provenance=True)

        print(f"Ratios calculés: {len(ratios)} génériques, {len(sector_ratios)} sectoriels")

        # 3bis. Overrides qualitatifs optionnels (secteur / gouvernance), transmis
        # en JSON par le formulaire (ex: {"management_quality": 4}). Si absents
        # ou invalides, RatingEngine retombe sur les notes de référence du
        # secteur (defaults), documentées comme telles côté UI.
        def parse_overrides(field_name):
            raw = request.form.get(field_name)
            if not raw:
                return None
            try:
                data = json.loads(raw)
                return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else None
            except (ValueError, TypeError):
                return None

        governance_overrides = parse_overrides('governance_overrides')
        sector_overrides = parse_overrides('sector_overrides')

        # 4. Notation pondérée /5 (Secteur 20% + Ratios Financiers 60% + Gouvernance 20%)
        try:
            rating = build_rating(
                sector, ratios, sector_ratios, sub_sector=sub_sector,
                sector_overrides=sector_overrides, governance_overrides=governance_overrides,
            )
        except Exception as e:
            print(f"Erreur notation: {str(e)}")
            return jsonify({'success': False, 'error': f'Erreur notation: {str(e)}'}), 400

        final_rating = rating['final_rating']

        # 4bis. Risk Drivers : facteurs qui expliquent le plus la note finale,
        # à partir des `details` déjà calculés par build_rating() (pas de
        # recalcul de score). `sector_ratio_series` est utilisé pour la
        # détection de tendance car `financial_result` est construit à partir
        # des ratios sectoriels (cf. RatingEngine.calculate_financial_score
        # appelé avec `sector_ratios` dans build_rating()).
        risk_drivers = identify_risk_drivers(
            rating['sector_result'], rating['financial_result'], rating['governance_result'],
            ratio_series=sector_ratio_series, years=history['years'], top_n=4,
            ratios_cfg=rating['sector_config']['ratios'],
        )

        # 4ter. Synthèse Exécutive (KPI + facteurs en phrases) pour l'affichage web.
        executive_summary = NarrativeGenerator.generate_for_executive_summary(
            final_rating, risk_drivers, sector_ratios, financials, sector,
            sector_ratios_provenance=sector_ratios_provenance,
        )

        # 5. Assembler résultats
        results = {
            'company_name': company_name,
            'sector': sector,
            'sub_sector': sub_sector,
            'sector_name': rating['sector_config']['name'],
            'final_rating': final_rating,
            'sector_result': rating['sector_result'],
            'financial_result': rating['financial_result'],
            'governance_result': rating['governance_result'],
            'ratios': ratios,
            'sector_ratios': sector_ratios,
            'financials': financials,
            'years': history['years'],
            'ratio_series': ratio_series,
            'sector_ratio_series': sector_ratio_series,
            'ratio_series_provenance': ratio_series_provenance,
            'sector_ratio_series_provenance': sector_ratio_series_provenance,
            'sector_ratios_provenance': sector_ratios_provenance,
            'financial_series': history['series'],
            'risk_drivers': risk_drivers,
            'executive_summary': executive_summary,
            'shareholders': history.get('shareholders', []),
            'shareholders_count': len(history.get('shareholders') or []),
            'financial_summary': {
                'total_assets': financials.get('actifs_totaux'),
                'total_debt': financials.get('dettes'),
                'equity': financials.get('equity'),
                'revenue': financials.get('revenus'),
                'net_income': financials.get('resultat_net')
            }
        }

        # 5bis. Graphiques analytiques (PNG base64, palette web) pour la page Résultats.
        try:
            results['charts'] = build_web_charts(
                sector, sector_ratio_series_provenance, ratio_series_provenance,
                history['series'], history['years'],
            )
        except Exception as e:
            print(f"Erreur graphiques web: {str(e)}")
            results['charts'] = []

        # 6. Générer PDF
        try:
            pdf_path, pdf_filename = generate_pdf_report(results)
            results['pdf_url'] = f'/download-report/{pdf_filename}'
            print(f"PDF généré: {pdf_filename}")
        except Exception as e:
            print(f"Erreur PDF: {str(e)}")
            results['pdf_url'] = None

        # 7. Sauvegarder l'analyse dans l'historique (best-effort : une
        # erreur ici ne doit jamais faire échouer une analyse par ailleurs
        # réussie -- l'historique est un confort, pas une garantie).
        try:
            save_analysis_to_history(company_name, sector, sub_sector, final_rating, results)
        except Exception as e:
            print(f"Erreur sauvegarde historique: {str(e)}")

        return jsonify({
            'success': True,
            'results': results
        })
    
    except Exception as e:
        print(f"Erreur générale: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/analyze/banking-enriched', methods=['POST'])
def analyze_banking_enriched():
    """
    Analyse crédit bancaire à partir du template enrichi (8 onglets).

    Endpoint séparé de /analyze : lit BANKING_TEMPLATE_ENRICHI_V2.xlsx via
    BankingDataProcessor (modules/banking_enriched_processor.py), toujours
    secteur 'banking'. Le score final utilise la MÊME grille de notation
    (build_rating, 20/60/20) que /analyze — seule la source des ratios
    sectoriels change (mappée depuis le template enrichi via
    map_to_sector_ratios/map_to_sector_ratio_series, cf. ce module). Les
    données propres au template enrichi (portefeuille sectoriel,
    actionnariat, management, qualitatif, traçabilité) enrichissent
    uniquement la mise en page du PDF ; elles ne pèsent pas sur le score.

    Contrairement à /analyze (réponse JSON + lien de téléchargement), cet
    endpoint retourne directement le PDF généré.
    """
    company_name = request.form.get('company_name') or 'Banque'
    file = request.files.get('file')

    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Fichier requis'}), 400
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Fichier doit être .xlsx'}), 400

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(temp_path)

    try:
        # 1. Charger le template enrichi (8 onglets) — jamais d'exception
        # levée pour une ligne/colonne/onglet manquant isolé (cf.
        # BankingDataProcessor.load_all_sheets) : seul un fichier illisible
        # (mauvais chemin, fichier corrompu) échoue ici.
        try:
            processor = BankingDataProcessor(temp_path)
            enriched_data = processor.load_all_sheets()
        except Exception as e:
            print(f"Erreur lecture template enrichi: {e}")
            return jsonify({'success': False, 'error': f'Erreur lecture template enrichi : {e}'}), 400

        warnings = processor.get_warnings()
        if warnings:
            print(f"Avertissements chargement enrichi: {warnings}")

        financial_summary = processor.get_financial_summary()
        sector_ratios = map_to_sector_ratios(processor)
        sector_ratio_series = map_to_sector_ratio_series(processor)

        # 2. Notation : logique inchangée (build_rating), avec les ratios
        # sectoriels mappés depuis le template enrichi ci-dessus.
        try:
            rating = build_rating('banking', ratios={}, sector_ratios=sector_ratios)
        except Exception as e:
            print(f"Erreur notation: {e}")
            return jsonify({'success': False, 'error': f'Erreur notation: {e}'}), 400

        final_rating = rating['final_rating']

        risk_drivers = identify_risk_drivers(
            rating['sector_result'], rating['financial_result'], rating['governance_result'],
            ratio_series=sector_ratio_series, years=processor.years, top_n=4,
            ratios_cfg=rating['sector_config']['ratios'],
        )

        executive_summary = NarrativeGenerator.generate_for_executive_summary(
            final_rating, risk_drivers, sector_ratios, financial_summary, 'banking',
        )

        # 3. Assembler les résultats (même forme que /analyze) + bloc
        # `enriched` consommé uniquement par EnrichedBankingReportGenerator
        # pour la page « Données Enrichies » du PDF.
        results = {
            'company_name': company_name,
            'sector': 'banking',
            'sector_name': rating['sector_config']['name'],
            'final_rating': final_rating,
            'sector_result': rating['sector_result'],
            'financial_result': rating['financial_result'],
            'governance_result': rating['governance_result'],
            'ratios': {},
            'sector_ratios': sector_ratios,
            'financials': financial_summary,
            'years': processor.years,
            'sector_ratio_series': sector_ratio_series,
            'financial_series': {},
            'risk_drivers': risk_drivers,
            'executive_summary': executive_summary,
            'enriched': {
                'portfolio': processor.get_portfolio_summary(),
                'governance': processor.get_governance_summary(),
                'qualitative': enriched_data.get('qualitative', {}),
                'traceability': enriched_data.get('traceability', {}),
                'indicators': enriched_data.get('indicators', {}),
                'warnings': warnings,
            },
        }

        # 4. Générer le PDF enrichi
        try:
            pdf_path, pdf_filename = generate_enriched_pdf_report(results)
        except Exception as e:
            print(f"Erreur PDF enrichi: {e}")
            return jsonify({'success': False, 'error': f'Erreur génération PDF: {e}'}), 500

        return send_file(
            pdf_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=pdf_filename,
        )

    except Exception as e:
        print(f"Erreur générale /analyze/banking-enriched: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route('/analyses', methods=['GET'])
def list_analyses():
    """Liste toutes les analyses sauvegardées (colonnes légères, pas
    `results_json` — cf. get_analysis() pour le détail complet)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, company_name, sector, sub_sector, score, category, rating, analysis_date
            FROM analyses
            ORDER BY analysis_date DESC
        ''')
        analyses = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'analyses': analyses})
    except Exception as e:
        print(f"Erreur récupération historique: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/analyses/<analysis_id>', methods=['GET'])
def get_analysis(analysis_id):
    """Récupère les résultats complets d'une analyse sauvegardée -- même
    forme que la réponse de /analyze, pour être passée telle quelle à
    App.analysis.renderResults() côté client (rechargement à l'identique,
    sans relancer le calcul)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT results_json FROM analyses WHERE id = ?', (analysis_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify({'success': False, 'error': 'Analyse non trouvée'}), 404

        return jsonify({'success': True, 'results': json.loads(row['results_json'])})
    except Exception as e:
        print(f"Erreur récupération analyse: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/analyses/<analysis_id>', methods=['DELETE'])
def delete_analysis(analysis_id):
    """Supprime une analyse de l'historique."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM analyses WHERE id = ?', (analysis_id,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        if not deleted:
            return jsonify({'success': False, 'error': 'Analyse non trouvée'}), 404
        return jsonify({'success': True})
    except Exception as e:
        print(f"Erreur suppression analyse: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/analyses/<analysis_id>/export', methods=['GET'])
def export_analysis(analysis_id):
    """Télécharge une analyse sauvegardée en JSON (archivage)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT company_name, results_json FROM analyses WHERE id = ?', (analysis_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify({'success': False, 'error': 'Analyse non trouvée'}), 404

        company_name, results_json = row
        safe_name = secure_filename(company_name) or 'analyse'
        return send_file(
            BytesIO(results_json.encode('utf-8')),
            mimetype='application/json',
            as_attachment=True,
            download_name=f'{safe_name}_{analysis_id[:8]}.json',
        )
    except Exception as e:
        print(f"Erreur export analyse: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download-report/<filename>')
def download_report(filename):
    """Télécharger le rapport PDF"""
    try:
        import os
        from werkzeug.utils import secure_filename
        from flask import send_file
        
        # Sécuriser le nom du fichier
        safe_filename = secure_filename(filename)
        file_path = os.path.join('uploads/reports', safe_filename)
        
        print(f"Tentative de téléchargement: {file_path}")
        print(f"Fichier existe: {os.path.exists(file_path)}")
        
        if not os.path.exists(file_path):
            print(f"Fichier non trouvé: {file_path}")
            # Lister les fichiers disponibles
            if os.path.exists('uploads/reports'):
                files = os.listdir('uploads/reports')
                print(f"Fichiers disponibles: {files}")
            return jsonify({'error': f'Fichier non trouvé: {filename}'}), 404
        
        # Vérifier que c'est un PDF
        if not safe_filename.endswith('.pdf'):
            return jsonify({'error': 'Le fichier n\'est pas un PDF'}), 400
        
        return send_file(
            file_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=safe_filename
        )
    
    except Exception as e:
        print(f"Erreur téléchargement: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Erreur: {str(e)}'}), 500
@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/analyze') or request.path.startswith('/download-report'):
        return jsonify({'success': False, 'error': 'Ressource non trouvée'}), 404
    return render_template('error.html', code=404, message="Page non trouvée."), 404

@app.errorhandler(500)
def server_error(e):
    if request.path.startswith('/analyze') or request.path.startswith('/download-report'):
        return jsonify({'success': False, 'error': 'Erreur serveur'}), 500
    return render_template('error.html', code=500, message="Une erreur inattendue est survenue."), 500

if __name__ == '__main__':
    os.makedirs('uploads/files', exist_ok=True)
    os.makedirs('uploads/reports', exist_ok=True)
    app.run(debug=True, port=5000)