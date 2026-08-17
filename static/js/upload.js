/* Zone de dépôt de fichier, validation, sélection secteur/sous-secteur. */
window.App = window.App || {};

App.upload = (function () {
  const { qs, on } = App.utils;

  const MAX_FILE_SIZE_MB = 10;
  const ALLOWED_EXTENSIONS = ['xlsx', 'xls'];

  let selectedFile = null;

  function getExtension(filename) {
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : '';
  }

  function validateFile(file) {
    if (!file) return 'Veuillez sélectionner un fichier.';
    if (!ALLOWED_EXTENSIONS.includes(getExtension(file.name))) {
      return 'Format non supporté. Fichier attendu : .xlsx ou .xls.';
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      return `Fichier trop volumineux (max ${MAX_FILE_SIZE_MB} MB).`;
    }
    return null;
  }

  function setFile(file, dropzone, fileInput, errorEl, filenameEl) {
    const error = validateFile(file);
    if (error) {
      selectedFile = null;
      dropzone.classList.remove('has-file');
      errorEl.textContent = error;
      errorEl.classList.add('visible');
      filenameEl.textContent = '';
      return false;
    }
    selectedFile = file;
    errorEl.textContent = '';
    errorEl.classList.remove('visible');
    dropzone.classList.add('has-file');
    filenameEl.innerHTML = `<span class="status-icon--ok">&#10003;</span> ${App.utils.escapeHtml(file.name)}`;
    return true;
  }

  function init() {
    const dropzone = qs('#dropzone');
    const fileInput = qs('#fileInput');
    const browseBtn = qs('#browseBtn');
    const errorEl = qs('#fileError');
    const filenameEl = qs('#dropzoneFilename');
    const sectorSelect = qs('#sectorSelect');
    const subSectorGroup = qs('#subSectorGroup');

    if (!dropzone || !fileInput) return;

    on(browseBtn, 'click', () => fileInput.click());
    on(dropzone, 'click', (e) => {
      if (e.target !== browseBtn) fileInput.click();
    });
    on(dropzone, 'keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        fileInput.click();
      }
    });

    on(fileInput, 'change', () => {
      if (fileInput.files && fileInput.files[0]) {
        setFile(fileInput.files[0], dropzone, fileInput, errorEl, filenameEl);
      }
    });

    ['dragenter', 'dragover'].forEach((evt) => {
      on(dropzone, evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach((evt) => {
      on(dropzone, evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove('dragover');
      });
    });

    on(dropzone, 'drop', (e) => {
      const files = e.dataTransfer && e.dataTransfer.files;
      if (files && files[0]) {
        fileInput.files = files;
        setFile(files[0], dropzone, fileInput, errorEl, filenameEl);
      }
    });

    on(sectorSelect, 'change', () => {
      const isIndustry = sectorSelect.value === 'industry';
      subSectorGroup.hidden = !isIndustry;
      if (!isIndustry) {
        qs('#subSectorSelect').value = '';
      }
    });
  }

  function getSelectedFile() {
    return selectedFile;
  }

  function reset() {
    selectedFile = null;
  }

  return { init, getSelectedFile, validateFile, reset };
})();
