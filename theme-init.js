/* Applies the stored theme/language before first paint (loaded synchronously in <head>). */
(function () {
  try {
    var t = localStorage.getItem("ftrap_theme") || "light";
    var l = localStorage.getItem("ftrap_lang") || (/^de\b/i.test(navigator.language || "") ? "de" : "en");
    document.documentElement.dataset.theme = t;
    document.documentElement.dataset.lang = l;
  } catch (e) {}
})();
