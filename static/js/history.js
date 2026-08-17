/* Historique des analyses : liste, rechargement, suppression, export. */
window.App = window.App || {};

App.history = (function () {
  const { qs, on, escapeHtml } = App.utils;

  const SECTOR_LABELS = { banking: 'Banque', industry: 'Industrie', insurance: 'Assurance' };

  // Couleur du badge de catégorie (indépendante de toute recommandation --
  // la recommandation/décision n'est plus affichée côté web, cf.
  // analysis.js/analysis.html) ; garder synchronisé si la grille de
  // catégories change (cf. rating_engine.py -> CATEGORIES).
  function categoryBadgeClass(category) {
    if (category <= 2) return 'badge-success';
    if (category === 3) return 'badge-warning';
    return 'badge-danger';
  }

  async function load() {
    const content = qs('#historyContent');
    content.innerHTML = '<p class="text-muted">Chargement de l\'historique...</p>';
    try {
      const response = await fetch('/analyses');
      const data = await response.json();
      if (!data.success) {
        content.innerHTML = `<div class="alert alert-danger">Erreur : ${escapeHtml(data.error || 'inconnue')}</div>`;
        return;
      }
      if (!data.analyses.length) {
        content.innerHTML = '<div class="history-empty">Aucune analyse enregistrée pour le moment.</div>';
        return;
      }
      renderTable(data.analyses);
    } catch (err) {
      content.innerHTML = `<div class="alert alert-danger">Erreur réseau : ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderTable(analyses) {
    const content = qs('#historyContent');
    const rows = analyses.map((a) => `
      <tr data-id="${escapeHtml(a.id)}">
        <td><strong>${escapeHtml(a.company_name)}</strong></td>
        <td>${escapeHtml(SECTOR_LABELS[a.sector] || a.sector)}</td>
        <td class="history-score">${Number(a.score).toFixed(2)}/5</td>
        <td><span class="badge ${categoryBadgeClass(a.category)}">Cat. ${a.category} — ${escapeHtml(a.rating)}</span></td>
        <td>${escapeHtml(new Date(a.analysis_date).toLocaleString('fr-FR'))}</td>
        <td class="history-actions">
          <button type="button" class="btn btn-primary" data-action="reload">Charger</button>
          <button type="button" class="btn btn-secondary" data-action="export">Exporter</button>
          <button type="button" class="btn btn-secondary" data-action="delete">Supprimer</button>
        </td>
      </tr>
    `).join('');

    content.innerHTML = `
      <div style="overflow-x:auto;">
        <table class="history-table">
          <thead>
            <tr><th>Entreprise</th><th>Secteur</th><th>Score</th><th>Catégorie</th><th>Date</th><th>Actions</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;

    content.querySelectorAll('tr[data-id]').forEach((tr) => {
      const id = tr.getAttribute('data-id');
      on(tr.querySelector('[data-action="reload"]'), 'click', () => reload(id));
      on(tr.querySelector('[data-action="export"]'), 'click', () => exportAnalysis(id));
      on(tr.querySelector('[data-action="delete"]'), 'click', () => remove(id));
    });
  }

  async function reload(id) {
    try {
      const response = await fetch(`/analyses/${id}`);
      const data = await response.json();
      if (!data.success) {
        alert('Erreur : ' + (data.error || 'analyse introuvable'));
        return;
      }
      App.analysis.renderResults(data.results);
      App.ui.showSection('resultsSection');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      alert('Erreur réseau : ' + err.message);
    }
  }

  function exportAnalysis(id) {
    window.location.href = `/analyses/${id}/export`;
  }

  async function remove(id) {
    if (!confirm('Supprimer définitivement cette analyse de l\'historique ?')) return;
    try {
      const response = await fetch(`/analyses/${id}`, { method: 'DELETE' });
      const data = await response.json();
      if (!data.success) {
        alert('Erreur : ' + (data.error || 'suppression impossible'));
        return;
      }
      load();
    } catch (err) {
      alert('Erreur réseau : ' + err.message);
    }
  }

  function init() {
    on(qs('#historyToggleBtn'), 'click', () => {
      App.ui.showSection('historySection');
      load();
    });
    on(qs('#historyCloseBtn'), 'click', () => App.ui.showSection('uploadSection'));
  }

  return { init };
})();
