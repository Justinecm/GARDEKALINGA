// Apply the saved theme before React loads (no flash). Auto follows the Manila sky:
// dark from 6 PM to 5 AM (Gabi), light otherwise.
(function () {
  try {
    var pref = localStorage.getItem("gk.theme") || "auto";
    var hour = Number(new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false, timeZone: "Asia/Manila" }).format(new Date())) % 24;
    var night = hour >= 18 || hour < 5;
    var theme = pref === "dark" || (pref === "auto" && night) ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", theme);
    var lang = localStorage.getItem("gk.lang");
    if (lang === "fil") document.documentElement.setAttribute("lang", "fil");
  } catch (e) {
    /* storage blocked: keep light */
  }
})();
