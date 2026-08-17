# modules/scoring/logistic.py
import numpy as np

class LogisticRegressionModel:
    """Modèle de Régression Logistique pour scoring crédit"""
    
    def __init__(self):
        # Poids heuristiques
        self.weights = {
            'current_ratio': 0.8,
            'quick_ratio': 0.6,
            'debt_to_equity': -0.5,
            'roe': 1.2,
            'profit_margin': 0.6,
            'asset_turnover': 0.4,
            'interest_coverage': 0.7,
        }
    
    def safe_float(self, value, default=0.0):
        """Convertir valeur en float de manière sûre"""
        try:
            if value is None:
                return default
            val = float(value)
            # Vérifier si finite
            if np.isnan(val) or np.isinf(val):
                return default
            return val
        except:
            return default
    
    def predict(self, ratios):
        """
        Prédire probabilité de défaut
        Entrée: dict des ratios
        Sortie: {pd, score, interpretation}
        """
        try:
            # Extraire les ratios principaux (SAFE)
            cr = self.safe_float(ratios.get('current_ratio'), 1.0)
            de = self.safe_float(ratios.get('debt_to_equity'), 0.5)
            roe = self.safe_float(ratios.get('roe'), 0.1)
            pm = self.safe_float(ratios.get('profit_margin'), 0.05)
            at = self.safe_float(ratios.get('asset_turnover'), 1.0)
            ic = self.safe_float(ratios.get('interest_coverage'), 5.0)
            da = self.safe_float(ratios.get('debt_to_assets'), 0.4)
            
            # Calculer score brut avec heuristique simple
            raw_score = 0.0
            
            # Liquidité (plus haut = mieux)
            raw_score += self.weights['current_ratio'] * min(max(cr, 0), 3.0)
            
            # Solvabilité (plus bas = mieux pour debt)
            raw_score += self.weights['debt_to_equity'] * (1.0 / (1.0 + max(de, 0.1)))
            raw_score += self.weights['interest_coverage'] * min(max(ic, 0) / 5.0, 2.0)
            
            # Profitabilité (plus haut = mieux)
            raw_score += self.weights['roe'] * min(max(roe, 0) * 10, 2.0)
            raw_score += self.weights['profit_margin'] * min(max(pm, 0) * 20, 2.0)
            
            # Efficacité (plus haut = mieux)
            raw_score += self.weights['asset_turnover'] * min(max(at, 0), 2.5)
            
            # Convertir raw_score en probabilité (0-1)
            # Sigmoid: 1 / (1 + exp(-x))
            try:
                pd = 1.0 / (1.0 + np.exp(-float(raw_score)))
            except:
                pd = 0.05
            
            # Assurer que pd est entre 0 et 1
            pd = max(0.0, min(1.0, float(pd)))
            
            # Convertir en score 0-100
            score = int(round((1.0 - pd) * 100))
            score = max(0, min(100, score))
            
            # Interprétation
            if score >= 80:
                interpretation = "Très faible risque"
            elif score >= 70:
                interpretation = "Faible risque"
            elif score >= 60:
                interpretation = "Risque modéré"
            elif score >= 50:
                interpretation = "Risque élevé"
            else:
                interpretation = "Très haut risque"
            
            print(f"Logistic: PD={pd:.4f}, Score={score}")
            
            return {
                'pd': float(pd),
                'score': score,
                'interpretation': interpretation
            }
        
        except Exception as e:
            print(f"Erreur Logistic: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'pd': 0.05,
                'score': 95,
                'interpretation': "Résultat par défaut"
            }