import sys
import requests

# La console Windows par défaut (cp1252) plante sur les emojis ci-dessous
# sans ce reconfigure -- indépendant du bug /analyze lui-même.
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = 'http://localhost:5000'

# /analyze attend sector/company_name en champs de formulaire multipart
# (request.form côté Flask), jamais en query string (request.args) --
# c'était le bug : sector passé via '?sector=banking' dans l'URL et
# company_name absent, donc request.form.get(...) renvoyait None pour les
# deux et déclenchait le 400 "Données incomplètes".
CASES = [
    ('banking', 'banking_test.xlsx', 2.84),
    ('banking', 'templates_excel/banking_template_EXEMPLE.xlsx', 3.53),
    ('industry', 'templates_excel/industry_template_EXEMPLE.xlsx', 3.77),
    ('insurance', 'templates_excel/insurance_template_EXEMPLE.xlsx', 3.52),
]

all_ok = True
for sector, filepath, expected_score in CASES:
    print(f"Testing {filepath} (sector={sector})...")
    try:
        with open(filepath, 'rb') as f:
            files = {'file': f}
            data = {'sector': sector, 'company_name': f'Test {sector.capitalize()}'}
            response = requests.post(f'{BASE_URL}/analyze', files=files, data=data)

        print(f"  Status Code: {response.status_code}")
        if response.status_code == 200:
            body = response.json()
            score = body['results']['final_rating']['final_score']
            match = abs(score - expected_score) < 0.01
            all_ok = all_ok and match
            status = "OK" if match else f"MISMATCH (expected {expected_score})"
            print(f"  Score: {score}/5 [{status}]")
        else:
            all_ok = False
            print(f"  Error: {response.json()}")
    except Exception as e:
        all_ok = False
        print(f"  Exception: {e}")
    print()

print("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED")
