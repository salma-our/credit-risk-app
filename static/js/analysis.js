/* Appel API, rendu des résultats, modal graphique détaillé. */
window.App = window.App || {};

App.analysis = (function () {
  const { qs, qsa, formatMDH, formatUnit, escapeHtml, on } = App.utils;

  let currentCharts = [];

  // Transparence données manquantes : `entry.is_override === false` signale un
  // facteur Secteur/Gouvernance noté avec la valeur de référence par défaut du
  // secteur (pas une évaluation qualitative propre à ce dossier) — cf.
  // RatingEngine._weighted_block(). `is_override` vaut `null` pour un facteur
  // du bloc Ratios Financiers (toujours calculé depuis le dossier réel) : pas
  // de badge dans ce cas, uniquement `=== false` déclenche l'affichage.
  function estimeBadge(title) {
    return `<span class="badge-estime" title="${escapeHtml(title)}">Valeur par défaut secteur</span>`;
  }

  function renderFactorList(el, entries) {
    el.innerHTML = '';
    if (!entries || entries.length === 0) {
      el.innerHTML = '<li class="text-muted">Aucun facteur disponible.</li>';
      return;
    }
    entries.forEach((entry) => {
      const li = document.createElement('li');
      const badge = entry.is_override === false
        ? estimeBadge('Valeur de référence par défaut du secteur, non personnalisée pour ce dossier.')
        : '';
      li.innerHTML = `<span class="factor-label">${escapeHtml(entry.label)}</span> — ${escapeHtml(entry.commentaire)}${badge}`;
      el.appendChild(li);
    });
  }

  // `sectorRatiosProvenance` (results.sector_ratios_provenance) enveloppe
  // chaque ratio sectoriel avec sa provenance (réel / calculé / proxy /
  // indisponible, cf. modules/data_provenance.py) — un KPI dont le ratio
  // sous-jacent est de type 'proxy' (approximation faute de donnée réelle,
  // ex: PNB estimé via Revenus) est marqué "Estimé" plutôt qu'affiché comme
  // une valeur réelle sans qualification.
  function renderKpi(kpi, sectorRatiosProvenance) {
    const grid = qs('#kpiGrid');
    grid.innerHTML = '';
    const provenance = sectorRatiosProvenance || {};
    Object.entries(kpi || {}).forEach(([key, item]) => {
      const prov = provenance[key];
      const isProxy = !!(prov && typeof prov === 'object' && prov.type === 'proxy');
      const card = document.createElement('div');
      card.className = 'kpi-card' + (isProxy ? ' kpi-card--estimated' : '');
      const badge = isProxy
        ? `<span class="badge-estime" title="Approximation calculée en l'absence de la donnée réelle correspondante.">Estimé</span>`
        : '';
      card.innerHTML = `
        <div class="kpi-card__label">${escapeHtml(item.label)}</div>
        <div class="kpi-card__value">${item.value === null || item.value === undefined ? 'N/A' : formatUnit(item.value, item.unit)}</div>
        ${badge}
      `;
      grid.appendChild(card);
    });
  }

  // Bandeau "Fiabilité des données" : X/Y ratios financiers du dossier
  // réellement renseignés (financial_result.coverage, cf. RatingEngine.
  // calculate_financial_score) -- masqué si l'info est absente (dossier
  // traité par une version antérieure de l'API, cf. compatibilité).
  function renderCoverage(financialResult) {
    const box = qs('#coverageInfo');
    if (!box) return;
    const coverage = (financialResult || {}).coverage;
    const parts = typeof coverage === 'string' ? coverage.split('/').map(Number) : null;
    if (!parts || parts.length !== 2 || !parts[1]) {
      box.hidden = true;
      return;
    }
    const [available, total] = parts;
    const pct = Math.round((available / total) * 100);

    let colorVar = '--success';
    if (pct < 50) colorVar = '--primary-red';
    else if (pct < 80) colorVar = '--primary-orange';

    qs('#coverageLabel').textContent =
      `Fiabilité des données : ${available}/${total} ratios financiers renseignés dans le dossier`;
    const fill = qs('#coverageBarFill');
    fill.style.width = `${pct}%`;
    fill.style.background = `var(${colorVar})`;
    qs('#coveragePercent').textContent = `${pct}%`;
    box.hidden = false;
  }

  function renderCharts(charts) {
    currentCharts = charts || [];
    const grid = qs('#chartGrid');
    const section = qs('#chartsSection');
    grid.innerHTML = '';
    if (!currentCharts.length) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    currentCharts.forEach((chart, idx) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chart-thumb';
      btn.setAttribute('aria-haspopup', 'dialog');
      btn.innerHTML = `
        <img src="${chart.image}" alt="${escapeHtml(chart.title)}" loading="lazy">
        <div class="chart-thumb__title">${escapeHtml(chart.title)}</div>
      `;
      on(btn, 'click', () => openChartModal(idx));
      grid.appendChild(btn);
    });
  }

  function openChartModal(idx) {
    const chart = currentCharts[idx];
    if (!chart) return;
    qs('#modalNumber').textContent = `Graphique ${idx + 1}/${currentCharts.length}`;
    qs('#modalTitle').textContent = chart.title;
    qs('#modalImage').src = chart.image;
    qs('#modalImage').alt = chart.title;
    const narrativeEl = qs('#modalNarrative');
    narrativeEl.textContent = chart.narrative || '';
    narrativeEl.hidden = !chart.narrative;
    const overlay = qs('#chartModal');
    overlay.hidden = false;
    qs('#modalCloseBtn').focus();
  }

  function closeChartModal() {
    qs('#chartModal').hidden = true;
  }

  function renderResults(results) {
    qs('#resultCompanyName').textContent = results.company_name || '--';
    qs('#resultDate').textContent = new Date().toLocaleDateString('fr-FR');
    qs('#resultSectorName').textContent = results.sector_name || '--';

    const fr = results.final_rating || {};
    qs('#finalScoreValue').innerHTML = `${formatUnit(fr.final_score, '', 2)} <span>/ 5.0</span>`;
    qs('#finalCategory').textContent = `Catégorie ${fr.category ?? '--'} — ${fr.rating || '--'}`;

    renderCoverage(results.financial_result);

    const es = results.executive_summary || {};
    const positifs = (results.risk_drivers || {}).positifs || es.positive_factors_raw || [];
    const negatifs = (results.risk_drivers || {}).negatifs || es.negative_factors_raw || [];
    renderFactorList(qs('#positiveFactors'), positifs);
    renderFactorList(qs('#negativeFactors'), negatifs);

    renderKpi(es.kpi, results.sector_ratios_provenance);

    const fin = results.financial_summary || {};
    qs('#totalAssets').textContent = formatMDH(fin.total_assets);
    qs('#totalDebt').textContent = formatMDH(fin.total_debt);
    qs('#equity').textContent = formatMDH(fin.equity);
    qs('#revenue').textContent = formatMDH(fin.revenue);
    qs('#netIncome').textContent = formatMDH(fin.net_income);

    const pdfLink = qs('#pdfLink');
    if (results.pdf_url) {
      pdfLink.href = results.pdf_url;
      pdfLink.hidden = false;
    } else {
      pdfLink.hidden = true;
    }

    renderCharts(results.charts);
  }

  function init() {
    qsa('[data-close-modal]').forEach((btn) => on(btn, 'click', closeChartModal));
    on(qs('#chartModal'), 'click', (e) => {
      if (e.target.id === 'chartModal') closeChartModal();
    });
    on(document, 'keydown', (e) => {
      if (e.key === 'Escape') closeChartModal();
    });
    on(qs('#viewAllChartsBtn'), 'click', () => {
      const section = qs('#chartsSection');
      if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  return { init, renderResults };
})();
