"""
Krillo - fase 5 punt 12: de gratis zichtbaarheidstest.

De gratis scan liet tot nu toe alleen techniek zien: dertien controlepunten en
een cijfer. Dat is nuttig, maar niemand schrikt ervan. Waar een webshop-eigenaar
wel van schrikt is dit: "je wordt bij 1 van de 5 koopvragen genoemd, en bij drie
daarvan noemt AI wel andere winkels."

Dit bestand draait die test. Het bouwt met opzet niets nieuws: het gebruikt
precies dezelfde keten als een betalende klant, alleen met vijf vragen in plaats
van dertig. Zou de gratis test een eigen kortere weg nemen, dan kunnen het
gratis cijfer en het betaalde cijfer over dezelfde winkel verschillen, en dan
ben je je geloofwaardigheid kwijt op het enige moment dat telt.

Wat de gratis test bewust NIET geeft, want daar begint het betaalde product:
- de verklaring uit de dertien checks (waarom het zo is)
- de beweging tussen twee metingen
- de controle of wat AI zegt ook klopt
- dertig vragen in plaats van vijf, elke week opnieuw
"""

import os

import db
import kosten
import koopvragen
import metingen
import beoordeling
import scan_engine

# Vijf vragen, niet dertig. Genoeg om het te laten zien, weinig genoeg om
# gratis te kunnen zijn. Blijkt uit de eerste tientallen tests dat het goedkoper
# uitvalt dan gedacht, dan kan dit omhoog zonder dat er iets anders verandert.
GRATIS_VRAGEN = int(os.environ.get("GRATIS_VRAGEN", "5"))

# Harde rem op de dag. Zonder dit kan een bericht dat goed loopt je in een
# middag honderden euro's kosten aan mensen die alleen even kwamen kijken.
MAX_TESTS_PER_DAG = int(os.environ.get("GRATIS_TESTS_PER_DAG", "40"))

# Binnen deze termijn krijgt dezelfde winkel de uitslag van de vorige keer.
# Dat scheelt geld, maar het belangrijkste is dat iemand die zijn uitslag
# doorstuurt niet drie verschillende cijfers laat zien door de dagelijkse ruis
# in AI-antwoorden.
HERGEBRUIK_DAGEN = int(os.environ.get("GRATIS_TEST_HERGEBRUIK_DAGEN", "30"))


# Hoeveel van de dagelijkse kostengrens de gratis tests hoogstens mogen
# opmaken. Dit is het belangrijkste getal in dit bestand.
#
# Zonder deze grens deelt de gratis test dezelfde pot als de wekelijkse meting
# van betalende klanten. Een bericht dat goed loopt kan die pot dan leegtrekken,
# waarna de meting van iemand die 39 euro per maand betaalt niet meer draait.
# Dat is precies de verkeerde volgorde: eerst je klanten, dan de etalage.
DEEL_VOOR_GRATIS = float(os.environ.get("GRATIS_TEST_DEEL_VAN_DAG", "0.6"))


def mag_starten():
    """Kijkt of er nog een gratis test bij kan vandaag.

    Geeft (mag, reden) terug. De reden is bedoeld om aan een bezoeker te tonen,
    dus die is in gewone taal en zegt niet dat het over geld gaat. Een bezoeker
    hoeft niet te weten wat jouw dagbudget is."""
    vandaag = db.tel_tests_vandaag()
    if vandaag >= MAX_TESTS_PER_DAG:
        return False, ("De gratis test is vandaag heel vaak gedaan en staat tot morgen uit. "
                       "Mail hallo@krillo.nl, dan sturen we hem alsnog.")

    # De gewone rem: is de dag al helemaal op, dan gaat er sowieso niets meer.
    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        return False, ("De gratis test staat even uit. Probeer het later vandaag nog eens, "
                       "of mail hallo@krillo.nl.")

    # En de eigen, lagere grens, zodat er altijd budget overblijft voor de
    # metingen van klanten die ervoor betalen.
    plafond = kosten.GRENS_TOTAAL_DAG_EURO * DEEL_VOOR_GRATIS
    uitgegeven = (db.kosten_vandaag() or {}).get("kosten") or 0
    if plafond and uitgegeven >= plafond:
        return False, ("De gratis test staat voor vandaag uit. Probeer het morgen nog eens, "
                       "of mail hallo@krillo.nl.")
    return True, None


def draai(test_id, webshop_url):
    """De hele test voor een winkel. Draait op de achtergrond.

    Zet onderweg de status bij, zodat de pagina kan laten zien waar hij is in
    plaats van een spinner die niets zegt. Vijf vragen aan twee modellen duurt
    al gauw een minuut of twee, en dat is lang genoeg om iemand te laten
    afhaken als er niets gebeurt."""
    try:
        vragen = db.get_koopvragen(webshop_url, alleen_actief=True)
        if not vragen:
            db.zet_zichtbaarheidstest(test_id, "vragen bedenken")
            # Eerst scannen, zodat de vragen op meer gebaseerd zijn dan alleen
            # de homepagina. Dat kost geen AI-geld, alleen wat tijd.
            scan = scan_engine.run_scan(webshop_url)
            extra = scan.get("gevonden_paginas") if "error" not in scan else None
            gemaakt = koopvragen.genereer_koopvragen(webshop_url, extra)
            if gemaakt:
                db.bewaar_koopvragen(webshop_url, gemaakt["omschrijving"], gemaakt["vragen"])
            vragen = db.get_koopvragen(webshop_url, alleen_actief=True)

        if not vragen:
            db.zet_zichtbaarheidstest(
                test_id, "mislukt",
                foutsoort="Geen koopvragen: de site was niet goed genoeg te lezen.")
            return None

        db.zet_zichtbaarheidstest(test_id, "vragen stellen aan AI")
        samenvatting = metingen.meet_webshop(webshop_url, max_vragen=GRATIS_VRAGEN)
        meting_id = (samenvatting or {}).get("meting_id")
        if not meting_id or not samenvatting.get("gelukt"):
            reden = (samenvatting or {}).get("reden") or "Geen enkel AI-model gaf antwoord."
            db.zet_zichtbaarheidstest(test_id, "mislukt", foutsoort=reden)
            return None

        db.zet_zichtbaarheidstest(test_id, "antwoorden lezen", meting_id=meting_id)
        winkelnaam = _winkelnaam(webshop_url)
        beoordeling.beoordeel_ronde(webshop_url, meting_id, winkelnaam)

        beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url, meting_id)]
        if not beoordelingen:
            db.zet_zichtbaarheidstest(
                test_id, "mislukt",
                foutsoort="De antwoorden konden niet beoordeeld worden.")
            return None

        beeld = beoordeling.klantbeeld(webshop_url, beoordelingen)
        beeld = _inkorten(beeld)
        db.zet_zichtbaarheidstest(test_id, "klaar", resultaat=beeld, meting_id=meting_id)
        return beeld
    except Exception as e:
        print(f"Gratis zichtbaarheidstest mislukt voor {webshop_url}: {e}")
        db.zet_zichtbaarheidstest(test_id, "mislukt", foutsoort=str(e)[:200])
        return None


def _inkorten(beeld):
    """Houdt alleen over wat op de pagina en in de mail komt.

    Het volledige klantbeeld bevat meer dan een gratis test hoort te tonen, en
    het wordt als JSON bewaard. Klein houden dus, en niets bewaren wat we niet
    laten zien."""
    return {
        "gesteld": beeld.get("gesteld", 0),
        "telbaar": beeld.get("telbaar", 0),
        "genoemd": beeld.get("genoemd", 0),
        "aanbevolen": beeld.get("aanbevolen", 0),
        "modellen": beeld.get("modellen", []),
        "concurrenten": [
            {"naam": c["naam"], "genoemd": c["genoemd"], "wij": c.get("wij", False)}
            for c in (beeld.get("concurrenten") or [])[:5]
        ],
        "regels": [
            {
                "vraag": r["vraag"],
                "genoemd": bool(r.get("genoemd")),
                "aanbevolen": bool(r.get("aanbevolen")),
                "bewijs": (r.get("bewijs") or "")[:300] or None,
            }
            for r in (beeld.get("regels") or [])
        ],
    }


def _winkelnaam(webshop_url):
    """De naam zoals hij in AI-antwoorden staat, niet het domein. In een
    antwoord staat Dille & Kamille en niet dille-kamille.nl."""
    profiel = db.get_winkelprofiel(webshop_url)
    omschrijving = (profiel or {}).get("omschrijving") or ""
    if " is " in omschrijving:
        return omschrijving.split(" is ")[0].strip()
    return None


def samenvattingszin(resultaat, webshop_url=None):
    """De ene zin die bovenaan de uitslag staat en in de mail.

    Geen percentages en geen opsmuk. Als het slecht is, staat dat er gewoon,
    want dat is precies waarom iemand hierna verder klikt."""
    if not resultaat:
        return "De test kon niet afgemaakt worden."

    telbaar = resultaat.get("telbaar") or 0
    genoemd = resultaat.get("genoemd") or 0
    aanbevolen = resultaat.get("aanbevolen") or 0
    modellen = " en ".join(resultaat.get("modellen") or []) or "AI"

    if not telbaar:
        return ("Bij deze vragen noemde AI helemaal geen winkels, dus er valt over deze ronde "
                "niets te zeggen. Dat gebeurt soms.")

    if genoemd == 0:
        return (f"Je werd bij geen van de {telbaar} koopvragen genoemd door {modellen}. "
                f"Bij vragen waar wel winkels genoemd werden, stond jij er niet bij.")

    if aanbevolen:
        return (f"Je werd bij {genoemd} van de {telbaar} koopvragen genoemd door {modellen}, "
                f"en bij {aanbevolen} daarvan ook echt aanbevolen.")

    return (f"Je werd bij {genoemd} van de {telbaar} koopvragen genoemd door {modellen}, "
            f"maar bij geen enkele echt aanbevolen. Genoemd worden is niet hetzelfde als "
            f"aangeraden worden.")
