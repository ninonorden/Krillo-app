"""
Krillo - de benchmark.

Telt op wat er over tientallen webshops gemeten is, zodat er iets te publiceren
valt: "van de tachtig geteste Nederlandse webshops werd de helft bij geen enkele
koopvraag genoemd".

Bewust los van de database, zodat het rekenwerk te testen is zonder dat er een
database hoeft te draaien. db.benchmark_regels() haalt de regels op, dit bestand
doet er sommen mee.

Twee regels die overal in dit bestand gelden, en die dezelfde zijn als op de
klantpagina:

- Tellen per VRAAG en niet per antwoord. Twee modellen die dezelfde vraag
  beantwoorden zijn samen één vraag.
- Winkels waarvoor de meting niet gelukt is tellen niet mee in de noemer. Een
  winkel die we niet konden meten als "niet genoemd" tellen zou het beeld
  somberder maken dan het is, en dat is precies het soort fout waar dit product
  niet mee weg kan komen.
"""


def _bruikbaar(regel):
    """Een winkel telt mee zodra er minstens één bruikbare vraag gemeten is.

    Zonder deze grens zou een winkel waarvan de meting halverwege stukliep als
    'nooit genoemd' in de cijfers belanden."""
    return (regel.get("vragen") or 0) > 0


def tel_op(regels):
    """De cijfers die je publiceert.

    Geeft nooit winkelnamen terug. Losse winkels blijven binnen, het patroon
    gaat naar buiten."""
    alles = list(regels or [])
    gemeten = [r for r in alles if _bruikbaar(r)]

    nooit = [r for r in gemeten if (r.get("genoemd") or 0) == 0]
    soms = [r for r in gemeten if 0 < (r.get("genoemd") or 0)]
    aanbevolen = [r for r in gemeten if (r.get("aanbevolen") or 0) > 0]
    blokkeren = [r for r in alles if r.get("blokkeert_robots")]

    scores = [r["score"] for r in alles if r.get("score") is not None]
    vragen_totaal = sum(r.get("vragen") or 0 for r in gemeten)
    genoemd_totaal = sum(r.get("genoemd") or 0 for r in gemeten)

    return {
        "winkels": len(alles),
        "gemeten": len(gemeten),
        "niet_gelukt": len(alles) - len(gemeten),
        "nooit_genoemd": len(nooit),
        "soms_genoemd": len(soms),
        "ooit_aanbevolen": len(aanbevolen),
        "blokkeren_robots": len(blokkeren),
        "gemiddelde_score": round(sum(scores) / len(scores)) if scores else None,
        "vragen_totaal": vragen_totaal,
        "genoemd_totaal": genoemd_totaal,
    }


def per_platform(regels):
    """Dezelfde optelling, uitgesplitst per winkelplatform.

    Dit beantwoordt de vraag of Shopify-winkels het anders doen dan de rest.
    Platforms met minder dan drie gemeten winkels laten we weg: bij twee
    winkels is elk verschil toeval en zou een uitsplitsing een zekerheid
    suggereren die er niet is."""
    groepen = {}
    for r in regels or []:
        naam = r.get("platform") or "onbekend"
        groepen.setdefault(naam, []).append(r)

    uit = []
    for naam, groep in groepen.items():
        cijfers = tel_op(groep)
        if cijfers["gemeten"] < 3:
            continue
        cijfers["platform"] = naam
        uit.append(cijfers)
    uit.sort(key=lambda c: c["gemeten"], reverse=True)
    return uit


def kernzinnen(cijfers, per_platform_cijfers=None):
    """De zinnen die je letterlijk kan overnemen in een bericht of persmail.

    Alleen zinnen die door de cijfers gedekt worden. Is er te weinig gemeten om
    iets te kunnen zeggen, dan staat er niets. Een benchmark met vier winkels is
    geen benchmark."""
    zinnen = []
    n = cijfers.get("gemeten") or 0
    if n < 10:
        return ["Er zijn nog te weinig winkels gemeten om hier iets over te zeggen. "
                "Vanaf ongeveer dertig winkels wordt het een verhaal dat standhoudt."]

    # Enkelvoud en meervoud kloppend krijgen. Klein detail, maar deze zinnen gaan
    # letterlijk naar de pers en naar een forum, en "1 winkels blokkeert" leest
    # als iets wat door een machine is opgeschreven.
    def werd(aantal):
        return "werd" if aantal == 1 else "werden"

    def winkel_woord(aantal):
        return "winkel" if aantal == 1 else "winkels"

    if cijfers["nooit_genoemd"]:
        aantal = cijfers["nooit_genoemd"]
        zinnen.append(
            f"Van de {n} geteste Nederlandse webshops {werd(aantal)} er {aantal} bij "
            f"geen enkele koopvraag genoemd door ChatGPT of Gemini."
        )
    if cijfers["blokkeren_robots"]:
        aantal = cijfers["blokkeren_robots"]
        werkwoord = "blokkeert" if aantal == 1 else "blokkeren"
        # Bewust "gescande winkels" en niet gewoon "winkels". Deze noemer is het
        # totaal, de zin erboven gebruikt het aantal winkels dat te meten viel.
        # Staan er twee verschillende getallen zonder uitleg naast elkaar in een
        # bericht, dan leest dat als een rekenfout.
        zinnen.append(
            f"{aantal} van de {cijfers['winkels']} gescande "
            f"{winkel_woord(cijfers['winkels'])} {werkwoord} AI-robots in het eigen "
            f"robots.txt-bestand, vrijwel zeker zonder het te weten."
        )
    if cijfers["soms_genoemd"]:
        soms, aanbev = cijfers["soms_genoemd"], cijfers["ooit_aanbevolen"]
        # "slechts" klopt alleen als het er minder zijn. Bij nul en bij alles
        # moet er iets anders staan, anders schrijf je een zin die niet klopt
        # met je eigen cijfers, en dat is precies waar dit product op afgerekend
        # zou worden.
        if aanbev == 0:
            staart = "maar geen daarvan werd bij ook maar één vraag echt aanbevolen"
        elif aanbev == soms:
            staart = "en die werden allemaal bij minstens één vraag ook echt aanbevolen"
        else:
            staart = (f"maar slechts {aanbev} daarvan {werd(aanbev)} bij minstens één vraag "
                      f"ook echt aanbevolen")
        zinnen.append(
            f"{soms} {winkel_woord(soms)} {werd(soms)} wel genoemd, {staart}. "
            f"Genoemd worden is dus iets heel anders dan aangeraden worden."
        )
    if cijfers.get("gemiddelde_score") is not None:
        zinnen.append(
            f"De gemiddelde score op de dertien technische controlepunten was "
            f"{cijfers['gemiddelde_score']} van de 100."
        )

    # De uitsplitsing per platform als één vergelijking, niet als een rijtje
    # losse zinnen. "Van de 10 WooCommerce-winkels werden er 0 nooit genoemd"
    # is een zin die niemand hardop zou zeggen, en bij één platform valt er
    # sowieso niets te vergelijken.
    bekend = [p for p in (per_platform_cijfers or []) if p["platform"] != "onbekend"]
    if len(bekend) >= 2:
        delen = ", ".join(
            f"bij {p['platform']} {p['nooit_genoemd']} van de {p['gemeten']}"
            for p in bekend
        )
        zinnen.append(
            f"Uitgesplitst naar winkelplatform werden nooit genoemd: {delen}."
        )
    elif len(bekend) == 1:
        p = bekend[0]
        aantal = p["nooit_genoemd"]
        zinnen.append(
            f"Van de winkels waarvan we het platform konden herkennen draaiden er "
            f"{p['gemeten']} op {p['platform']}, en daarvan {werd(aantal)} er {aantal} "
            f"nooit genoemd."
        )

    return zinnen
