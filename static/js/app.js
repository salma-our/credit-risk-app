/* Initialisation et orchestration des sections de la page. */
window.App = window.App || {};

App.ui = (function () {
  const { qs, on } = App.utils;

  function showSection(name) {
    ['uploadSection', 'loadingSection', 'resultsSection', 'errorSection', 'historySection'].forEach((id) => {
      const el = qs('#' + id);
      if (el) el.hidden = id !== name;
    });
  }

  function buildFormData(form) {
    const formData = new FormData(form);
    const file = App.upload.getSelectedFile();
    if (file) {
      formData.set('file', file);
    }
    // Gouvernance qualitative (optionnelle) : envoyée uniquement si le
    // secteur sélectionné a des champs de gouvernance rendus (cf.
    // governance.js -- null pour un secteur sans config, ex. sector vide).
    const sector = qs('#sectorSelect').value;
    const governanceOverrides = App.governance.buildOverrides(sector);
    if (governanceOverrides && Object.keys(governanceOverrides).length > 0) {
      formData.append('governance_overrides', JSON.stringify(governanceOverrides));
    }
    return formData;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const form = e.target;

    const file = App.upload.getSelectedFile();
    const fileError = App.upload.validateFile(file);
    if (fileError) {
      qs('#fileError').textContent = fileError;
      qs('#fileError').classList.add('visible');
      return;
    }

    showSection('loadingSection');

    try {
      const response = await fetch('/analyze', {
        method: 'POST',
        body: buildFormData(form),
      });
      const data = await response.json();

      if (!data.success) {
        qs('#errorMessage').textContent = data.error || 'Erreur inconnue.';
        showSection('errorSection');
        return;
      }

      App.analysis.renderResults(data.results);
      showSection('resultsSection');
    } catch (err) {
      qs('#errorMessage').textContent = 'Erreur réseau : ' + err.message;
      showSection('errorSection');
    }
  }

  function resetApp() {
    const form = qs('#analysisForm');
    if (form) form.reset();
    App.upload.reset();
    qs('#dropzoneFilename').textContent = '';
    qs('#dropzone').classList.remove('has-file');
    qs('#fileError').classList.remove('visible');
    qs('#subSectorGroup').hidden = true;
    App.governance.renderFields('');
    showSection('uploadSection');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  document.addEventListener('DOMContentLoaded', () => {
    App.upload.init();
    App.analysis.init();
    App.governance.init();
    App.history.init();

    on(qs('#analysisForm'), 'submit', handleSubmit);
    on(qs('#newAnalysisBtn'), 'click', resetApp);
    on(qs('#retryBtn'), 'click', resetApp);

    showSection('uploadSection');
  });

  return { showSection };
})();
