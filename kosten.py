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
    # Voor de metingen (fase 5 stap 3). Deze bedragen zijn op 20-08-2026
    # opgezocht op de openbare prijspagina's van de aanbieders en omgerekend
    # naar euro. Ze zijn een startpunt, geen contract: controleer ze in je
    # eigen facturatie-overzicht bij OpenAI en Google voordat je er marges op
    # baseert. Verandert er een prijs, voeg dan een NIEUWE regel toe met een
    # nieuwe datum en prijsversie, zodat de cijfers van vorige maand blijven
    # kloppen.
    {
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "invoer_per_miljoen": 1.80,
        "uitvoer_per_miljoen": 10.80,
        "valuta": "EUR",
        "geldig_vanaf": "2026-08-01",
        "prijsversie": "2026-08",
    },
    {
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "invoer_per_miljoen": 0.18,
        "uitvoer_per_miljoen": 1.08,
        "valuta": "EUR",
        "geldig_vanaf": "2026-08-01",
        "prijsversie": "2026-08",
    },
    {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "invoer_per_miljoen": 0.68,
        "uitvoer_per_miljoen": 4.05,
        "valuta": "EUR",
        "geldig_vanaf": "2026-08-01",
        "prijsversie": "2026-08",
    },
    {
        "provider": "google",
        "model": "gemini-3.7-flash",
        "invoer_per_miljoen": 0.68,
        "uitvoer_per_miljoen": 3.38,
        "valuta": "EUR",
        "geldig_vanaf": "2026-08-01",
        "prijsversie": "2026-08",
    },
    {
        "provider": "google",
        "model": "gemini-3.5-flash-lite",
        "invoer_per_miljoen": 0.27,
        "uitvoer_per_miljoen": 2.25,
        "valuta": "EUR",
        "geldig_vanaf": "2026-08-01",
        "prijsversie": "2026-08",
    },
    {
        "provider": "google",
        "model": "gemini-2.5-flash-lite",
        "invoer_per_miljoen": 0.09,
        "uitvoer_per_miljoen": 0.36,
        "valuta": "EUR",
        "geldig_vanaf": "2026-08-01",
        "prijsversie": "2026-08",
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


def registreer_vaste_kosten(soort, provider, bedrag, webshop_url=None, email=None,
                            scan_id=None, duur_ms=None, gelukt=True, foutsoort=None,
                            aantal=1, gebeurtenis_id=None):
    """Legt een handeling vast die per stuk kost in plaats van per token.

    Nodig sinds de bronanalyse: een zoekopdracht bij een zoekmachine kost een
    vast bedrag, ongeacht hoe lang het antwoord is. Tokens invullen zou daar
    een verzonnen getal van maken, en dan klopt /admin/kosten niet meer.

    De prijs staat bij de aanroeper, niet hier, want die weet om welke dienst
    het gaat. Wel gaat het door dezelfde tabel, zodat de dagrem en het
    maandoverzicht per klant deze kosten gewoon meetellen. Dat is het punt:
    een rem die de helft van je uitgaven niet ziet is geen rem."""
    return db.bewaar_kostengebeurtenis({
        "gebeurtenis_id": gebeurtenis_id or uuid.uuid4().hex,
        "soort": soort,
        "provider": provider,
        "model": None,
        "invoer_tokens": 0,
        "uitvoer_tokens": 0,
        "kosten": round(float(bedrag or 0) * max(1, int(aantal)), 6),
        "kosten_status": "berekend",
        "prijsversie": "vast-tarief",
        "webshop_url": webshop_url,
        "email": email,
        "scan_id": scan_id,
        "duur_ms": duur_ms,
        "gelukt": gelukt,
        "foutsoort": foutsoort,
        "pogingen": 1,
    })


# Wat we rekenen voor een aanroep waarvan we de prijs niet kennen.
#
# Staat een modelnaam niet in PRIJZEN, dan wordt de kostprijs als "onbekend"
# opgeslagen en niet als nul. Maar de optelling in de database slaat die rijen
# over, dus de rem zag ze niet. Eén typefout in een modelnaam in Render en de
# dagrem van 25 euro sloeg nooit meer aan terwijl de rekening gewoon opliep.
#
# Daarom tellen onbekende aanroepen nu mee tegen een ruime schatting. Liever
# een rem die te vroeg dichtgaat dan een rem die niets ziet.
SCHATTING_ONBEKENDE_AANROEP_EURO = float(
    os.environ.get("SCHATTING_ONBEKENDE_AANROEP_EURO", "0.02"))


def _met_onbekend(regel):
    """Telt de aanroepen zonder bekende prijs mee tegen een schatting."""
    if not regel:
        return 0.0
    kosten = float(regel.get("kosten") or 0)
    onbekend = int(regel.get("onbekende_prijs") or 0)
    return kosten + onbekend * SCHATTING_ONBEKENDE_AANROEP_EURO


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
            if _met_onbekend(scan) >= GRENS_PER_SCAN_EURO:
                redenen.append(
                    f"Deze scan kost al {scan['kosten']:.2f} euro, "
                    f"de grens ligt op {GRENS_PER_SCAN_EURO:.2f} euro."
                )

    if webshop_url:
        maand = db.kosten_per_klant_deze_maand(webshop_url)
        kosten = _met_onbekend(maand)
        if kosten >= GRENS_PER_KLANT_MAAND_EURO:
            redenen.append(
                f"Deze klant kost deze maand al {kosten:.2f} euro, "
                f"de grens ligt op {GRENS_PER_KLANT_MAAND_EURO:.2f} euro."
            )
        else:
            _waarschuw_bij_drempel(webshop_url, kosten, GRENS_PER_KLANT_MAAND_EURO, "klant")

    vandaag = db.kosten_vandaag()
    totaal = _met_onbekend(vandaag)
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


ABONNEMENT_PER_MAAND = float(os.environ.get("ABONNEMENT_PER_MAAND", "39"))


def marge_per_klant(regels, abonnement=None):
    """Fase 5: wat kost een klant per maand, en houdt het abonnement stand?

    Krijgt de rijen uit het kostenoverzicht en zet de kosten van elke webshop
    naast wat een abonnee betaalt. Dit was de reden om de kostenregistratie te
    bouwen: vooraf was niet zeker of 39 euro per maand genoeg zou zijn.

    Let op bij het lezen: het overzicht loopt over een gekozen aantal dagen en
    een abonnement loopt per maand. Daarom rekenen we de kosten om naar een
    maand, anders vergelijk je twee weken kosten met een hele maand omzet."""
    abonnement = abonnement if abonnement is not None else ABONNEMENT_PER_MAAND
    uitkomst = []
    for r in regels or []:
        if not r.get("webshop_url"):
            continue
        kosten_euro = float(r.get("kosten") or 0)
        uitkomst.append({
            "webshop_url": r["webshop_url"],
            "aanroepen": r.get("aantal") or 0,
            "kosten": kosten_euro,
            "over": abonnement - kosten_euro,
            "aandeel": (kosten_euro / abonnement) if abonnement else None,
            "verliesgevend": kosten_euro >= abonnement,
        })
    uitkomst.sort(key=lambda k: k["kosten"], reverse=True)
    return uitkomst


def naar_maand(kosten_euro, dagen):
    """Rekent kosten over een periode om naar een maand van dertig dagen."""
    if not dagen:
        return kosten_euro
    return kosten_euro * (30.0 / dagen)
