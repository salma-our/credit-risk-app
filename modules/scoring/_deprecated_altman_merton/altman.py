# modules/scoring/altman.py
import numpy as np

class AltmanZModel:
    """Modèle Z-Altman classique (1968)"""
    
    def __init__(self):
        # Coefficients Altman
        self.coefficients = {
            'X1': 1.2,
            'X2': 1.4,
            'X3': 3.3,
            'X4': 0.6,
            'X5': 1.0
        }
    
    def predict(self, ratios, financials):
        """
        Calculer Z-Score Altman
        Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5
        """
        try:
            # Extraire composantes
            total_assets = financials.get('actifs_totaux', 500000000)
            
            # X1: Working Capital / Total Assets
            current_assets = financials.get('actifs_courants', 150000000)
            current_liabilities = financials.get('passifs_courants', 100000000)
            working_capital = current_assets - current_liabilities
            X1 = working_capital / total_assets if total_assets > 0 else 0
            
            # X2: Retained Earnings / Total Assets (approximation)
            # On va utiliser 20% des équités comme RE
            X2 = 0.20
            
            # X3: EBIT / Total Assets
            ebit = financials.get('ebit', 80000000)
            X3 = ebit / total_assets if total_assets > 0 else 0
            
            # X4: Market Value Equity / Book Value Debt
            equity = financials.get('capitaux_propres', 300000000)
            debt = financials.get('dettes_totales', 200000000)
            X4 = equity / debt if debt > 0 else 0
            
            # X5: Sales / Total Assets
            revenue = financials.get('revenus', 800000000)
            X5 = revenue / total_assets if total_assets > 0 else 0
            
            # Calculer Z-Score
            z_score = (
                self.coefficients['X1'] * X1 +
                self.coefficients['X2'] * X2 +
                self.coefficients['X3'] * X3 +
                self.coefficients['X4'] * X4 +
                self.coefficients['X5'] * X5
            )
            
            # Déterminer zone
            if z_score > 2.99:
                zone = "Safe Zone"
                pd = 0.02  # 2%
            elif z_score > 1.81:
                zone = "Gray Zone"
                pd = 0.10  # 10%
            else:
                zone = "Distress Zone"
                pd = 0.50  # 50%
            
            # Convertir en score 0-100
            score = max(0, min(100, int((1 - pd) * 100)))
            
            # Interprétation
            if z_score > 2.99:
                interpretation = "Très faible risque (Safe Zone)"
            elif z_score > 1.81:
                interpretation = "Risque modéré (Gray Zone)"
            else:
                interpretation = "Risque très élevé (Distress Zone)"
            
            return {
                'z_score': float(z_score),
                'zone': zone,
                'pd': float(pd),
                'score': score,
                'interpretation': interpretation
            }
        
        except Exception as e:
            print(f"Erreur Altman: {str(e)}")
            return {
                'z_score': 0,
                'zone': 'Unknown',
                'pd': 0.5,
                'score': 50,
                'interpretation': "Erreur calcul"
            }