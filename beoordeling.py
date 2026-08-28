"""
Krillo - fase 5 stap 4: de antwoorden lezen en beoordelen.

De antwoorden staan al in de database. Hier halen we eruit wat er voor de klant
toe doet. Dat is meer dan tellen of zijn naam ergens voorkomt, want de eerste
echte meting liet drie dingen zien die je niet mag negeren:

1. Winkels en merken staan door elkaar in hetzelfde lijstje. In een antwoord
   over servies staan Serax, HKliving en Ferm Living (merken) naast fonQ,
   Flinders en Loods 5 (winkels). Tel je die op een hoop, dan maak je van een
   merk een concurrent van een webshop, en dat klopt niet.

2. Genoemd worden is niet hetzelfde als aanbevolen worden. Dille en Kamille
   stond in twee antwoorden netjes in de lijst, maar ontbrak in de slotzin
   waarin de AI zegt waar hij echt naar zou kijken. Dat verschil is precies wat
   een klant wil weten. Verkoop je een vermelding als een aanbeveling, dan
   beloof je meer dan je meet.

3. Niet elke vraag kan een winkel opleveren. Vraag je naar merken of naar een
   product, dan komt er geen enkele webshop in het antwoord voor, hoe goed die
   webshop ook is. Zulke vragen mogen niet meetellen in de noemer, anders is
   "genoemd bij 4 van de 30" een misleidend getal.

De positie leggen we wel vast maar wegen we niet mee in een score. Zesde van
negen is iets anders dan eerste, en dat mag je laten zien, maar er een
gewogen cijfer van maken suggereert precisie die er niet is.
"""

import json
import os
import time

import anthropic

import db
import kosten

MODEL = os.environ.get("BEOORDEEL_MODEL", "claude-sonnet-4-6")


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _schoon_json(ruw):
    """Leest de JSON uit het antwoord van een model.

    Bestand tegen een model dat er tekst omheen zet ("Hier is de JSON:") of een
    code-blok gebruikt. Dat gebeurt regelmatig, en zonder deze marge klapte het
    inlezen en telde het antwoord stil als mislukt."""
    ruw = (ruw or "").strip()
    if "```" in ruw:
        stukken = ruw.split("```")
        if len(stukken) > 1:
            ruw = stukken[1]
            if ruw.lstrip().lower().startswith("json"):
                ruw = ruw.lstrip()[4:]
    begin, eind = ruw.find("{"), ruw.rfind("}")
    if begin == -1 or eind <= begin:
        begin, eind = ruw.find("["), ruw.rfind("]")
    if begin != -1 and eind > begin:
        ruw = ruw[begin:eind + 1]
    return json.loads(ruw)


def beoordeel_antwoord(webshop_url, vraag, antwoord, winkelnaam=None):
    """Leest een antwoord en haalt eruit wie er genoemd wordt en hoe.

    winkelnaam is de naam zoals de winkel zichzelf noemt. Die geven we mee
    omdat een domeinnaam als dille-kamille.nl in de tekst als Dille & Kamille
    geschreven staat, en soms als Dille en Kamille of D&K."""
    client = _get_client()
    if client is None or not antwoord:
        return None

    naam_uitleg = f'De winkel die we volgen is "{winkelnaam}" ({webshop_url}).' if winkelnaam \
        else f"De winkel die we volgen heeft als website {webshop_url}."

    prompt = f"""Je leest het antwoord dat een AI-assistent gaf op een koopvraag. Wij meten of
een bepaalde webshop daarin voorkomt, en hoe.

{naam_uitleg}
Let op de schrijfwijze: dezelfde winkel kan met &, met en, met of zonder
spaties of afgekort geschreven zijn. Dat telt allemaal als dezelfde winkel.

De vraag was:
{vraag}

Het antwoord was:
{antwoord}

Haal hier het volgende uit.

WINKELS TEGENOVER MERKEN. Zet een naam alleen bij winkels als je er als
consument iets kan kopen, dus een webshop of een winkelketen. Zet hem bij
merken als het een merk of label is dat via andere winkels verkocht wordt.
Twijfel je, kijk dan naar hoe het antwoord zelf de naam gebruikt. Voorbeelden
ter verduidelijking: fonQ, Loods 5, de Bijenkorf en Flinders zijn winkels.
Serax, HKliving, Ferm Living en Broste Copenhagen zijn merken. Een naam die
allebei is (een merk met een eigen webshop) zet je bij winkels, en dan zet je
ook_merk op true.

KON ER UBERHAUPT EEN WINKEL GENOEMD WORDEN. Vraagt de vraag om een winkel of om
een plek om te kopen, dan is dat ja. Vraagt hij alleen naar merken, producten of
algemene informatie, dan is dat nee, ook als er toevallig toch een winkel
langskomt. Dit bepaalt of deze vraag meetelt in de meting.

AANBEVOLEN OF ALLEEN GENOEMD. Veel antwoorden geven eerst een lange lijst en
sluiten af met een advies, bijvoorbeeld "voor de meest vergelijkbare look zou ik
vooral kijken naar X, Y en Z". Alleen wie in dat slotadvies staat, of wie in de
tekst duidelijk als eerste keuze wordt aangeraden, is aanbevolen. In een rij
staan is genoemd, niet aanbevolen. Zet in aanbevolen_winkels alleen namen die
ook echt winkels zijn. Wordt er in het slotadvies een merk aangeraden, dan hoort
dat daar niet in.

Antwoord ALLEEN met geldige JSON, niets ervoor of erna:

{{
  "winkel_kon_genoemd": true,
  "winkels": [
    {{"naam": "fonQ", "positie": 2, "ook_merk": false}}
  ],
  "merken": ["Serax", "HKliving"],
  "aanbevolen_winkels": ["Loods 5"],
  "onze_winkel": {{
    "genoemd": true,
    "positie": 6,
    "aanbevolen": false,
    "toon": "korte omschrijving van hoe onze winkel neergezet wordt, of null",
    "soort_vermelding": "winkel, product of beide, of null",
    "bewijs": "de zin uit het antwoord waar je dit op baseert, letterlijk overgenomen"
  }}
}}

SOORT VERMELDING. Hier gaat het om wat er precies over onze winkel gezegd
wordt. Drie mogelijkheden:
- "winkel": er wordt gezegd dat je er terecht kan, of de winkel staat in een
  rijtje adressen. Bijvoorbeeld "kijk eens bij Dille & Kamille".
- "product": er wordt een concreet product of productsoort van deze winkel
  aangeraden. Bijvoorbeeld "de emaille mokken van Dille & Kamille" of "een
  thee- en koffiecadeauset van Dille & Kamille".
- "beide": allebei staan er.
Wordt de winkel niet genoemd, zet dan null. Een winkel die alleen in een rijtje
staat met een feitje erachter, zoals "doorgaans 30 dagen retour", is "winkel"
en geen "product".

Het bewijs is verplicht als de winkel genoemd wordt. Neem de zin letterlijk over
uit het antwoord, verzin niets. Zet je aanbevolen op true, neem dan de zin over
waarin de winkel wordt aangeraden. Kan je zo'n zin niet aanwijzen, dan is
aanbevolen false.

De positie is de plek in de opsomming, beginnend bij 1. Komt onze winkel niet
voor, zet dan genoemd op false en positie op null."""

    try:
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            print(f"Beoordelen geblokkeerd door de kostenrem: {rem['reden']}")
            return None

        gestart = time.monotonic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=response.usage.input_tokens,
            uitvoer_tokens=response.usage.output_tokens,
            soort="antwoord-beoordelen",
            webshop_url=webshop_url,
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        data = _schoon_json(response.content[0].text)

        onze = data.get("onze_winkel") or {}
        winkels = [w for w in (data.get("winkels") or []) if isinstance(w, dict) and w.get("naam")]
        return {
            "winkel_kon_genoemd": bool(data.get("winkel_kon_genoemd")),
            "winkels": winkels,
            "merken": [m for m in (data.get("merken") or []) if isinstance(m, str)],
            "aanbevolen_winkels": [a for a in (data.get("aanbevolen_winkels") or []) if isinstance(a, str)],
            "genoemd": bool(onze.get("genoemd")),
            "positie": onze.get("positie") if isinstance(onze.get("positie"), int) else None,
            "aanbevolen": bool(onze.get("aanbevolen")),
            "toon": (onze.get("toon") or None),
            "bewijs": (onze.get("bewijs") or None),
            "soort_vermelding": (onze.get("soort_vermelding")
                                 if onze.get("soort_vermelding") in ("winkel", "product", "beide")
                                 else None),
            "aantal_winkels": len(winkels),
        }
    except Exception as e:
        print(f"Beoordelen mislukt: {e}")
        return None


def beoordeel_ronde(webshop_url, meting_id=None, winkelnaam=None):
    """Beoordeelt alle nog niet beoordeelde antwoorden van een meetronde.

    Al beoordeelde antwoorden worden overgeslagen, dus je kan dit veilig nog
    een keer starten zonder dubbel te betalen."""
    samenvatting = {"bekeken": 0, "gelukt": 0, "mislukt": 0, "gestopt_door_rem": False, "reden": None}

    antwoorden = db.onbeoordeelde_antwoorden(webshop_url, meting_id)
    if not antwoorden:
        samenvatting["reden"] = "Er staan geen onbeoordeelde antwoorden klaar."
        return samenvatting

    print(f"Beoordelen gestart voor {webshop_url}: {len(antwoorden)} antwoorden.")

    for a in antwoorden:
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            samenvatting["gestopt_door_rem"] = True
            samenvatting["reden"] = rem["reden"]
            break

        samenvatting["bekeken"] += 1
        uitkomst = beoordeel_antwoord(webshop_url, a["vraag"], a["antwoord"], winkelnaam)
        if uitkomst is None:
            samenvatting["mislukt"] += 1
            continue

        db.bewaar_beoordeling({
            "antwoord_id": a["id"],
            "meting_id": a["meting_id"],
            "webshop_url": webshop_url,
            "vraag": a["vraag"],
            "intentie": a["intentie"],
            "model": a["model"],
            "winkel_kon_genoemd": uitkomst["winkel_kon_genoemd"],
            "genoemd": uitkomst["genoemd"],
            "positie": uitkomst["positie"],
            "aantal_winkels": uitkomst["aantal_winkels"],
            "aanbevolen": uitkomst["aanbevolen"],
            "toon": uitkomst["toon"],
            "bewijs": uitkomst["bewijs"],
            "soort_vermelding": uitkomst["soort_vermelding"],
            "winkels": json.dumps(uitkomst["winkels"], ensure_ascii=False),
            "merken": json.dumps(uitkomst["merken"], ensure_ascii=False),
            "aanbevolen_winkels": json.dumps(uitkomst["aanbevolen_winkels"], ensure_ascii=False),
        })
        samenvatting["gelukt"] += 1

    print(f"Beoordelen klaar voor {webshop_url}: {samenvatting}")
    return samenvatting


def vat_samen(beoordelingen):
    """Maakt van de losse beoordelingen het beeld dat de klant straks ziet.

    Bewust in aantallen en niet in procenten. Een percentage van dertig vragen
    suggereert een precisie die er niet is, en de roadmap legt dat ook zo vast.
    De noemer is alleen het aantal vragen waar een winkel genoemd kon worden."""
    telbaar = [b for b in beoordelingen if b.get("winkel_kon_genoemd")]
    genoemd = [b for b in telbaar if b.get("genoemd")]
    aanbevolen = [b for b in genoemd if b.get("aanbevolen")]

    # Eerst vaststellen welke namen in deze ronde ergens als winkel herkend
    # zijn. Het slotadvies van een antwoord raadt vaak merken aan, en die
    # mogen niet in een tabel met concurrerende webshops belanden.
    # Kleine letters naar de schrijfwijze zoals hij het eerst voorkwam, zodat
    # dezelfde winkel altijd onder een naam geteld wordt.
    bekende_winkels = {}
    for b in telbaar:
        for w in (b.get("winkels") or []):
            naam = (w.get("naam") or "").strip()
            if naam:
                bekende_winkels.setdefault(naam.lower(), naam)

    concurrenten = {}
    for b in telbaar:
        for w in (b.get("winkels") or []):
            naam = (w.get("naam") or "").strip()
            if not naam:
                continue
            regel = concurrenten.setdefault(naam, {"naam": naam, "genoemd": 0, "aanbevolen": 0})
            regel["genoemd"] += 1
        for naam in (b.get("aanbevolen_winkels") or []):
            naam = (naam or "").strip()
            if not naam:
                continue
            # Koppelen op de schrijfwijze die we al kennen. Het model wisselt
            # tussen "fonQ" en "FonQ", en dan kreeg je twee regels in de tabel:
            # een met de vermeldingen en een met de aanbevelingen.
            bekend = bekende_winkels.get(naam.lower())
            if not bekend:
                continue
            regel = concurrenten.setdefault(bekend, {"naam": bekend, "genoemd": 0, "aanbevolen": 0})
            regel["aanbevolen"] += 1

    posities = [b["positie"] for b in genoemd if b.get("positie")]
    return {
        "product_genoemd": len([b for b in genoemd
                                if b.get("soort_vermelding") in ("product", "beide")]),
        "alleen_winkel": len([b for b in genoemd if b.get("soort_vermelding") == "winkel"]),
        "totaal": len(beoordelingen),
        "telbaar": len(telbaar),
        "niet_telbaar": len(beoordelingen) - len(telbaar),
        "genoemd": len(genoemd),
        "aanbevolen": len(aanbevolen),
        "gemiddelde_positie": round(sum(posities) / len(posities), 1) if posities else None,
        "tonen": [b["toon"] for b in genoemd if b.get("toon")][:6],
        "concurrenten": sorted(
            concurrenten.values(),
            key=lambda c: (c["aanbevolen"], c["genoemd"]),
            reverse=True,
        )[:15],
    }


def toonnaam(model):
    """De naam die een klant herkent. Een modelnaam als gpt-5.6-terra zegt hem
    niets, en die verandert bovendien elke paar maanden."""
    naam = (model or "").lower()
    if naam.startswith("gpt") or naam.startswith("o"):
        return "ChatGPT"
    if naam.startswith("gemini"):
        return "Gemini"
    if naam.startswith("claude"):
        return "Claude"
    return model


def klantbeeld(webshop_url, beoordelingen):
    """Zet de beoordelingen om in wat de klant op zijn eigen pagina ziet.

    Belangrijk verschil met de beheerpagina: daar telt elk antwoord apart, hier
    telt elke VRAAG een keer. Met twee modellen levert dertig vragen zestig
    antwoorden op, en "genoemd bij 8 van de 60" leest alsof er zestig vragen
    gesteld zijn. De klant wil weten bij hoeveel van zijn vragen hij voorkomt.

    Staan de twee modellen niet hetzelfde, dan telt de sterkste uitkomst:
    aanbevolen gaat voor genoemd, genoemd gaat voor niet genoemd. Dat staat er
    ook zo bij op de pagina, anders lees je een cijfer dat strenger of milder
    is dan het lijkt."""
    # Bewust via scan_engine en niet zelf uitrekenen. Dit stond hier als
    # webshop_url.split(".")[0], en sinds normalize_url elk adres met https://
    # begint leverde dat "https://dillekamille" op. De vergelijking daarna was
    # dus altijd onwaar en de eigen winkel van de klant stond als concurrent
    # in zijn eigen tabel.
    import scan_engine

    per_vraag = {}
    for b in beoordelingen:
        vraag = b.get("vraag")
        if not vraag:
            continue
        sterkte = 2 if b.get("aanbevolen") else (1 if b.get("genoemd") else 0)
        regel = per_vraag.get(vraag)
        if regel is None:
            regel = per_vraag[vraag] = {
                "vraag": vraag, "sterkte": -1, "telt_mee": False,
                "genoemd": False, "aanbevolen": False,
                "positie": None, "aantal_winkels": None, "bewijs": None,
                "soort_vermelding": None,
                # De intentie gaat mee omdat de bronanalyse hem nodig heeft.
                # Niet elke koopvraag is even bruikbaar als zoekterm: een vraag
                # over retourbeleid levert pagina's over retourbeleid op, geen
                # pagina's over winkels in die categorie.
                "intentie": b.get("intentie"),
            }
        if b.get("winkel_kon_genoemd"):
            regel["telt_mee"] = True
        if sterkte > regel["sterkte"]:
            regel.update({
                "sterkte": sterkte,
                "genoemd": bool(b.get("genoemd")),
                "aanbevolen": bool(b.get("aanbevolen")),
                "positie": b.get("positie"),
                "aantal_winkels": b.get("aantal_winkels"),
                "bewijs": b.get("bewijs"),
                "soort_vermelding": b.get("soort_vermelding"),
            })

    telbaar = [r for r in per_vraag.values() if r["telt_mee"]]

    # De concurrentietabel telt ook per vraag, net als de cijfers bovenaan.
    # Deed hij dat per antwoord, dan zou onze eigen regel verdubbelen zodra er
    # twee modellen draaien terwijl het cijfer erboven gelijk blijft. Dan staat
    # er 34 in de tabel en 17 in de teller, over precies hetzelfde.
    winkels_per_vraag = {}
    aanbevolen_per_vraag = {}
    bekende_namen = {}
    for b in beoordelingen:
        for w in (b.get("winkels") or []):
            naam = (w.get("naam") or "").strip()
            if naam:
                bekende_namen.setdefault(naam.lower(), naam)
    for b in beoordelingen:
        vraag = b.get("vraag")
        if not vraag or not b.get("winkel_kon_genoemd"):
            continue
        for w in (b.get("winkels") or []):
            naam = (w.get("naam") or "").strip()
            if naam:
                winkels_per_vraag.setdefault(naam, set()).add(vraag)
        for naam in (b.get("aanbevolen_winkels") or []):
            naam = (naam or "").strip()
            # Op kleine letters koppelen aan de naam zoals we hem tellen.
            # Anders belandde "Bijenkorf" niet bij "de Bijenkorf" en kwam de
            # kolom aanbevolen op nul te staan, terwijl daar op gesorteerd
            # wordt en de bronanalyse daarop selecteert.
            bekend = bekende_namen.get(naam.lower()) if naam else None
            if bekend:
                aanbevolen_per_vraag.setdefault(bekend, set()).add(vraag)

    concurrenten = []
    for naam, vragen in winkels_per_vraag.items():
        concurrenten.append({
            "naam": naam,
            "genoemd": len(vragen),
            "aanbevolen": len(aanbevolen_per_vraag.get(naam, ())),
            "wij": scan_engine.is_eigen_winkel(webshop_url, naam),
        })
    concurrenten.sort(key=lambda c: (c["aanbevolen"], c["genoemd"]), reverse=True)

    # Welke modellen hebben deze ronde echt antwoord gegeven. Op de pagina
    # noemen we alleen die, want beloven dat je bij ChatGPT en Gemini meet
    # terwijl er maar een van de twee antwoordde is een belofte te veel.
    modellen = sorted({toonnaam(b.get("model")) for b in beoordelingen if b.get("model")})

    return {
        "gesteld": len(per_vraag),
        "telbaar": len(telbaar),
        "niet_telbaar": len(per_vraag) - len(telbaar),
        "genoemd": len([r for r in telbaar if r["genoemd"]]),
        "aanbevolen": len([r for r in telbaar if r["aanbevolen"]]),
        # Stap 5: een winkel noemen is iets anders dan een product van die
        # winkel aanraden. "Kijk eens bij Dille & Kamille" tegenover "de emaille
        # mokken van Dille & Kamille". Het tweede levert veel eerder een
        # aankoop op, dus dat verschil hoort zichtbaar te zijn.
        "product_genoemd": len([r for r in telbaar
                                if r["genoemd"] and r.get("soort_vermelding") in ("product", "beide")]),
        "concurrenten": concurrenten[:8],
        "modellen": modellen,
        "regels": sorted(telbaar, key=lambda r: (-r["sterkte"], r["vraag"])),
    }
