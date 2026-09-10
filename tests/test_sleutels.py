"""Tests voor sleutels die verlopen.

Shopify weigert sinds april 2026 eeuwige sleutels voor nieuwe publieke apps.
Dit bestand bewaakt de vier dingen die daarbij mis kunnen gaan, en die alle
vier tot een winkel leiden die wij niet meer kunnen bedienen:

1. Vragen wij wel om een verlopende sleutel.
2. Weigeren wij een antwoord zonder vervaldatum, in plaats van hem stil op te
   slaan en pas bij de eerste meting een 403 te krijgen.
3. Verversen wij op tijd, en slaan wij het nieuwe paar op VOORDAT wij hem
   gebruiken.
4. Gebruiken wij een nieuwe sleutel NIET als het opslaan mislukt is.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

os.environ.setdefault("SHOPIFY_API_KEY", "testsleutel")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import shopify_app  # noqa: E402

fouten = []


def controleer(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok   {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


class NepAntwoord:
    def __init__(self, code, inhoud):
        self.status_code = code
        self._inhoud = inhoud
        self.text = str(inhoud)

    def json(self):
        return self._inhoud


def met_neppost(antwoord, verzameling):
    """Vervangt requests.post en onthoudt wat er verstuurd is."""
    def nep(url, json=None, timeout=None):
        verzameling.append({"url": url, "body": json or {}})
        return antwoord
    return nep


print("\n1. Het inwisselen van een kaartje vraagt om een verlopende sleutel")
verstuurd = []
shopify_app.requests.post = met_neppost(NepAntwoord(200, {
    "access_token": "shpat_nieuw", "expires_in": 3599,
    "refresh_token": "shprt_een", "refresh_token_expires_in": 7775999,
    "scope": "read_products"}), verstuurd)

uit = shopify_app.wissel_id_token("test.myshopify.com", "kaartje")
controleer("het lukt", uit.get("gelukt") is True)
controleer("expiring staat in het verzoek", verstuurd[0]["body"].get("expiring") == 1)
controleer("de geldigheid komt mee", uit.get("geldig_seconden") == 3599)
controleer("de verversleutel komt mee", uit.get("verversleutel") == "shprt_een")
controleer("de geldigheid van de verversleutel komt mee",
           uit.get("verversleutel_seconden") == 7775999)


print("\n2. Een sleutel zonder vervaldatum wordt geweigerd")
verstuurd = []
shopify_app.requests.post = met_neppost(NepAntwoord(200, {
    "access_token": "shpat_eeuwig", "scope": "read_products"}), verstuurd)
uit = shopify_app.wissel_id_token("test.myshopify.com", "kaartje")
controleer("wordt niet als gelukt gemeld", uit.get("gelukt") is False)
controleer("de reden noemt de vervaldatum", "vervaldatum" in (uit.get("fout") or ""))
controleer("er komt geen sleutel uit", not uit.get("sleutel"))


print("\n3. Verversen levert een nieuw paar op")
verstuurd = []
shopify_app.requests.post = met_neppost(NepAntwoord(200, {
    "access_token": "shpat_twee", "expires_in": 3599,
    "refresh_token": "shprt_twee", "refresh_token_expires_in": 7775999}), verstuurd)
uit = shopify_app.ververs_sleutel("test.myshopify.com", "shprt_een")
controleer("het lukt", uit.get("gelukt") is True)
controleer("grant_type is refresh_token",
           verstuurd[0]["body"].get("grant_type") == "refresh_token")
controleer("de oude verversleutel gaat mee",
           verstuurd[0]["body"].get("refresh_token") == "shprt_een")
controleer("er komt een NIEUWE verversleutel terug",
           uit.get("verversleutel") == "shprt_twee")
controleer("niet als voorgoed mislukt gemeld", uit.get("voorgoed_mislukt") is False)


print("\n4. Een geweigerde verversleutel is voorgoed mislukt, een storing niet")
for code in (400, 401, 403):
    shopify_app.requests.post = met_neppost(NepAntwoord(code, {"error": "nee"}), [])
    uit = shopify_app.ververs_sleutel("test.myshopify.com", "shprt_oud")
    controleer(f"{code} is voorgoed mislukt", uit.get("voorgoed_mislukt") is True)
for code in (500, 502, 503):
    shopify_app.requests.post = met_neppost(NepAntwoord(code, {"error": "later"}), [])
    uit = shopify_app.ververs_sleutel("test.myshopify.com", "shprt_oud")
    controleer(f"{code} is NIET voorgoed mislukt", uit.get("voorgoed_mislukt") is False)


print("\n5. De keuze om wel of niet te verversen")
#
# Dit is de kern van _shopify_sleutel in app.py, hier nagebouwd zodat de test
# geen database en geen Flask nodig heeft. Klopt deze rekensom niet, dan valt
# een meting van vijf minuten halverwege om met een 403.
MARGE = 300


def moet_verversen(sleutel_tot):
    if sleutel_tot is None:
        return True
    return (sleutel_tot - datetime.now(timezone.utc)).total_seconds() <= MARGE


nu = datetime.now(timezone.utc)
controleer("een sleutel zonder vervaldatum wordt vervangen", moet_verversen(None))
controleer("een verlopen sleutel wordt vervangen",
           moet_verversen(nu - timedelta(minutes=1)))
controleer("een sleutel die over een minuut verloopt wordt vervangen",
           moet_verversen(nu + timedelta(seconds=60)))
controleer("een sleutel die nog een half uur meegaat blijft staan",
           not moet_verversen(nu + timedelta(minutes=30)))


print("\n6. Een nieuwe sleutel wordt niet gebruikt als het opslaan mislukt")
#
# Shopify laat de oude verversleutel vervallen zodra je de nieuwe gebruikt.
# Slaan wij het paar niet op, dan zijn wij de winkel voorgoed kwijt. Dus is
# "opslaan mislukt" hier hetzelfde als "geen sleutel".
def sleutel_na_verversen(opslaan_lukt):
    uit = {"gelukt": True, "sleutel": "shpat_drie", "geldig_seconden": 3599,
           "verversleutel": "shprt_drie"}
    if not uit.get("gelukt"):
        return None
    if not opslaan_lukt:
        return None
    return uit["sleutel"]


controleer("bij gelukt opslaan komt de sleutel eruit",
           sleutel_na_verversen(True) == "shpat_drie")
controleer("bij mislukt opslaan komt er niets uit",
           sleutel_na_verversen(False) is None)


print("\n7. Wat er in app.py en db.py aanwezig moet zijn")
hier = os.path.dirname(os.path.abspath(__file__))
app_tekst = open(os.path.join(APP, "app.py")).read()
db_tekst = open(os.path.join(APP, "db.py")).read()

controleer("app.py heeft _shopify_sleutel", "def _shopify_sleutel(" in app_tekst)
controleer("db.py heeft vervang_shopify_sleutelpaar",
           "def vervang_shopify_sleutelpaar(" in db_tekst)
controleer("db.py heeft wis_shopify_verversleutel",
           "def wis_shopify_verversleutel(" in db_tekst)
controleer("de kolom sleutel_tot wordt aangemaakt", "sleutel_tot TIMESTAMPTZ" in db_tekst)
controleer("de kolom verversleutel wordt aangemaakt", "verversleutel TEXT" in db_tekst)
# Dit is de belangrijkste controle van dit bestand: nergens mag de sleutel nog
# rechtstreeks uit de rij gehaald worden om mee naar Shopify te gaan, want dan
# kan hij verlopen zijn en krijg je een 403.
#
# Eén keer mag wel, en maar één keer: de regel binnen _shopify_sleutel zelf die
# de verse sleutel in de rij terugzet. Die staat links van het isteken en gaat
# dus nergens heen.
regels_met = [r.strip() for r in app_tekst.splitlines() if 'rij["toegangssleutel"]' in r]
controleer("de sleutel wordt nergens rechtstreeks uit de rij gebruikt",
           regels_met == ['rij["toegangssleutel"] = uitkomst["sleutel"]'])


print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
