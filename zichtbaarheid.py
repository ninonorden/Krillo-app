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
import bronnen
import kosten
import koopvragen
import metingen
import beoordeling
import markt
import scan_engine

# Vijf vragen, niet dertig. Genoeg om het te laten zien, weinig genoeg om
# gratis te kunnen zijn. Blijkt uit de eerste tientallen tests dat het goedkoper
# uitvalt dan gedacht, dan kan dit omhoog zonder dat er iets anders verandert.
GRATIS_VRAGEN = int(os.environ.get("GRATIS_VRAGEN", "5"))

# De voorproef: draait automatisch bij elke gratis scan, zonder e-mailadres.
#
# Waarom dit er is. Op een ondernemersforum testte iemand de gratis scan en zijn
# conclusie was: "eigenlijk zie ik vooral basis SEO zaken". Hij had gelijk over
# wat hij zag. Het cijfer over dertien technische punten stond bovenaan, en het
# enige dat Krillo echt onderscheidt, of AI je winkel noemt, zat eronder achter
# een e-mailformulier. Wie niet doorklikt ziet een SEO-tool.
#
# Drie vragen bij één model kost ongeveer zes cent. Dat is de prijs van een
# eerste indruk die klopt.
VOORPROEF_AAN = os.environ.get("VOORPROEF_AAN", "ja").lower() not in ("nee", "no", "0", "uit")
VOORPROEF_VRAGEN = int(os.environ.get("VOORPROEF_VRAGEN", "3"))

# De bronanalyse in de gratis test.
#
# Waarom dit hier staat. Dit is het sterkste dat Krillo heeft: niet "je wordt
# niet genoemd", maar "hier staan de pagina's waar je concurrent wel op staat
# en jij niet, en die pagina's bestaan al". Dat zat tot nu toe volledig achter
# de betaalmuur. Iemand die de gratis test deed kreeg een cijfer en een
# probleem, en geen enkele aanwijzing dat wij weten waar het vandaan komt.
#
# Wat het kost. Twee zoekopdrachten is ongeveer een cent, plus het ophalen van
# een stuk of acht pagina's, en dat kost niets bij een AI-aanbieder. Dat is
# goedkoper dan de vijf vragen die er al voor staan.
#
# Wat er met opzet NIET bij zit: de volledige lijst vindplaatsen, de ranglijst
# per concurrent en het bewaren ervan. De gratis test laat zien DAT die
# pagina's er zijn en noemt er hoogstens drie. De rest is het betaalde product.
GRATIS_BRONNEN_AAN = os.environ.get("GRATIS_BRONNEN_AAN", "ja").strip().lower() \
    not in ("nee", "no", "false", "0", "uit")
GRATIS_BRONNEN_VRAGEN = int(os.environ.get("GRATIS_BRONNEN_VRAGEN", "2"))
GRATIS_BRONNEN_PAGINAS = int(os.environ.get("GRATIS_BRONNEN_PAGINAS", "3"))

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


def _bronnen_erbij(webshop_url, beeld, winkelnaam, meting_id):
    """De bronanalyse voor de gratis test, klein gehouden.

    Geeft None terug zodra er iets niet lukt. Dit onderdeel mag de test nooit
    laten mislukken: de uitslag is al af op het moment dat dit draait, en een
    zoekmachine die even dichtzit is geen reden om iemand niets te laten zien.
    """
    if not GRATIS_BRONNEN_AAN:
        return None
    if not bronnen.beschikbaar():
        print(f"Bronanalyse in de gratis test overgeslagen: {bronnen.waarom_niet()}")
        return None

    # Nog een keer langs de rem. De meting hiervoor heeft al geld gekost, dus
    # de dag kan er tussendoor doorheen zijn.
    rem = kosten.mag_doorgaan(webshop_url=webshop_url)
    if not rem["mag"]:
        print(f"Bronanalyse in de gratis test overgeslagen door de rem: {rem['reden']}")
        return None

    profiel = db.get_winkelprofiel(webshop_url) or {}
    m = markt.bepaal(profiel.get("taal"), profiel.get("land"))

    # Minder vragen en minder pagina's dan bij een klant. Tijdelijk, en netjes
    # terug, want bronnen is een module die iedereen deelt en een betalende
    # klant hoort de volle analyse te krijgen.
    was_vragen = bronnen.MAX_VRAGEN_PER_RONDE
    was_paginas = bronnen.MAX_PAGINAS
    try:
        bronnen.MAX_VRAGEN_PER_RONDE = max(1, GRATIS_BRONNEN_VRAGEN)
        bronnen.MAX_PAGINAS = max(1, GRATIS_BRONNEN_PAGINAS)
        vindplaatsen = bronnen.analyseer(
            webshop_url, beeld, winkelnaam=winkelnaam, meting_id=meting_id,
            land=m["zoek_land"], taal=m["zoek_taal"],
        )
    except Exception as e:
        print(f"Bronanalyse in de gratis test mislukt voor {webshop_url}: {e}")
        return None
    finally:
        bronnen.MAX_VRAGEN_PER_RONDE = was_vragen
        bronnen.MAX_PAGINAS = was_paginas

    if not vindplaatsen:
        return None
    try:
        return bronnen.vat_samen(vindplaatsen, winkelnaam)
    except Exception as e:
        print(f"Bronnen samenvatten mislukt voor {webshop_url}: {e}")
        return None


def draai(test_id, webshop_url, aantal_vragen=None, max_aanbieders=None,
          bronnen_erbij=True):
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
            # Met de taal en het land van DEZE winkel. Stond hier eerder
            # zonder, en dan viel het terug op Nederlands. Een winkel uit Texas
            # kreeg dan Nederlandse vragen over Nederlandse webshops. Erger nog:
            # die vragen bleven staan, dus werd hij daarna elke week met de
            # verkeerde taal gemeten zonder dat iemand het merkte.
            profiel = db.get_winkelprofiel(webshop_url) or {}
            m = markt.bepaal(profiel.get("taal"), profiel.get("land"))
            gemaakt = koopvragen.genereer_koopvragen(
                webshop_url, extra, taal=m["taal"], landnaam=m["land"])
            if gemaakt:
                db.bewaar_koopvragen(webshop_url, gemaakt["omschrijving"],
                                     gemaakt["vragen"], winkelnaam=gemaakt.get("naam"))
            vragen = db.get_koopvragen(webshop_url, alleen_actief=True)

        if not vragen:
            db.zet_zichtbaarheidstest(
                test_id, "mislukt",
                foutsoort="Geen koopvragen: de site was niet goed genoeg te lezen.")
            return None

        db.zet_zichtbaarheidstest(test_id, "vragen stellen aan AI")
        samenvatting = metingen.meet_webshop(
            webshop_url,
            max_vragen=aantal_vragen or GRATIS_VRAGEN,
            max_aanbieders=max_aanbieders,
        )
        meting_id = (samenvatting or {}).get("meting_id")
        if not meting_id or not samenvatting.get("gelukt"):
            reden = (samenvatting or {}).get("reden") or "Geen enkel AI-model gaf antwoord."
            db.zet_zichtbaarheidstest(test_id, "mislukt", foutsoort=reden)
            return None

        # Minstens de helft van de vragen moet gelukt zijn. Hier stond alleen
        # "gelukt > 0", en dan gold een test waarbij vier van de vijf vragen
        # mislukten gewoon als geslaagd. De bezoeker las dan "je werd bij 0 van
        # de 1 vragen genoemd", terwijl er op de pagina staat dat het er vijf
        # zijn. Zo'n uitslag wordt ook nog dertig dagen hergebruikt en
        # doorgestuurd, dus een halve meting blijft een maand rondzingen.
        bedoeld = aantal_vragen or GRATIS_VRAGEN
        gelukt = (samenvatting or {}).get("gelukt") or 0
        if gelukt * 2 < bedoeld:
            db.zet_zichtbaarheidstest(
                test_id, "mislukt",
                foutsoort=(f"Maar {gelukt} van de {bedoeld} vragen kwamen door. "
                           f"Te weinig voor een eerlijke uitslag."))
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

        # De bronanalyse hierna, met het volledige klantbeeld. Die heeft de
        # vragen en de concurrenten nodig zoals ze uit de beoordeling komen, en
        # _inkorten gooit precies die velden weg.
        bronbeeld = None
        if bronnen_erbij:
            db.zet_zichtbaarheidstest(test_id, "kijken waar anderen wel staan",
                                      meting_id=meting_id)
            bronbeeld = _bronnen_erbij(webshop_url, beeld, winkelnaam, meting_id)

        beeld = _inkorten(beeld)
        if bronbeeld:
            beeld["bronnen"] = _bronnen_inkorten(bronbeeld)
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


def _bronnen_inkorten(samenvatting):
    """Wat er van de bronanalyse in de gratis uitslag komt.

    Drie pagina's, niet twaalf. Niet uit zuinigheid maar omdat dit het punt is
    waar het betaalde product begint: wij laten zien dat die plekken bestaan en
    hoe ze eruitzien, en de volledige lijst plus de uitgeschreven oplossing per
    pagina is wat je koopt. Wie dit leest weet genoeg om te geloven dat wij het
    weten, en niet genoeg om het zelf af te maken."""
    if not samenvatting:
        return None
    gemist = [
        {
            "titel": g.get("titel") or g.get("domein"),
            "domein": g.get("domein"),
            "concurrenten": (g.get("concurrenten") or [])[:4],
        }
        for g in (samenvatting.get("gemiste_paginas") or [])[:3]
    ]
    return {
        "paginas": samenvatting.get("paginas") or 0,
        "sites": samenvatting.get("sites") or 0,
        "wij_erop": samenvatting.get("wij_erop") or 0,
        "gemist": samenvatting.get("gemist") or 0,
        "conclusie": samenvatting.get("conclusie") or "",
        # Bewust zonder het webadres van de pagina zelf. De domeinnaam staat er
        # wel, dus je ziet waar het over gaat, maar de directe lijst met
        # adressen om aan te werken is het betaalde deel.
        "gemiste_paginas": gemist,
    }


def _winkelnaam(webshop_url):
    """De naam zoals hij in AI-antwoorden staat, niet het domein. In een
    antwoord staat Dille & Kamille en niet dille-kamille.nl.

    Gaat langs dezelfde controle als bij een klant, want een naam als "deze
    webshop" levert overal treffers op die er niet zijn."""
    profiel = db.get_winkelprofiel(webshop_url) or {}
    uit_veld = scan_engine.bruikbare_winkelnaam(profiel.get("winkelnaam"))
    if uit_veld:
        return uit_veld
    omschrijving = profiel.get("omschrijving") or ""
    if " is " in omschrijving:
        return scan_engine.bruikbare_winkelnaam(omschrijving.split(" is ")[0])
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
