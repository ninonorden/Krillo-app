"""Tweede testronde: het ophalen van pagina's en het lezen van de antwoorden
van de zoekmachines, met nagebootste antwoorden.

Deze werkomgeving mag niet naar willekeurige websites, dus echt ophalen kan
hier niet. Wat wel te testen is: dat de HTML goed uitgelezen wordt, dat een
beveiligingspagina herkend wordt, en dat de antwoorden van Brave en Google
allebei goed gelezen worden. Een typefout daarin zou stilletjes nul resultaten
opleveren, en dan lijkt het alsof er niets te vinden is.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import requests

import bronnen

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


class NepAntwoord:
    def __init__(self, tekst="", status=200, soort="text/html; charset=utf-8", json_data=None):
        self.text = tekst
        self.status_code = status
        self.headers = {"Content-Type": soort}
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def met_antwoord(antwoord):
    """Vervangt requests.get door iets dat altijd hetzelfde teruggeeft."""
    def nep_get(*a, **kw):
        return antwoord
    return nep_get


origineel_get = requests.get

PAGINA = """
<!DOCTYPE html><html><head><title>De 10 leukste servieswinkels</title>
<script>var weg = "Xenos";</script><style>.a{color:red}</style></head>
<body>
<h1>De leukste webshops voor servies</h1>
<p>Wij kozen voor Dille &amp; Kamille, fonQ en Loods 5.</p>
<noscript>Zet javascript aan</noscript>
<a href="https://www.dille-kamille.nl/servies">Bekijk het assortiment</a>
<a href="/interne-link">Meer lezen</a>
</body></html>
"""

print("\n== een gewone pagina uitlezen ==")
requests.get = met_antwoord(NepAntwoord(PAGINA))
tekst = bronnen._haal_pagina("https://blog.nl/servies")
zo("er komt tekst uit", len(tekst) > 50, True)
zo("kop staat erin", "leukste webshops voor servies" in tekst.lower(), True)
zo("winkel uit de lopende tekst", bronnen.komt_voor(tekst, "Dille & Kamille"), True)
zo("tweede winkel", bronnen.komt_voor(tekst, "fonQ"), True)
zo("derde winkel", bronnen.komt_voor(tekst, "Loods 5"), True)
zo("winkel uit een link telt mee",
   bronnen.komt_voor(tekst, "Dille en Kamille", ook_domein="dille-kamille.nl"), True)
zo("script-inhoud telt NIET mee", bronnen.komt_voor(tekst, "Xenos"), False)
zo("winkel die er niet op staat", bronnen.komt_voor(tekst, "de Bijenkorf"), False)

print("\n== pagina's die we moeten overslaan ==")
requests.get = met_antwoord(NepAntwoord("iets", status=404))
zo("404 geeft niets", bronnen._haal_pagina("https://blog.nl/weg"), "")

requests.get = met_antwoord(NepAntwoord("%PDF-1.4 rommel", soort="application/pdf"))
zo("pdf geeft niets", bronnen._haal_pagina("https://blog.nl/folder.pdf"), "")

requests.get = met_antwoord(NepAntwoord("<html><body>Just a moment... checking your browser</body></html>"))
zo("beveiligingspagina geeft niets", bronnen._haal_pagina("https://blog.nl/cf"), "")


def kapot_get(*a, **kw):
    raise requests.ConnectionError("site doet het niet")


requests.get = kapot_get
zo("onbereikbare site geeft niets en klapt niet", bronnen._haal_pagina("https://weg.nl/"), "")

print("\n== het antwoord van Brave lezen ==")
import os
os.environ["BRAVE_API_KEY"] = "nep-sleutel-voor-de-test"
os.environ["GOOGLE_ZOEK_API_KEY"] = "nep"
os.environ["GOOGLE_ZOEK_CX"] = "nep"
brave_json = {"web": {"results": [
    {"url": "https://blog.nl/a", "title": "Top 10", "description": "Een lijstje"},
    {"url": "https://vergelijk.nl/b", "title": "Vergelijking", "description": ""},
    {"title": "regel zonder adres"},
]}}
requests.get = met_antwoord(NepAntwoord(json_data=brave_json))
resultaten = bronnen._zoek_brave("beste servieswinkel")
zo("twee bruikbare resultaten", len(resultaten), 2)
zo("adres klopt", resultaten[0]["url"], "https://blog.nl/a")
zo("titel klopt", resultaten[0]["titel"], "Top 10")
zo("regel zonder adres valt af", all(r["url"] for r in resultaten), True)

print("\n== het antwoord van Google lezen ==")
google_json = {"items": [
    {"link": "https://blog.nl/a", "title": "Top 10", "snippet": "Een lijstje"},
    {"link": "https://forum.nl/b", "title": "Draadje", "snippet": "Tekst"},
    {"title": "regel zonder link"},
]}
requests.get = met_antwoord(NepAntwoord(json_data=google_json))
resultaten = bronnen._zoek_google("beste servieswinkel")
zo("twee bruikbare resultaten", len(resultaten), 2)
zo("adres klopt", resultaten[1]["url"], "https://forum.nl/b")
zo("omschrijving klopt", resultaten[0]["omschrijving"], "Een lijstje")

print("\n== de parameters die we echt versturen ==")
# Dit gaat mis zonder dat je het merkt: Brave keurt een verkeerde landcode af
# en dat ziet er precies hetzelfde uit als nul resultaten.
verstuurd = {}


def vang_get(*a, **kw):
    verstuurd.clear()
    verstuurd.update(kw)
    verstuurd["adres"] = a[0] if a else kw.get("url")
    return NepAntwoord(json_data=brave_json)


requests.get = vang_get
bronnen._zoek_brave("test")
p = verstuurd["params"]
zo("Brave: landcode in HOOFDLETTERS", p["country"], "NL")
zo("Brave: taalcode in kleine letters", p["search_lang"], "nl")
zo("Brave: hoogstens 20 resultaten", p["count"] <= 20, True)
zo("Brave: sleutel in de kop en niet in het adres",
   "X-Subscription-Token" in verstuurd["headers"], True)
zo("Brave: sleutel staat niet in het webadres", "nep-sleutel" in str(verstuurd["adres"]), False)

requests.get = lambda *a, **kw: (verstuurd.clear(), verstuurd.update(kw),
                                 NepAntwoord(json_data=google_json))[-1]
bronnen._zoek_google("test")
p = verstuurd["params"]
zo("Google: landcode in kleine letters", p["gl"], "nl")
zo("Google: taalcode in kleine letters", p["hl"], "nl")
zo("Google: hoogstens 10 resultaten", p["num"] <= 10, True)

print("\n== de losse test van de zoekmachine ==")
requests.get = met_antwoord(NepAntwoord(json_data=brave_json))


class StilleKosten:
    @staticmethod
    def registreer_vaste_kosten(**kw):
        return None


echte = bronnen.kosten
bronnen.kosten = StilleKosten
uit = bronnen.test_zoekmachine("beste webshop voor cadeaus")
zo("gelukt", uit["gelukt"], True)
zo("met resultaten", len(uit["resultaten"]), 2)
zo("geen foutmelding", uit["fout"], None)

requests.get = met_antwoord(NepAntwoord(json_data={"web": {"results": []}}))
uit = bronnen.test_zoekmachine("iets")
zo("wel antwoord maar nul resultaten wordt uitgelegd", "nul resultaten" in (uit["fout"] or ""), True)

requests.get = met_antwoord(NepAntwoord("Unprocessable Entity", status=422))
uit = bronnen.test_zoekmachine("iets")
zo("een afgekeurd verzoek geeft de echte fout terug", "422" in (uit["fout"] or ""), True)
zo("en meldt niet dat het gelukt is", uit["gelukt"], False)
bronnen.kosten = echte

print("\n== een zoekmachine die uitvalt ==")


class NepKosten:
    laatste = {}

    @staticmethod
    def registreer_vaste_kosten(**kw):
        NepKosten.laatste = kw
        return None

    @staticmethod
    def mag_doorgaan(**kw):
        return {"mag": True}


echte_kosten = bronnen.kosten
bronnen.kosten = NepKosten

requests.get = kapot_get
zo("storing geeft lege lijst", bronnen.zoek("iets", webshop_url="winkel.nl"), [])
zo("mislukte zoekopdracht kost niets", NepKosten.laatste.get("bedrag"), 0.0)
zo("mislukking wordt wel vastgelegd", NepKosten.laatste.get("gelukt"), False)
zo("met een leesbare reden", bool(NepKosten.laatste.get("foutsoort")), True)

requests.get = met_antwoord(NepAntwoord(json_data=brave_json))
resultaten = bronnen.zoek("iets", webshop_url="winkel.nl")
zo("gelukte zoekopdracht geeft resultaten", len(resultaten), 2)
zo("en kost een halve cent", round(NepKosten.laatste.get("bedrag"), 4), 0.0045)
zo("staat als bronnen-zoeken in de kosten", NepKosten.laatste.get("soort"), "bronnen-zoeken")
zo("met de webshop erbij", NepKosten.laatste.get("webshop_url"), "winkel.nl")

bronnen.kosten = echte_kosten
requests.get = origineel_get

print("\n== de kostenrem telt vaste kosten mee ==")
import kosten as echte_kostenmodule

opgeslagen = {}


class NepDb:
    @staticmethod
    def bewaar_kostengebeurtenis(g):
        opgeslagen.update(g)
        return True


echte_db = echte_kostenmodule.db
echte_kostenmodule.db = NepDb
echte_kostenmodule.registreer_vaste_kosten(
    soort="bronnen-zoeken", provider="brave", bedrag=0.0045,
    webshop_url="winkel.nl", aantal=4, duur_ms=120)
zo("vier zoekopdrachten kosten vier keer zoveel", round(opgeslagen["kosten"], 4), 0.018)
zo("gaat door dezelfde tabel als de AI-kosten", opgeslagen["soort"], "bronnen-zoeken")
zo("wordt als berekend gemarkeerd", opgeslagen["kosten_status"], "berekend")
zo("geen verzonnen tokens", (opgeslagen["invoer_tokens"], opgeslagen["uitvoer_tokens"]), (0, 0))
echte_kostenmodule.db = echte_db

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
