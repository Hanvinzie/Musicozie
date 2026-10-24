(function () {
  "use strict";
  var stored = null;
  try { stored = localStorage.getItem("musicozie-theme"); } catch (e) { /* storage blocked */ }
  var theme = stored === "light" || stored === "dark"
    ? stored
    : (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  document.documentElement.setAttribute("data-theme", theme);
})();
