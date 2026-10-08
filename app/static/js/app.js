(function () {
  "use strict";

  // Hide the login/register preloader once the page has loaded
  if (document.querySelector(".preloader") != null) {
    window.addEventListener('load', function () {
      document.querySelector('body').classList.add("loaded-success");
    });
  }

  // Sortable tables (pages without simple-datatables skip this)
  if (typeof simpleDatatables !== 'undefined') {
    document.querySelectorAll(".table-sorter").forEach(function (el) {
      new simpleDatatables.DataTable(el);
    });
  }
})();
