/* Helpers partagés : formatage, DOM. */
window.App = window.App || {};

App.utils = (function () {
  function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined || Number.isNaN(num)) return '--';
    return Number(num).toLocaleString('fr-FR', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function formatPercent(num, decimals = 2) {
    if (num === null || num === undefined || Number.isNaN(num)) return '--';
    return formatNumber(num, decimals) + '%';
  }

  function formatMDH(num) {
    if (num === null || num === undefined || Number.isNaN(num)) return '--';
    return formatNumber(num, 1) + ' MDH';
  }

  function formatUnit(num, unit, decimals = 2) {
    if (num === null || num === undefined || Number.isNaN(num)) return 'N/A';
    if (unit === 'MDH') return formatMDH(num);
    if (unit === '%') return formatPercent(num, decimals);
    return formatNumber(num, decimals) + (unit ? ' ' + unit : '');
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.from((root || document).querySelectorAll(selector));
  }

  function on(el, event, handler) {
    if (el) el.addEventListener(event, handler);
  }

  return { formatNumber, formatPercent, formatMDH, formatUnit, escapeHtml, qs, qsa, on };
})();
