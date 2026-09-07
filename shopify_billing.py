"""Betalen in de Shopify-app.

Shopify eist dat een betaalde app via hun eigen betaling loopt. Je mag een
winkelier niet naar je eigen betaalpagina sturen. Dat is geen advies, daar wordt
je app op afgekeurd. Dus: Mollie voor krillo.nl, dit voor Shopify.

Hoe het loopt:
  1. De winkelier klikt op abonneren.
  2. Wij vragen Shopify om een abonnement en krijgen een bevestigingslink terug.
  3. Wij sturen zijn browser daarheen, hij ziet daar de prijs en gaat akkoord.
  4. Shopify stuurt hem terug naar onze app.

Wat wij bewust NIET doen: de stand van het abonnement bij ons opslaan. Wij
vragen hem elke keer aan Shopify. Een winkelier kan zijn abonnement opzeggen in
zijn eigen scherm zonder dat wij daar bericht van krijgen, en dan zou onze
opgeslagen stand zeggen dat hij betaalt terwijl dat niet zo is. Iemand
aanrekenen wat hij niet heeft is het ergste wat hier mis kan gaan.
"""

import os

import requests

import shopify_app

# Het betaalde plan. Eén plan, één prijs, geen trapjes: bij drie prijzen gaat
# een winkelier vergelijken in plaats van beslissen.
PLAN_NAAM = "Krillo monitoring"
PLAN_PRIJS = "39.00"
PLAN_VALUTA = "USD"
PROEFDAGEN = 7


def testmodus():
    """Of wij nepbetalingen maken.

    In een ontwikkelwinkel kan het niet anders: Shopify weigert daar een echte
    betaling. Zet SHOPIFY_BILLING_TEST op 'ja' zolang je test, en HAAL HEM WEG
    voordat je live gaat. Een testabonnement levert namelijk geen geld op, en
    dat merk je pas als je op je rekening kijkt."""
    return (os.environ.get("SHOPIFY_BILLING_TEST") or "nee").strip().lower() == "ja"


def _graphql(winkel, sleutel, vraag, variabelen=None):
    winkel = shopify_app._schoon(winkel)
    if not shopify_app.geldige_winkel(winkel) or not sleutel:
        return {"gelukt": False, "fout": "Geen geldige winkel of sleutel."}
    try:
        antwoord = requests.post(
            f"https://{winkel}/admin/api/{shopify_app.API_VERSIE}/graphql.json",
            headers=shopify_app._kop(sleutel),
            json={"query": vraag, "variables": variabelen or {}},
            timeout=25)
        if antwoord.status_code >= 300:
            return {"gelukt": False,
                    "fout": f"Shopify gaf {antwoord.status_code}: {antwoord.text[:200]}"}
        gegevens = antwoord.json() or {}
        if gegevens.get("errors"):
            return {"gelukt": False, "fout": str(gegevens["errors"])[:300]}
        return {"gelukt": True, "gegevens": gegevens.get("data") or {}}
    except Exception as e:
        return {"gelukt": False, "fout": f"{type(e).__name__}: {e}"[:250]}


VRAAG_HUIDIG = """
query {
  currentAppInstallation {
    activeSubscriptions {
      id
      name
      status
      test
      trialDays
      createdAt
      currentPeriodEnd
    }
  }
}
"""


def huidig_abonnement(winkel, sleutel):
    """Het lopende abonnement van deze winkel, of None.

    Bij een fout geven wij ook None terug, met de fout erbij. Dat is met opzet:
    weten wij het niet zeker, dan behandelen wij hem als niet-betalend en niet
    als betalend. Liever iemand een dag te veel gratis geven dan iemand die
    niets afsloot laten denken dat hij betaalt."""
    uit = _graphql(winkel, sleutel, VRAAG_HUIDIG)
    if not uit["gelukt"]:
        print(f"Abonnement opvragen mislukt voor {winkel}: {uit['fout']}")
        return {"actief": False, "abonnement": None, "fout": uit["fout"]}
    lopend = (((uit["gegevens"] or {}).get("currentAppInstallation") or {})
              .get("activeSubscriptions") or [])
    levend = [a for a in lopend if (a.get("status") or "").upper() == "ACTIVE"]
    if not levend:
        return {"actief": False, "abonnement": None, "fout": None}
    return {"actief": True, "abonnement": levend[0], "fout": None}


OPDRACHT_START = """
mutation maakAbonnement($naam: String!, $terugUrl: URL!, $test: Boolean!,
                        $proefdagen: Int!, $bedrag: Decimal!, $valuta: CurrencyCode!) {
  appSubscriptionCreate(
    name: $naam
    returnUrl: $terugUrl
    test: $test
    trialDays: $proefdagen
    lineItems: [{
      plan: {
        appRecurringPricingDetails: {
          price: { amount: $bedrag, currencyCode: $valuta }
          interval: EVERY_30_DAYS
        }
      }
    }]
  ) {
    userErrors { field message }
    confirmationUrl
    appSubscription { id status }
  }
}
"""


def start_abonnement(winkel, sleutel, terug_url, proefdagen=None):
    """Vraagt Shopify om een abonnement. Geeft de bevestigingslink terug.

    De proefperiode kan je op nul zetten. Dat is nodig omdat een winkel die
    al eens een proef gehad heeft er geen tweede hoort te krijgen: opzeggen en
    meteen weer starten zou anders telkens zeven nieuwe gratis dagen geven, en
    dat kan eindeloos.

    Er is op dit moment nog niets afgesloten en er is nog niets betaald. Dat
    gebeurt pas als de winkelier op die pagina akkoord geeft. Zeg dat dus ook zo
    op het scherm: 'je gaat naar Shopify om het te bevestigen', niet 'je bent
    geabonneerd'."""
    if not terug_url:
        return {"gelukt": False, "fout": "Er ontbreekt een adres om naar terug te keren."}
    uit = _graphql(winkel, sleutel, OPDRACHT_START, {
        "naam": PLAN_NAAM,
        "terugUrl": terug_url,
        "test": testmodus(),
        "proefdagen": PROEFDAGEN if proefdagen is None else max(0, int(proefdagen)),
        "bedrag": PLAN_PRIJS,
        "valuta": PLAN_VALUTA,
    })
    if not uit["gelukt"]:
        return {"gelukt": False, "fout": uit["fout"]}
    blok = ((uit["gegevens"] or {}).get("appSubscriptionCreate") or {})
    problemen = blok.get("userErrors") or []
    if problemen:
        melding = "; ".join(p.get("message", "") for p in problemen)
        print(f"Abonnement aanmaken geweigerd voor {winkel}: {melding}")
        return {"gelukt": False, "fout": melding[:300]}
    link = blok.get("confirmationUrl")
    if not link:
        return {"gelukt": False, "fout": "Shopify gaf geen bevestigingslink terug."}
    return {"gelukt": True, "link": link,
            "abonnement": blok.get("appSubscription") or {},
            "test": testmodus()}


OPDRACHT_STOP = """
mutation stopAbonnement($id: ID!) {
  appSubscriptionCancel(id: $id) {
    userErrors { field message }
    appSubscription { id status }
  }
}
"""


def zeg_op(winkel, sleutel, abonnement_id):
    """Opzeggen. Moet kunnen vanuit onze eigen app, niet alleen bij Shopify.

    Een opzegknop die er niet is leest als 'ze maken het expres moeilijk', en
    dat is precies het soort ding waar een beoordelaar over valt."""
    if not abonnement_id:
        return {"gelukt": False, "fout": "Er is geen lopend abonnement."}
    uit = _graphql(winkel, sleutel, OPDRACHT_STOP, {"id": abonnement_id})
    if not uit["gelukt"]:
        return {"gelukt": False, "fout": uit["fout"]}
    blok = ((uit["gegevens"] or {}).get("appSubscriptionCancel") or {})
    problemen = blok.get("userErrors") or []
    if problemen:
        return {"gelukt": False,
                "fout": "; ".join(p.get("message", "") for p in problemen)[:300]}
    return {"gelukt": True, "abonnement": blok.get("appSubscription") or {}}
