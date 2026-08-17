/* Gouvernance qualitative : sliders générés dynamiquement selon le secteur
   sélectionné (les critères et leurs clés diffèrent par secteur). */
window.App = window.App || {};

App.governance = (function () {
  const { qs, on, escapeHtml } = App.utils;

  // Reflète modules/sectors.py -> SectorConfig.SECTORS[secteur]
  // ['governance_weights'] / ['governance_weights_labels'] -- à tenir
  // synchronisé si sectors.py change (clé + note par défaut). Un secteur
  // absent de cette config (valeur `sectorSelect` vide) masque la section.
  const GOVERNANCE_CONFIG = {
    banking: [
      { key: 'type_actionariat', label: "Type d'actionnariat", hint: "Stabilité et qualité des actionnaires de référence.", default: 4 },
      { key: 'risque_conflit', label: "Risque de conflit d'intérêts", hint: "Transactions apparentées, gouvernance des décisions sensibles.", default: 4 },
      { key: 'expertise_management', label: "Expertise du management", hint: "Expérience et compétence de l'équipe dirigeante.", default: 4 },
      { key: 'clarte_strategie', label: "Clarté de la stratégie", hint: "Lisibilité et cohérence de la stratégie affichée.", default: 4 },
    ],
    industry: [
      { key: 'management_quality', label: "Qualité du management", hint: "Expérience et compétence de l'équipe dirigeante.", default: 3 },
      { key: 'strategic_clarity', label: "Clarté stratégique", hint: "Lisibilité et cohérence de la stratégie affichée.", default: 3 },
    ],
    insurance: [
      { key: 'board_composition', label: "Composition du conseil d'administration", hint: "Indépendance, diversité et expertise des administrateurs.", default: 3 },
      { key: 'risk_management', label: "Gestion des risques", hint: "Maturité du dispositif de gestion des risques.", default: 3 },
    ],
  };

  function fieldId(sector, key) {
    return `gov_${sector}_${key}`;
  }

  function renderFields(sector) {
    const section = qs('#governanceSection');
    const container = qs('#governanceFields');
    if (!section || !container) return;

    const fields = GOVERNANCE_CONFIG[sector];
    if (!fields) {
      container.innerHTML = '';
      section.hidden = true;
      section.open = false;
      return;
    }

    section.hidden = false;
    container.innerHTML = fields.map((f) => {
      const id = fieldId(sector, f.key);
      return `
        <div class="governance-field">
          <label for="${id}">
            ${escapeHtml(f.label)}
            <span class="governance-value" data-value-for="${id}">${f.default}</span>/5
          </label>
          <input type="range" id="${id}" min="1" max="5" value="${f.default}" class="governance-slider">
          <small class="governance-hint">${escapeHtml(f.hint)}</small>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.governance-slider').forEach((slider) => {
      // `touched` distingue "valeur par défaut jamais consultée" de "analyste
      // a bougé le curseur (même revenu à la valeur de départ)" -- sans ce
      // suivi, envoyer systématiquement la valeur affichée (= le défaut tant
      // que rien n'est touché) marquerait CHAQUE analyse comme personnalisée
      // (is_override=true) et ferait disparaître le badge "valeur par défaut"
      // même quand l'analyste n'a jamais ouvert la section.
      slider.dataset.touched = 'false';
      on(slider, 'input', () => {
        slider.dataset.touched = 'true';
        const badge = container.querySelector(`[data-value-for="${slider.id}"]`);
        if (badge) badge.textContent = slider.value;
      });
    });
  }

  // Retourne {clé_gouvernance: note} pour le secteur courant (uniquement les
  // curseurs réellement manipulés par l'analyste, cf. `touched` ci-dessus),
  // au format attendu par RatingEngine._weighted_block() (cf. app.py
  // governance_overrides). Retourne null si le secteur n'a pas de config
  // gouvernance ; {} si le secteur en a une mais rien n'a été touché.
  function buildOverrides(sector) {
    const fields = GOVERNANCE_CONFIG[sector];
    if (!fields) return null;
    const overrides = {};
    fields.forEach((f) => {
      const slider = qs('#' + fieldId(sector, f.key));
      if (slider && slider.dataset.touched === 'true') {
        overrides[f.key] = parseFloat(slider.value);
      }
    });
    return overrides;
  }

  function init() {
    const sectorSelect = qs('#sectorSelect');
    if (!sectorSelect) return;
    on(sectorSelect, 'change', () => renderFields(sectorSelect.value));
    renderFields(sectorSelect.value);
  }

  return { init, renderFields, buildOverrides };
})();
