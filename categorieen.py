"""Winkels indelen in categorieen, en tellen of dat genoeg oplevert.

WAAROM DIT BESTAND BESTAAT, EN WAAROM HET HET BELANGRIJKSTE VAN DE HELE OMBOUW IS.

Krillo meet nu per winkel: dertig koopvragen per klant per week, ongeveer tien
euro per klant per maand. Daarmee groeien de kosten even hard mee als de omzet
en loopt het bedrijf vast rond de tienduizend euro omzet.

Het alternatief is per CATEGORIE meten. Vraag "waar koop ik online emaille
servies" een keer, en kijk daarna welke van de tweeenzestig servieswinkels in
dat antwoord voorkomen. Een meting, tweeenzestig uitkomsten. De meetkosten per
winkel gaan dan van tien euro per maand naar ongeveer twee cent.

Dat hangt volledig op een aanname: dat er genoeg winkels per categorie zijn. Bij
vijftig winkels per categorie is de besparing vijftigvoudig. Bij drie winkels
per categorie is er geen besparing en deugt het hele plan niet.

Dit bestand toetst die aanname VOORDAT er iets omgebouwd wordt, en doet daarna
het echte indeelwerk.

DRIE KEUZES DIE HIER GEMAAKT ZIJN, MET REDEN:

1. Een VASTE lijst categorieen, geen vrije tekst. Laat je het model zelf een
   categorie verzinnen, dan krijgt bijna elke winkel zijn eigen categorie
   ("duurzame babykleding van biologisch katoen") en is het hele voordeel weg.
   Liever te breed dan te fijn.

2. In BATCHES van veertig winkels per aanroep. Een aanroep per winkel zou 765
   aanroepen betekenen; zo zijn het er twintig. De hele indeling van je huidige
   lijst kost daarmee ongeveer veertig cent in plaats van tien euro.

3. Twijfelgevallen krijgen "overig" en doen NIET mee aan de index. Een winkel in
   de verkeerde categorie krijgt een positie die niet klopt, en dan ben je in
   een keer al het vertrouwen kwijt dat je met een goede meting opbouwt. Liever
   geen uitspraak dan een verzonnen uitspraak.
"""
import json
import os
import time

import anthropic

import beoordeling
import db
import kosten

# Bewust hetzelfde model als de rest van de tekstverwerking. Door de batches is
# de prijs geen probleem: veertig winkels in een aanroep kost ongeveer twee
# cent, dus de hele lijst van 765 winkels kost minder dan een euro.
MODEL = os.environ.get("CATEGORIE_MODEL", "claude-sonnet-4-6")

# Hoeveel winkels er in een aanroep gaan. Veertig past ruim binnen een
# antwoord van 4096 tekens en houdt de prompt kort genoeg om nauwkeurig te
# blijven. Hoger kan, maar dan gaat het model slordiger indelen.
PER_AANROEP = int(os.environ.get("CATEGORIE_PER_AANROEP", "40"))

# De ondergrens waaronder een categorie niet meedoet aan de openbare index. Een
# ranglijst van vier winkels is geen ranglijst, en zo'n pagina is bij Google
# eerder een blok aan het been dan een klantenstroom.
MINIMUM_VOOR_INDEX = int(os.environ.get("CATEGORIE_MINIMUM", "10"))

# De vaste categorielijst. Afgeleid van de vijftien branches waarin de winkels
# tot nu toe gevonden zijn, uitgesplitst tot het niveau waarop een koopvraag
# zinnig is. "Sport en outdoor" is te breed om er een koopvraag over te stellen,
# "hardlopen" niet.
#
# Een categorie erbij is een regel in deze lijst. Een categorie eraf is NIET
# zomaar een regel weg: winkels die erin zaten moeten dan opnieuw ingedeeld.
# Elke categorie is (slug, naam, ouder). De ouder is waar deze categorie in
# oprolt zolang hij te klein is voor een eigen ranglijst.
#
# WAAROM DIE OUDER ER IS. Bij de eerste echte indeling op 13 september bleek de
# staart te dun: huidverzorging 1 winkel, make-up 1, watersport 1. Zulke
# categorieen halen de tien nooit en vielen daarmee uit de index, terwijl de
# winkels erin prima meetbaar zijn.
#
# Nu rolt een te kleine categorie op in zijn ouder. "Make-up" met een winkel
# telt dan mee in "Cosmetica en verzorging". Groeit make-up later door naar
# tien of meer, dan staat hij vanzelf op eigen benen. Zo hoeft er nooit iemand
# opnieuw ingedeeld te worden als de markt verandert: de indeling blijft fijn,
# alleen de RANGLIJST wordt zo grof als nodig.
#
# De regel in een zin: fijn indelen, grof publiceren, en vanzelf splitsen zodra
# er genoeg winkels zijn.
CATEGORIEEN = [
    ("kleding", "Kleding algemeen", None),
    ("kleding-dames", "Dameskleding", "kleding"),
    ("kleding-heren", "Herenkleding", "kleding"),
    ("kleding-kinderen", "Kinderkleding", "kleding"),
    ("kleding-duurzaam", "Duurzame en biologische kleding", "kleding"),
    ("schoenen", "Schoenen", None),
    ("sieraden", "Sieraden", None),
    ("horloges", "Horloges", "sieraden"),
    ("tassen-lederwaren", "Tassen en lederwaren", None),
    ("wonen-interieur", "Wonen en interieur", None),
    ("meubels", "Meubels", "wonen-interieur"),
    ("verlichting", "Verlichting", None),
    ("beddengoed-textiel", "Beddengoed en woontextiel", "wonen-interieur"),
    ("woondecoratie", "Woondecoratie en accessoires", "wonen-interieur"),
    ("kunst-posters", "Kunst en posters", "wonen-interieur"),
    ("keuken-servies", "Servies en tafelgerei", None),
    ("kookgerei", "Pannen en kookgerei", "keuken-servies"),
    ("koffie-thee", "Koffie en thee", None),
    ("delicatessen", "Delicatessen en speciaalzaken", None),
    ("wijn-drank", "Wijn en sterke drank", "delicatessen"),
    ("chocolade-snoep", "Chocolade en snoep", "delicatessen"),
    ("babyspullen", "Babyspullen en verzorging", None),
    ("kraamcadeaus", "Kraamcadeaus en gepersonaliseerde cadeaus", "babyspullen"),
    ("speelgoed", "Speelgoed", None),
    ("speelgoed-educatief", "Educatief en houten speelgoed", "speelgoed"),
    ("sport-fitness", "Sport en fitness", None),
    ("hardlopen", "Hardlopen", "sport-fitness"),
    ("yoga", "Yoga en pilates", "sport-fitness"),
    ("watersport", "Watersport", "sport-fitness"),
    ("outdoor-kamperen", "Outdoor en kamperen", None),
    ("fietsonderdelen", "Fietsen en onderdelen", None),
    ("wielrennen", "Wielrennen en fietskleding", "fietsonderdelen"),
    ("elektronica", "Elektronica algemeen", None),
    ("audio", "Audio en koptelefoons", None),
    ("computers-accessoires", "Computers en accessoires", "elektronica"),
    ("telefoon-accessoires", "Telefoonhoesjes en accessoires", "elektronica"),
    ("gaming", "Gaming", "elektronica"),
    ("slim-huis", "Slimme huis en domotica", "elektronica"),
    ("cosmetica", "Cosmetica en verzorging", None),
    ("cosmetica-natuurlijk", "Natuurlijke cosmetica", "cosmetica"),
    ("huidverzorging", "Huidverzorging", "cosmetica"),
    ("haarverzorging", "Haarverzorging", "cosmetica"),
    ("parfum", "Parfum", "cosmetica"),
    ("makeup", "Make-up", "cosmetica"),
    ("scheren-baard", "Scheren en baardverzorging", "cosmetica"),
    ("supplementen", "Supplementen en gezondheid", None),
    ("medische-hulpmiddelen", "Medische hulpmiddelen en hulpmiddelen thuis", "supplementen"),
    ("dieren-overig", "Dierbenodigdheden", None),
    ("hond", "Hondenbenodigdheden", "dieren-overig"),
    ("kat", "Kattenbenodigdheden", "dieren-overig"),
    ("kamerplanten", "Kamerplanten", None),
    ("tuin", "Tuin en buitenleven", None),
    ("zaden-bloembollen", "Zaden en bloembollen", "tuin"),
    ("hobby-knutselen", "Hobby en knutselen", None),
    ("breien-haken", "Breien, haken en stoffen", "hobby-knutselen"),
    ("schrijfwaren-kantoor", "Schrijfwaren en kantoor", None),
    ("boeken", "Boeken", None),
    ("muziekinstrumenten", "Muziekinstrumenten", "hobby-knutselen"),
    ("gereedschap", "Gereedschap en klussen", None),
    ("auto-accessoires", "Auto-accessoires", None),
    ("zerowaste", "Duurzaam en zero waste", None),
    ("feestartikelen", "Feestartikelen", None),
    ("reizen-bagage", "Reizen en bagage", None),
    ("erotiek", "Erotiek", None),
    ("overig", "Overig, doet niet mee aan de index", None),
]

# Zodra een categorie hier boven komt, is hij groot genoeg om gesplitst te
# worden in zijn kinderen. Dan wordt een ranglijst van honderd winkels weer
# nietszeggend en hebben de fijnere categorieen meer waarde.
SPLITS_BOVEN = int(os.environ.get("CATEGORIE_SPLITS_BOVEN", "40"))

# ENGELSE NAMEN (24 september). De app, de mails en de gratis check zijn
# Engels, maar lieten de Nederlandse naam zien: "#4 of 23 in Koffie en thee",
# "in the Elektronica algemeen category". Daar nu de Engelse naam. De
# openbare ranglijstpagina's houden bewust de Nederlandse naam, want dat is
# het woord waarop een Nederlandse koper zoekt (zie app.openbare_categorie).
NAMEN_EN = {
    "kleding": "Clothing", "kleding-dames": "Women's clothing", "kleding-heren": "Men's clothing",
    "kleding-kinderen": "Children's clothing", "kleding-duurzaam": "Sustainable clothing",
    "schoenen": "Shoes", "sieraden": "Jewellery", "horloges": "Watches",
    "tassen-lederwaren": "Bags and leather goods", "wonen-interieur": "Home and interior",
    "meubels": "Furniture", "verlichting": "Lighting", "beddengoed-textiel": "Bedding and home textiles",
    "woondecoratie": "Home decor", "kunst-posters": "Art and posters",
    "keuken-servies": "Tableware", "kookgerei": "Cookware", "koffie-thee": "Coffee and tea",
    "delicatessen": "Delicatessen", "wijn-drank": "Wine and spirits",
    "chocolade-snoep": "Chocolate and sweets", "babyspullen": "Baby products",
    "kraamcadeaus": "Baby gifts", "speelgoed": "Toys", "speelgoed-educatief": "Educational toys",
    "sport-fitness": "Sports and fitness", "hardlopen": "Running", "yoga": "Yoga and pilates",
    "watersport": "Water sports", "outdoor-kamperen": "Outdoor and camping",
    "fietsonderdelen": "Bikes and parts", "wielrennen": "Road cycling",
    "elektronica": "Electronics", "audio": "Audio and headphones",
    "computers-accessoires": "Computers and accessories", "telefoon-accessoires": "Phone accessories",
    "gaming": "Gaming", "slim-huis": "Smart home", "cosmetica": "Cosmetics and personal care",
    "cosmetica-natuurlijk": "Natural cosmetics", "huidverzorging": "Skincare",
    "haarverzorging": "Hair care", "parfum": "Perfume", "makeup": "Make-up",
    "scheren-baard": "Shaving and beard care", "supplementen": "Supplements and health",
    "medische-hulpmiddelen": "Medical aids", "dieren-overig": "Pet supplies",
    "hond": "Dog supplies", "kat": "Cat supplies", "kamerplanten": "House plants",
    "tuin": "Garden and outdoor living", "zaden-bloembollen": "Seeds and bulbs",
    "hobby-knutselen": "Hobby and crafts", "breien-haken": "Knitting and fabrics",
    "schrijfwaren-kantoor": "Stationery and office", "boeken": "Books",
    "muziekinstrumenten": "Musical instruments", "gereedschap": "Tools and DIY",
    "auto-accessoires": "Car accessories", "zerowaste": "Zero waste",
    "feestartikelen": "Party supplies", "reizen-bagage": "Travel and luggage",
    "erotiek": "Adult", "overig": "Other",
}


def naam_en(slug):
    """De Engelse naam van een categorie; valt terug op de Nederlandse."""
    return NAMEN_EN.get(slug) or naam_van(slug)


OUDER = {slug: ouder for slug, _, ouder in CATEGORIEEN}

GELDIG = {slug for slug, _, _ in CATEGORIEEN}
NAMEN = {slug: naam for slug, naam, _ in CATEGORIEEN}


def naam_van(slug):
    """De leesbare naam bij een categorie."""
    return NAMEN.get(slug, slug or "onbekend")


def _client():
    sleutel = os.environ.get("ANTHROPIC_API_KEY")
    if not sleutel:
        return None
    return anthropic.Anthropic(api_key=sleutel)


def _prompt(winkels):
    lijst = "\n".join(f"- {slug}: {naam}" for slug, naam, _ in CATEGORIEEN)
    regels = []
    for w in winkels:
        stukken = [w["webshop_url"]]
        if w.get("naam"):
            stukken.append(w["naam"])
        if w.get("branche"):
            stukken.append(f"branche: {w['branche']}")
        if w.get("omschrijving"):
            stukken.append(w["omschrijving"][:280])
        regels.append(" | ".join(stukken))
    winkeltekst = "\n".join(regels)
    return f"""Hieronder staat een lijst webshops en daarboven een vaste lijst categorieen.
Deel elke webshop in bij precies een categorie uit die lijst.

DE CATEGORIEEN:
{lijst}

REGELS:
- Gebruik UITSLUITEND de slugs uit de lijst hierboven. Verzin er geen bij.
- Weet je het niet zeker, of verkoopt de winkel van alles wat, kies dan "overig".
  Een verkeerde categorie is veel erger dan "overig": de winkel krijgt dan een
  positie in een ranglijst waar hij niet thuishoort.
- Kies de categorie waarin de winkel het GROOTSTE deel van zijn omzet haalt, niet
  een hoekje van het assortiment.
- Een winkel die alleen doorverkoopt van AliExpress en overal een beetje van heeft,
  is "overig".

DE WEBSHOPS:
{winkeltekst}

Antwoord met alleen JSON, zonder uitleg eromheen:
{{"indeling": [{{"webshop_url": "...", "categorie": "slug"}}]}}"""


def deel_in(winkels):
    """Deelt een lijst winkels in. Geeft {webshop_url: slug} terug.

    Winkels waar het model niets zinnigs over zegt komen niet in de uitkomst
    voor. Die blijven dus zonder categorie en worden bij een volgende ronde
    opnieuw geprobeerd, in plaats van dat ze stil op "overig" belanden."""
    client = _client()
    if client is None or not winkels:
        return {}

    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        print(f"Indelen geblokkeerd door de kostenrem: {rem['reden']}")
        return {}

    try:
        gestart = time.monotonic()
        antwoord = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": _prompt(winkels)}],
        )
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=antwoord.usage.input_tokens,
            uitvoer_tokens=antwoord.usage.output_tokens,
            soort="winkels-indelen",
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        data = beoordeling._schoon_json(antwoord.content[0].text)
    except Exception as e:
        print(f"Indelen mislukt: {e}")
        return {}

    uit = {}
    for regel in (data or {}).get("indeling", []):
        url = (regel.get("webshop_url") or "").strip()
        slug = (regel.get("categorie") or "").strip()
        # Een verzonnen categorie is erger dan geen categorie: hij zou een
        # ranglijst maken die nergens op slaat. Die gooien wij dus weg.
        if url and slug in GELDIG:
            uit[url] = slug
    return uit


def deel_alles_in(hoeveel=None, opnieuw=False):
    """Deelt de winkels in die nog geen categorie hebben.

    Met opnieuw=True worden ook winkels die al ingedeeld zijn opnieuw bekeken.
    Dat is nodig als de categorielijst verandert.

    Geeft een verslag terug met wat er gebeurd is."""
    winkels = db.winkels_zonder_categorie(hoeveel, opnieuw=opnieuw)
    verslag = {"bekeken": len(winkels), "ingedeeld": 0, "overgeslagen": 0, "aanroepen": 0}
    if not winkels:
        return verslag

    for begin in range(0, len(winkels), PER_AANROEP):
        groep = winkels[begin:begin + PER_AANROEP]
        uitkomst = deel_in(groep)
        verslag["aanroepen"] += 1
        for w in groep:
            slug = uitkomst.get(w["webshop_url"])
            if slug:
                db.zet_categorie(w["webshop_url"], slug)
                verslag["ingedeeld"] += 1
            else:
                verslag["overgeslagen"] += 1
        # Bij een lege uitkomst is er iets mis (rem, sleutel, storing). Dan
        # heeft doorgaan geen zin en kost het alleen geld.
        if not uitkomst:
            verslag["gestopt"] = "geen uitkomst van het model, gestopt na deze groep"
            break
    return verslag


def rol_op(rijen):
    """Rolt te kleine categorieen op in hun ouder.

    Dit is de kern van "fijn indelen, grof publiceren". Een categorie met een
    winkel is geen ranglijst, maar de winkel erin is wel meetbaar. Door hem in
    zijn ouder te laten meetellen doet hij gewoon mee, en zodra zijn eigen
    categorie tien winkels heeft staat die op eigen benen.

    Geeft een lijst terug van {categorie, aantal, met_adres, opgerold_uit}."""
    tel = {r["categorie"]: dict(r, opgerold_uit=[]) for r in rijen
           if r["categorie"] and r["categorie"] != "overig"}

    # Van klein naar groot, zodat een kind eerst in zijn ouder valt en die
    # ouder daarna zelf nog kan doorrollen als hij ook te klein blijft.
    for slug in sorted(tel, key=lambda s: tel[s]["aantal"]):
        regel = tel.get(slug)
        if not regel or regel["aantal"] >= MINIMUM_VOOR_INDEX:
            continue
        ouder = OUDER.get(slug)
        if not ouder:
            continue
        doel = tel.setdefault(ouder, {"categorie": ouder, "aantal": 0,
                                      "met_adres": 0, "opgerold_uit": []})
        doel["aantal"] += regel["aantal"]
        doel["met_adres"] = (doel.get("met_adres") or 0) + (regel.get("met_adres") or 0)
        doel["opgerold_uit"] = doel["opgerold_uit"] + [slug] + regel["opgerold_uit"]
        del tel[slug]

    return sorted(tel.values(), key=lambda r: -r["aantal"])


def telling():
    """De cijfers waarop de go of no-go rust.

    De vraag is niet hoeveel categorieen er zijn, maar hoeveel WINKELS er in een
    ranglijst zitten die groot genoeg is om iets te betekenen. Een indeling met
    tachtig categorieen van drie winkels is een mislukking, ook al ziet de lijst
    er netjes uit."""
    rijen = db.categorie_telling()
    totaal = sum(r["aantal"] for r in rijen)
    zonder = next((r["aantal"] for r in rijen if not r["categorie"]), 0)
    overig = next((r["aantal"] for r in rijen if r["categorie"] == "overig"), 0)
    ingedeeld = sum(r["aantal"] for r in rijen
                    if r["categorie"] and r["categorie"] != "overig")

    na_oprollen = rol_op(rijen)
    bruikbaar = [r for r in na_oprollen if r["aantal"] >= MINIMUM_VOOR_INDEX]
    in_bruikbaar = sum(r["aantal"] for r in bruikbaar)
    te_splitsen = [r for r in bruikbaar if r["aantal"] > SPLITS_BOVEN and r["opgerold_uit"]]

    return {
        "totaal": totaal,
        "zonder_categorie": zonder,
        "overig": overig,
        "ingedeeld": ingedeeld,
        "categorieen": len(na_oprollen),
        "bruikbare_categorieen": len(bruikbaar),
        "winkels_in_bruikbare": in_bruikbaar,
        "aandeel_bruikbaar": round(in_bruikbaar / ingedeeld * 100) if ingedeeld else 0,
        "gemiddeld_per_categorie": round(ingedeeld / len(na_oprollen), 1) if na_oprollen else 0,
        "minimum": MINIMUM_VOOR_INDEX,
        "rijen": na_oprollen,
        "te_splitsen": te_splitsen,
        "geslaagd": bool(ingedeeld) and (in_bruikbaar / ingedeeld) >= 0.5,
    }


def besparing(telling_uitkomst, per_meting_euro=2.50):
    """Wat de categoriemeting scheelt ten opzichte van meten per winkel.

    Dit is de hele reden van de ombouw, dus het hoort op het scherm te staan in
    plaats van in een document."""
    bruikbaar = telling_uitkomst.get("bruikbare_categorieen") or 0
    winkels = telling_uitkomst.get("winkels_in_bruikbare") or 0
    oud = winkels * per_meting_euro
    nieuw = bruikbaar * per_meting_euro
    return {
        "per_winkel_oud": per_meting_euro,
        "per_winkel_nieuw": round(nieuw / winkels, 4) if winkels else 0,
        "ronde_oud": round(oud, 2),
        "ronde_nieuw": round(nieuw, 2),
        "factor": round(oud / nieuw) if nieuw else 0,
    }


# ---------------------------------------------------------------------------
# Het indelen op de achtergrond
#
# WAAROM DIT ER IS, EN WAT ER OP 13 SEPTEMBER MISGING.
#
# De eerste versie deed het indelen tijdens het verzoek zelf. Bij 975 winkels
# zijn dat vierentwintig aanroepen achter elkaar, en die duren samen tien
# minuten. Gunicorn kapt na twee minuten af, dus de werker werd afgeschoten, de
# pagina gaf een storing, en er was maar een deel ingedeeld. Nino moest vier
# keer klikken en twee keer de server herstarten.
#
# Dat is precies dezelfde fout als op 11 september met de kostenpagina: lang
# werk aan een verzoek hangen. De regel die daaruit volgt en die vanaf nu voor
# alles geldt: WERK DAT LANGER DUURT DAN EEN SECONDE OF TIEN HOORT OP EEN EIGEN
# DRAAD, en de pagina laat alleen zien hoe ver het is.
# ---------------------------------------------------------------------------
import threading

_stand = {"bezig": False, "gedaan": 0, "totaal": 0, "aanroepen": 0,
          "overgeslagen": 0, "klaar_op": None, "fout": None}
_slot = threading.Lock()


def stand():
    """Hoe ver het indelen is. Voor de beheerpagina."""
    return dict(_stand)


def _werk(hoeveel, opnieuw):
    try:
        winkels = db.winkels_zonder_categorie(hoeveel, opnieuw=opnieuw)
        _stand["totaal"] = len(winkels)
        for begin in range(0, len(winkels), PER_AANROEP):
            groep = winkels[begin:begin + PER_AANROEP]
            uitkomst = deel_in(groep)
            _stand["aanroepen"] += 1
            for w in groep:
                slug = uitkomst.get(w["webshop_url"])
                if slug:
                    db.zet_categorie(w["webshop_url"], slug)
                    _stand["gedaan"] += 1
                else:
                    _stand["overgeslagen"] += 1
            if not uitkomst:
                # Geen uitkomst betekent een lege sleutel, een storing of de
                # kostenrem. Doorgaan kost dan alleen geld en levert niets op.
                _stand["fout"] = ("Het model gaf niets terug. Gestopt. Kijk of de "
                                  "dagpot op is of er een storing is.")
                break
    except Exception as e:
        _stand["fout"] = f"{type(e).__name__}: {e}"[:200]
        print(f"Indelen op de achtergrond mislukt: {e}")
    finally:
        _stand["bezig"] = False
        _stand["klaar_op"] = time.time()
        print(f"Indelen klaar: {_stand}")


def start_indelen(hoeveel=None, opnieuw=False):
    """Start het indelen op een eigen draad. Geeft terug of hij gestart is.

    Twee keer starten kan niet: dan zou dezelfde winkel twee keer ingedeeld
    worden en twee keer betaald."""
    with _slot:
        if _stand["bezig"]:
            return False
        _stand.update({"bezig": True, "gedaan": 0, "totaal": 0, "aanroepen": 0,
                       "overgeslagen": 0, "klaar_op": None, "fout": None})
    threading.Thread(target=_werk, args=(hoeveel, opnieuw), daemon=True).start()
    return True
