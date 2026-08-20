"""
Krillo - kosten bijhouden.

Waarom dit bestaat: bij AI reken je per aanroep af. Een klant die 39 euro per
maand betaalt kan makkelijk meer kosten dan hij opbrengt zonder dat je het
merkt, zeker zodra we per klant wekelijks tientallen vragen aan meerdere
modellen gaan stellen. Wat we nu niet vastleggen, kunnen we later niet meer
reconstrueren.

Drie dingen gebeuren hier:
1. Per AI-aanroep vastleggen wat er gebeurde en wat het kostte.
2. Die kosten deterministisch berekenen, dus altijd hetzelfde bedrag bij
   hetzelfde aantal tokens. Bewust geen AI die dat uitrekent.
3. Een rem: boven een bepaald bedrag stopt het en krijg je bericht.
"""

import os
import uuid
from datetime import datetime, timezone

import db

# Prijzen per miljoen tokens, in euro. Met een datum erbij vanaf wanneer die
# prijs gold. Verandert een aanbieder zijn prijs, dan voeg je een nieuwe regel
# toe met een nieuwe datum. Zo blijven de cijfers van vorige maand kloppen.
#
# LET OP: check deze bedragen tegen de actuele prijslijst van de aanbieder
# voordat je ze serieus gebruikt. Ze staan hier als startpunt.
PRIJZEN = [
    {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "invoer_per_miljoen": 2.70,
        "uitvoer_per_miljoen": 13.50,
        "valuta": "EUR",
        "geldig_vanaf": "2026-01-01",
        "prijsversie": "2026-01",
    },
]

# Grenzen. Bewust ruim ingesteld: ze zijn bedoeld om ontsporingen te vangen,
# niet om normaal gebruik in de weg te zitten.
GRENS_PER_SCAN_EURO = float(os.environ.get("GRENS_PER_SCAN_EURO", "0.50"))
GRENS_PER_SCAN_AANROEPEN = int(os.environ.get("GRENS_PER_SCAN_AANROEPEN", "20"))
GRENS_PER_KLANT_MAAND_EURO = float(os.environ.get("GRENS_PER_KLANT_MAAND_EURO", "10.00"))
GRENS_TOTAAL_DAG_EURO = float(os.environ.get("GRENS_TOTAAL_DAG_EURO", "25.00"))
MAX_POGINGEN = int(os.environ.get("MAX_POGINGEN", "3"))


def zoek_prijs(provider, model, moment=None):
    """Geeft de prijs die gold op het opgegeven moment. Vindt hij niets, dan
    geeft hij None terug en wordt de kostprijs als onbekend geregistreerd,
    niet als nul. Een onbekende prijs stilzwijgend op nul zetten geeft een
    verkeerd beeld van je marge."""
    moment = moment or datetime.now(timezone.utc)
    kandidaten = [
        p for p in PRIJZEN
        if p["provider"] == provider
        and p["model"] == model
        and datetime.fromisoformat(p["geldig_vanaf"]).replace(tzinfo=timezone.utc) <= moment
    ]
    if not kandidaten:
        return None
    return sorted(kandidaten, key=lambda p: p["geldig_vanaf"])[-1]


def bereken_kosten(invoer_tokens, uitvoer_tokens, prijs):
    """Tokens maal prijs. Meer is het niet, en dat is precies de bedoeling:
    hetzelfde aantal tokens moet altijd hetzelfde bedrag opleveren."""
    if prijs is None:
        return None
    invoer = (invoer_tokens / 1_000_000) * prijs["invoer_per_miljoen"]
    uitvoer = (uitvoer_tokens / 1_000_000) * prijs["uitvoer_per_miljoen"]
    return round(invoer + uitvoer, 6)


def registreer_aanroep(provider, model, invoer_tokens, uitvoer_tokens,
                        soort, webshop_url=None, email=None, scan_id=None,
                        duur_ms=None, gelukt=True, foutsoort=None,
                        pogingen=1, gebeurtenis_id=None):
    """Legt een AI-aanroep vast met wat hij kostte.

    gebeurtenis_id: geef een eigen id mee als je wil voorkomen dat dezelfde
    aanroep twee keer geteld wordt, bijvoorbeeld bij een herhaalde melding."""
    prijs = zoek_prijs(provider, model)
    kosten = bereken_kosten(invoer_tokens or 0, uitvoer_tokens or 0, prijs)

    if prijs is None:
        kosten_status = "onbekend"
        print(f"LET OP: geen prijs bekend voor {provider}/{model}. Kosten niet berekend.")
    else:
        kosten_status = "berekend"

    return db.bewaar_kostengebeurtenis({
        "gebeurtenis_id": gebeurtenis_id or uuid.uuid4().hex,
        "soort": soort,
        "provider": provider,
        "model": model,
        "invoer_tokens": invoer_tokens or 0,
        "uitvoer_tokens": uitvoer_tokens or 0,
        "kosten": kosten,
        "kosten_status": kosten_status,
        "prijsversie": prijs["prijsversie"] if prijs else None,
        "webshop_url": webshop_url,
        "email": email,
        "scan_id": scan_id,
        "duur_ms": duur_ms,
        "gelukt": gelukt,
        "foutsoort": foutsoort,
        "pogingen": pogingen,
    })


def mag_doorgaan(webshop_url=None, scan_id=None):
    """Wordt aangeroepen VOORDAT een dure aanroep start. Geeft terug of het
    mag, en zo niet waarom. Dit is de rem die voorkomt dat een vastgelopen
    proces of een uitzonderlijk grote klant je rekening laat oplopen."""
    redenen = []

    if scan_id:
        scan = db.kosten_per_scan(scan_id)
        if scan:
            if scan["aantal"] >= GRENS_PER_SCAN_AANROEPEN:
                redenen.append(
                    f"Deze scan heeft al {scan['aantal']} AI-aanroepen gedaan, "
                    f"de grens ligt op {GRENS_PER_SCAN_AANROEPEN}."
                )
            if (scan["kosten"] or 0) >= GRENS_PER_SCAN_EURO:
                redenen.append(
                    f"Deze scan kost al {scan['kosten']:.2f} euro, "
                    f"de grens ligt op {GRENS_PER_SCAN_EURO:.2f} euro."
                )

    if webshop_url:
        maand = db.kosten_per_klant_deze_maand(webshop_url)
        kosten = (maand or {}).get("kosten") or 0
        if kosten >= GRENS_PER_KLANT_MAAND_EURO:
            redenen.append(
                f"Deze klant kost deze maand al {kosten:.2f} euro, "
                f"de grens ligt op {GRENS_PER_KLANT_MAAND_EURO:.2f} euro."
            )
        else:
            _waarschuw_bij_drempel(webshop_url, kosten, GRENS_PER_KLANT_MAAND_EURO, "klant")

    vandaag = db.kosten_vandaag()
    totaal = (vandaag or {}).get("kosten") or 0
    if totaal >= GRENS_TOTAAL_DAG_EURO:
        redenen.append(
            f"De totale AI-kosten van vandaag staan op {totaal:.2f} euro, "
            f"de dagelijkse grens is {GRENS_TOTAAL_DAG_EURO:.2f} euro."
        )
    else:
        _waarschuw_bij_drempel("alles samen", totaal, GRENS_TOTAAL_DAG_EURO, "dag")

    if redenen:
        return {"mag": False, "reden": " ".join(redenen)}
    return {"mag": True}


def _waarschuw_bij_drempel(wie, kosten, grens, soort):
    """Meldt het in de logs bij vijftig en tachtig procent, zodat je het ziet
    aankomen in plaats van pas als het al te laat is."""
    if grens <= 0:
        return
    deel = kosten / grens
    if deel >= 0.8:
        print(f"WAARSCHUWING ({soort}): {wie} zit op {deel*100:.0f}% van de grens "
              f"({kosten:.2f} van {grens:.2f} euro).")
    elif deel >= 0.5:
        print(f"Let op ({soort}): {wie} zit op {deel*100:.0f}% van de grens "
              f"({kosten:.2f} van {grens:.2f} euro).")
