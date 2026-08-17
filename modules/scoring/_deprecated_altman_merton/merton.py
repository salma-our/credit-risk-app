# modules/scoring/merton.py
import numpy as np
from scipy.stats import norm

class MertonModel:
    """Modèle Merton KMV - Distance to Default"""
    
    def __init__(self):
        self.risk_free_rate = 0.03  # 3%
        self.volatility = 0.15  # 15%
        self.time_horizon = 1.0  # 1 year
    
    def predict(self, ratios, financials):
        """
        Calculer Distance to Default
        Formule: DD = [ln(A/D) + (r - σ²/2)T] / (σ√T)
        """
        try:
            # Extraire valeurs
            asset_value = financials.get('actifs_totaux', 500000000)
            debt_value = financials.get('dettes_totales', 200000000)
            
            if debt_value <= 0 or asset_value <= 0:
                raise ValueError("Valeurs invalides")
            
            # Calculer Distance to Default
            # Formule Merton: DD = [ln(A/D) + (r - σ²/2)T] / (σ√T)
            
            ln_ratio = np.log(asset_value / debt_value)
            
            drift = (self.risk_free_rate - (self.volatility ** 2) / 2) * self.time_horizon
            
            volatility_term = self.volatility * np.sqrt(self.time_horizon)
            
            distance_to_default = (ln_ratio + drift) / volatility_term
            
            # Convertir DD en PD
            # PD = N(-DD) où N est la CDF normale
            pd = norm.cdf(-distance_to_default)
            
            # Convertir en score 0-100
            # Plus DD est grand, moins de risque
            score = max(0, min(100, 50 + 15 * distance_to_default))
            score = int(score)
            
            # Interprétation
            if distance_to_default > 3:
                interpretation = "Très faible risque (DD > 3)"
            elif distance_to_default > 2:
                interpretation = "Faible risque (DD > 2)"
            elif distance_to_default > 1:
                interpretation = "Risque modéré (DD > 1)"
            else:
                interpretation = "Risque élevé (DD < 1)"
            
            return {
                'distance_to_default': float(distance_to_default),
                'pd': float(pd),
                'score': score,
                'interpretation': interpretation
            }
        
        except Exception as e:
            print(f"Erreur Merton: {str(e)}")
            return {
                'distance_to_default': 0,
                'pd': 0.5,
                'score': 50,
                'interpretation': "Erreur calcul"
            }