"""Per verloren koopvraag: wat je concreet doet om hem te winnen (1 oktober 2026).

WAAROM. Nino over de pagina Fixes: "niet echt goede oplossingen, heel
onduidelijk". Klopte. Daar stonden drie algemene taken uit de scan van de site
(vragenpagina, productgegevens, koppen), los van de vragen die de winkel
verliest. En het overzicht beloofde "wat zij wel hebben en jij niet staat bij
je verbeteringen", terwijl daar niets over de concurrent stond.

Nu staat bovenaan Fixes per verloren vraag (eerst de vragen die de klant zelf
koos):
- de vraag, en wie AI in plaats van jou noemde;
- het onderwerp, uit de vraag zelf gehaald ("truffels en truffelproducten");
- drie stappen die bij DIE vraag horen, met dat onderwerp en die namen erin.
Zonder model: het werkt altijd, kost niets, en zegt niets wat we niet weten.
De uitgeschreven teksten (met het model) blijven eronder staan.
"""
import re

# Woorden die in een koopvraag staan maar niets over het product zeggen.
_STOP = set("""
waar wat welke welk wie hoe kan kun ik je jij we wij mijn mij me een de het het en of in op voor van
met bij naar online webshop webshops winkel winkels shop shops kopen koop bestellen bestel bestelt
beste goede goed goedkope goedkoop betaalbare betaalbaar nederland nederlandse belgie belgische
vlaanderen waar's is zijn er te om ook nog meer veel heel echt graag zoek zoeken vinden vind
leveren levert heeft hebben verkoopt verkopen gratis snel snelle verzending thuisbezorgd bezorgd aanraden aanrader raad tip tips
where what which who how can i you we my a an the and or in on for of with at to buy order shop
online store stores best good cheap affordable netherlands belgium is are there also find deliver
""".split())


def onderwerp(vraag):
    """"waar bestel ik online truffels en truffelproducten in Nederland?" wordt
    "truffels en truffelproducten"."""
    woorden = re.findall(r"[\w'-]+", (vraag or "").lower())
    kern = []
    for w in woorden:
        if w in _STOP:
            if kern and w in ("en", "and", "of", "or") :
                kern.append(w)
            continue
        kern.append(w)
    while kern and kern[-1] in ("en", "and", "of", "or"):
        kern.pop()
    while kern and kern[0] in ("en", "and", "of", "or"):
        kern.pop(0)
    return " ".join(kern[:6]) or (vraag or "").strip("? ")


def aanpak(vraag, anderen, landnaam=None, en=True):
    """Drie concrete stappen voor een vraag."""
    o = onderwerp(vraag)
    namen = [n for n in (anderen or []) if n][:2]
    if en:
        stappen = [
            f"Make one page the clear answer: your collection or category page for “{o}”. Put those words "
            f"in the page title and the first sentence, and say plainly that you sell it online"
            + (f" and deliver in {landnaam}." if landnaam else "."),
            f"Add three short questions and answers about {o} on that page: price range, delivery time, and how to "
            f"choose. AI often repeats exactly this kind of text.",
        ]
        if namen:
            stappen.append(f"AI names {' and '.join(namen)} for this question. Open their page about {o} and read "
                           f"the first paragraph: that is usually what AI takes over. Make yours more specific "
                           f"(brands, origin, delivery) rather than longer.")
        else:
            stappen.append("No store is named for this question yet: the first store with a clear page about it "
                           "has a good chance to become the answer.")
    else:
        stappen = [
            f"Maak een pagina het duidelijke antwoord: je collectie- of categoriepagina voor “{o}”. Zet die "
            f"woorden in de paginatitel en de eerste zin, en zeg duidelijk dat je het online verkoopt"
            + (f" en levert in {landnaam}." if landnaam else "."),
            f"Zet drie korte vragen met antwoord over {o} op die pagina: prijsklasse, levertijd en hoe je kiest. AI "
            f"neemt juist zo'n tekst vaak over.",
        ]
        if namen:
            stappen.append(f"AI noemt {' en '.join(namen)} bij deze vraag. Open hun pagina over {o} en lees de eerste "
                           f"alinea: die neemt AI meestal over. Maak die van jou specifieker (merken, herkomst, "
                           f"levering), niet langer.")
        else:
            stappen.append("Er wordt bij deze vraag nog geen winkel genoemd: de eerste met een duidelijke pagina "
                           "erover maakt een goede kans.")
    return {"vraag": vraag, "onderwerp": o, "anderen": namen, "stappen": stappen}


def voor_dashboard(vragen_overzicht, gekozen=None, landnaam=None, en=True, maximaal=3):
    """Uit dashboardpaginas.vragen_overzicht: de verloren vragen, gekozen eerst."""
    gekozen = list(gekozen or [])
    verloren = [v for v in (vragen_overzicht or {}).get("vragen", []) if not v.get("gewonnen")]
    verloren.sort(key=lambda v: (v["vraag"] not in gekozen, gekozen.index(v["vraag"]) if v["vraag"] in gekozen else 0))
    uit = []
    for v in verloren[:maximaal]:
        anderen = []
        for m in v.get("per_model") or []:
            for n in m.get("anderen") or []:
                if n not in anderen:
                    anderen.append(n)
        uit.append(aanpak(v["vraag"], anderen, landnaam, en))
    return uit


def _stam(woord):
    return woord[:5].lower()


def wat_ontbreekt(webshop_url, vraag, haal=None):
    """Een zin over wat er op de winkel ontbreekt voor deze vraag (1 oktober).

    Voorstel van de leeragent, akkoord Nino: in de opvolging na de gratis check
    een alinea die precies zegt welke pagina of tekst ontbreekt, zodat de
    eigenaar meteen ziet wat Watch of Fix aanpakt.

    EERLIJK: we zeggen alleen wat we echt nakeken. We halen de homepage op en
    kijken of er in het menu een link is die over het onderwerp gaat. Dus "we
    vonden geen pagina over X in je menu", nooit "je hebt geen pagina over X".
    Lukt het ophalen niet, dan geen zin (None) in plaats van een gok.

    haal: alleen voor de test (geeft de html van de homepage of None)."""
    import scan_engine
    from bs4 import BeautifulSoup
    o = onderwerp(vraag)
    sleutels = {_stam(w) for w in re.findall(r"[\w'-]+", o) if len(w) >= 4 and w not in ("en", "and")}
    if not sleutels:
        return None
    try:
        if haal:
            html = haal(webshop_url)
        else:
            resp = scan_engine.fetch(webshop_url, pogingen=1)
            html = resp.text if resp is not None else None
    except Exception:
        html = None
    if not html:
        return None
    naam = (webshop_url or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    treffer = None
    for a in BeautifulSoup(html, "html.parser").find_all("a"):
        tekst = " ".join(a.get_text(" ").split())
        if not tekst or len(tekst) > 60:
            continue
        woorden = {_stam(w) for w in re.findall(r"[\w'-]+", tekst) if len(w) >= 4}
        if woorden & sleutels:
            treffer = tekst
            break
    if treffer:
        return (f"Your menu has a page called “{treffer}”, but AI does not use it for this question yet. "
                f"What it misses: the words “{o}” in its title and first sentence, and a few short "
                f"questions and answers. With Watch you get that text written out; with Fix we put it in your store.")
    return (f"We could not find a page about “{o}” in the menu of {naam}. AI needs one clear page "
            f"to point to. With Watch you get that page written out; with Fix we put it in your store.")
