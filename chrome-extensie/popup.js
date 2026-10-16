// Stap 136: vraagt bij krilloai.com de plek op van de winkel in het actieve
// tabblad. Geen tracking, geen opslag; alleen het adres van de site.
(function () {
  var API = "https://krilloai.com";
  function zet(id, tekst) { document.getElementById(id).textContent = tekst || ""; }
  chrome.tabs.query({active: true, currentWindow: true}, function (tabs) {
    var url = (tabs && tabs[0] && tabs[0].url) || "";
    var host = "";
    try { host = new URL(url).hostname.replace(/^www\./, ""); } catch (e) {}
    if (!host || url.indexOf("http") !== 0) {
      zet("kop", "Open an online store first.");
      return;
    }
    zet("winkel", host);
    document.getElementById("knop").href = API + "/?winkel=" + encodeURIComponent(host) + "&utm_source=chrome-extension#scan";
    fetch(API + "/api/tools/index-check", {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify({url: host})})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.fout) { zet("kop", d.fout); return; }
        zet("kop", d.kop || "");
        if (d.gevonden && d.pagina) {
          var a = document.getElementById("lijst");
          a.href = API + d.pagina + "?utm_source=chrome-extension";
          a.hidden = false;
          zet("uitleg", "Measured every month with the same buying questions in ChatGPT and Gemini.");
        } else {
          zet("uitleg", d.uitleg || "");
        }
      })
      .catch(function () { zet("kop", "Krillo could not be reached. Try again in a moment."); });
  });
})();
