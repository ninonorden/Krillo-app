"""Het werk zelf doen in de winkel, in plaats van huiswerk uitdelen.

Dit is het verschil tussen Krillo en een scan-tool. Een scan zegt "je mist
beschrijvingen bij je afbeeldingen". Dat weet de eigenaar dan, en er verandert
niets, want hij heeft geen idee waar dat moet en zeventig producten.

Hier maken wij de tekst en zetten wij hem erin, met een knop.

Drie regels waar dit bestand zich aan houdt, en die belangrijker zijn dan wat
het bestand kan:

1. Wij tonen eerst wat er komt te staan. Nooit iets schrijven dat de eigenaar
   niet gezien heeft.
2. Wij bewaren de oude waarde VOORDAT wij schrijven. Lukt het bewaren niet,
   dan schrijven wij niet. Een wijziging die niet terug kan is erger dan geen
   wijziging.
3. Wij overschrijven nooit werk van iemand anders. Een afbeelding met een
   beschrijving laten wij met rust, een producttekst die er al staat ook. Wij
   vullen alleen aan waar het leeg is.

De winkel is van hem, niet van ons.
"""

import html
import json
import os
import re
import time

import requests

import db
import kosten
import shopify_app

MODEL = "claude-sonnet-4-6"

# Onder dit aantal leestekens noemen wij een producttekst leeg. Een tekst van
# veertig tekens is meestal "Mooie kaars." en daar kan een AI-assistent niets
# mee: geen materiaal, geen maat, geen gebruik.
TEKST_ONDERGRENS = 180

# Hoeveel producten wij hoogstens nakijken. Ruim genoeg voor bijna elke kleine
# winkel. Bij meer dan dit zeggen wij op het scherm hoeveel er nog wachten, in
# plaats van te doen alsof we klaar zijn.
PRODUCTEN_PER_KEER = 1000

# Hoeveel voorstellen wij maximaal in één keer laten maken. De eigenaar moet ze
# stuk voor stuk kunnen nakijken; een lijst van honderd kijkt niemand na.
VOORSTELLEN_PER_KEER = 12

# Hoeveel wijzigingen wij gratis in een winkel zetten.
#
# Waarom niet nul en waarom niet alles: een onbekende app met nul beoordelingen
# krijgt niemand zover om eerst te betalen voor een belofte. Maar iemand die
# ziet dat er echt drie teksten in zijn winkel staan die hij zelf niet had, en
# daarna leest dat er nog zevenenveertig klaarstaan, snapt meteen waar hij voor
# betaalt. Laten zien in plaats van vertellen, dat is het hele idee.
GRATIS_WIJZIGINGEN = 3


FAQ_HANDLE = "veelgestelde-vragen-krillo"

# Hoe lang wij wachten als Shopify zegt dat het te druk is, en hoe vaak wij het
# daarna nog proberen. GraphQL heeft geen losse verzoeken per seconde maar een
# emmer met punten: is die leeg, dan komt er een fout THROTTLED terug in plaats
# van een foutcode 429. Even wachten en het nog eens proberen is dan genoeg,
# want de emmer loopt vanzelf weer vol.
WACHT_BIJ_DRUKTE = 2
POGINGEN_BIJ_DRUKTE = 3

# Hoeveel foto's wij per product bekijken. Meer dan dit heeft bijna geen enkele
# winkel, en elk stuk dat je opvraagt kost punten uit diezelfde emmer.
FOTOS_PER_PRODUCT = 50


# ---------------------------------------------------------------- de winkel in

def _graphql(winkel, sleutel, vraag, variabelen=None):
    """Eén plek waar wij met de winkel praten, zodat fouten er ook maar op één
    plek uit kunnen komen.

    Alles gaat sinds april 2025 via de GraphQL-ingang. Shopify neemt geen
    nieuwe apps meer aan die de oude REST-ingang gebruiken, dus dit is geen
    smaakkwestie. Er is één adres (graphql.json) en één manier van vragen.

    Let op het verschil tussen twee soorten fouten. Een kapotte vraag of een
    lege emmer komt terug in "errors" bovenin, met een gewone code 200 ervoor.
    Alleen daarop kijken naar de HTTP-code zou dus betekenen dat wij een
    mislukking voor een succes aanzien."""
    winkel = shopify_app._schoon(winkel)
    if not shopify_app.geldige_winkel(winkel) or not sleutel:
        return {"gelukt": False, "fout": "Geen geldige winkel of sleutel."}
    url = f"https://{winkel}/admin/api/{shopify_app.API_VERSIE}/graphql.json"
    laatste = "Onbekende fout."
    for poging in range(POGINGEN_BIJ_DRUKTE):
        try:
            antwoord = requests.post(
                url, headers=shopify_app._kop(sleutel),
                json={"query": vraag, "variables": variabelen or {}}, timeout=25)
        except Exception as e:
            return {"gelukt": False, "fout": f"{type(e).__name__}: {e}"[:250]}
        if antwoord.status_code == 429:
            laatste = "Shopify gaf 429: te veel verzoeken."
            time.sleep(WACHT_BIJ_DRUKTE)
            continue
        if antwoord.status_code >= 300:
            return {"gelukt": False,
                    "fout": f"Shopify gaf {antwoord.status_code}: {antwoord.text[:200]}"}
        try:
            gegevens = antwoord.json() or {}
        except Exception:
            return {"gelukt": False, "fout": "Shopify gaf geen leesbaar antwoord."}
        fouten = gegevens.get("errors") or []
        if fouten:
            if _is_te_druk(fouten) and poging < POGINGEN_BIJ_DRUKTE - 1:
                time.sleep(WACHT_BIJ_DRUKTE)
                laatste = "Shopify had het te druk."
                continue
            return {"gelukt": False, "fout": _foutregel(fouten)}
        return {"gelukt": True, "gegevens": gegevens.get("data") or {}}
    return {"gelukt": False, "fout": laatste}


def _is_te_druk(fouten):
    """Zegt Shopify hier dat de emmer leeg is?

    De code staat bij elke fout onder "extensions". Wij kijken ook naar de
    tekst zelf, want bij sommige antwoorden komt alleen "Throttled" mee."""
    for fout in fouten or []:
        code = ((fout or {}).get("extensions") or {}).get("code") or ""
        if str(code).upper() == "THROTTLED":
            return True
        if "throttl" in str((fout or {}).get("message") or "").lower():
            return True
    return False


def _foutregel(fouten):
    """Van de foutenlijst één leesbare regel maken voor op het scherm."""
    regels = [str((f or {}).get("message") or f) for f in (fouten or [])]
    return ("Shopify: " + "; ".join(regels))[:300] if regels else "Shopify gaf een fout."


def _muteer(winkel, sleutel, vraag, variabelen, naam):
    """Een wijziging versturen en het antwoord echt nakijken.

    Dit is de valkuil van GraphQL: een mutatie die niets doet geeft nog steeds
    een keurige code 200 terug. Wat er mis ging staat in "userErrors" binnenin.
    Wie daar niet naar kijkt, meldt aan de eigenaar dat het gelukt is terwijl
    er niets veranderd is. Daarom komt hier hetzelfde soort antwoord uit als
    bij een echte fout: {"gelukt": False, "fout": ...}."""
    uit = _graphql(winkel, sleutel, vraag, variabelen)
    if not uit["gelukt"]:
        return uit
    stuk = (uit.get("gegevens") or {}).get(naam) or {}
    problemen = stuk.get("userErrors") or []
    if problemen:
        regels = []
        for p in problemen:
            veld = ".".join(str(x) for x in (p.get("field") or []) if x)
            bericht = str(p.get("message") or "").strip() or "onbekende fout"
            regels.append(f"{veld}: {bericht}" if veld else bericht)
        return {"gelukt": False, "fout": ("Shopify: " + "; ".join(regels))[:300]}
    return {"gelukt": True, "gegevens": stuk}


# --------------------------------------------------------------- nummers en gid

def _nummer(gid):
    """Uit "gid://shopify/Product/123" halen wij 123.

    Wij hebben dit nodig omdat de kenmerken van voorstellen
    (shopify:alt:1:11 en shopify:tekst:1) al zo in de database staan bij
    wijzigingen die eerder gemaakt zijn. Zouden wij daar nu een heel gid in
    zetten, dan is een oude wijziging niet meer terug te zetten. De vorm van
    het kenmerk blijft dus zoals hij was, en het lange gid maken wij weer aan
    op het moment dat wij hem nodig hebben."""
    tekst = str(gid if gid is not None else "").strip()
    if "/" in tekst:
        tekst = tekst.rstrip("/").split("/")[-1]
    tekst = tekst.split("?")[0]
    return int(tekst) if tekst.isdigit() else tekst


def _gid(soort, nummer):
    """Van 123 weer "gid://shopify/Product/123" maken.

    Geven wij er al een gid in, dan laten wij hem met rust. Zo kan deze functie
    zowel over een nummer uit een kenmerk als over iets dat rechtstreeks uit
    Shopify komt heen."""
    tekst = str(nummer if nummer is not None else "").strip()
    if tekst.startswith("gid://"):
        return tekst
    return f"gid://shopify/{soort}/{_nummer(tekst)}"


# ------------------------------------------------------------------ ophalen

VRAAG_PRODUCTEN = """
query Producten($aantal: Int!, $vanaf: String, $fotos: Int!) {
  products(first: $aantal, after: $vanaf) {
    nodes {
      id
      title
      handle
      descriptionHtml
      productType
      vendor
      tags
      media(first: $fotos) {
        nodes {
          id
          alt
          ... on MediaImage { image { url } }
        }
      }
      variants(first: 1) { nodes { price } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

VRAAG_PAGINAS = """
query Paginas($aantal: Int!, $vanaf: String) {
  pages(first: $aantal, after: $vanaf) {
    nodes { id title handle body }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _product_naar_dict(knoop):
    """Een product uit GraphQL in dezelfde vorm gieten als voorheen.

    Waarom wij dat doen: de rest van dit bestand, en het scherm dat erop
    volgt, werkt met body_html, product_type en images. Alleen het praten met
    de winkel is veranderd, niet wat wij ermee doen. Door de vorm hier één
    keer gelijk te trekken hoeft er verderop niets aangepast te worden, en dat
    scheelt een hoop plekken waar iets stuk kan gaan.

    Labels komen bij GraphQL als lijst terug en bij de oude ingang als één
    regel met komma's. Wij maken er weer een regel van, want die gaat zo naar
    het model toe."""
    fotos = []
    for media in ((knoop.get("media") or {}).get("nodes") or []):
        # Een product kan ook een filmpje of een 3D-model bevatten. Daar hoort
        # geen fotobeschrijving bij, dus die laten wij liggen.
        if "MediaImage" not in str(media.get("id") or ""):
            continue
        fotos.append({
            "id": _nummer(media.get("id")),
            "alt": media.get("alt") or "",
            "src": ((media.get("image") or {}).get("url")) or "",
        })
    prijzen = [{"price": v.get("price")}
               for v in ((knoop.get("variants") or {}).get("nodes") or [])]
    labels = knoop.get("tags")
    if isinstance(labels, list):
        labels = ", ".join(str(x) for x in labels)
    return {
        "id": _nummer(knoop.get("id")),
        "title": knoop.get("title") or "",
        "handle": knoop.get("handle") or "",
        "body_html": knoop.get("descriptionHtml") or "",
        "product_type": knoop.get("productType") or "",
        "vendor": knoop.get("vendor") or "",
        "tags": labels or "",
        "images": fotos,
        "variants": prijzen or [{}],
    }


def haal_producten(winkel, sleutel, maximaal=PRODUCTEN_PER_KEER):
    """Alle producten, in stukken van 250.

    Haalde hiervoor één pagina op. Een winkel met zeventig producten kreeg dus
    alleen voorstellen voor de eerste veertig, drukte op de knop, drukte nog
    eens, en kreeg weer diezelfde veertig. De producten daarna werden nooit
    bekeken, terwijl op het scherm staat dat wij de ontbrekende teksten
    invullen. Dan denkt iemand dat hij klaar is terwijl de helft leeg staat.

    Bladeren gaat bij GraphQL met een merkteken (endCursor) in plaats van met
    het laatste nummer. Dat is geen verschil in gedrag, alleen in de manier
    waarop je om het volgende stuk vraagt."""
    alles, vanaf = [], None
    while len(alles) < maximaal:
        aantal = min(250, maximaal - len(alles))
        uit = _graphql(winkel, sleutel, VRAAG_PRODUCTEN,
                       {"aantal": aantal, "vanaf": vanaf,
                        "fotos": FOTOS_PER_PRODUCT})
        if not uit["gelukt"]:
            print(f"Producten ophalen mislukt voor {winkel}: {uit['fout']}")
            break
        blok = ((uit.get("gegevens") or {}).get("products") or {})
        stuk = blok.get("nodes") or []
        if not stuk:
            break
        alles.extend(_product_naar_dict(p) for p in stuk)
        info = blok.get("pageInfo") or {}
        vanaf = info.get("endCursor")
        if not info.get("hasNextPage") or not vanaf:
            break
    return alles[:maximaal]


def haal_paginas(winkel, sleutel):
    """De pagina's van de winkel, in dezelfde vorm als voorheen.

    Het veld heet bij GraphQL "body" en bij de oude ingang "body_html". Wij
    houden body_html aan, want daar rekent de rest van de app op."""
    alles, vanaf = [], None
    while len(alles) < 250:
        uit = _graphql(winkel, sleutel, VRAAG_PAGINAS,
                       {"aantal": min(250, 250 - len(alles)), "vanaf": vanaf})
        if not uit["gelukt"]:
            return alles
        blok = ((uit.get("gegevens") or {}).get("pages") or {})
        stuk = blok.get("nodes") or []
        if not stuk:
            break
        for pg in stuk:
            alles.append({"id": _nummer(pg.get("id")), "title": pg.get("title") or "",
                          "handle": pg.get("handle") or "",
                          "body_html": pg.get("body") or ""})
        info = blok.get("pageInfo") or {}
        vanaf = info.get("endCursor")
        if not info.get("hasNextPage") or not vanaf:
            break
    return alles


# ------------------------------------------------------------ wat er mis is

def _kale_tekst(rommel):
    """HTML eruit, zodat wij de lengte van de echte tekst meten en niet die van
    de opmaak. Een lege alinea in Shopify is zo honderd tekens aan tags."""
    tekst = re.sub(r"<[^>]+>", " ", rommel or "")
    tekst = html.unescape(tekst)
    return re.sub(r"\s+", " ", tekst).strip()


def _productlink(winkel, product_id):
    return f"https://{shopify_app._schoon(winkel)}/admin/products/{product_id}"


def zoek_gebreken(winkel, sleutel):
    """Wat er in deze winkel ontbreekt, zonder er al tekst voor te maken.

    Dit is bewust gescheiden van het schrijven. Zoeken kost niets, schrijven
    kost geld bij het model. Zo kunnen wij de eigenaar eerst laten zien hoeveel
    er is voordat wij ook maar één opdracht versturen."""
    producten = haal_producten(winkel, sleutel)
    paginas = haal_paginas(winkel, sleutel)

    zonder_alt, dunne_tekst = [], []
    for p in producten:
        for afbeelding in (p.get("images") or []):
            if not (afbeelding.get("alt") or "").strip():
                zonder_alt.append({
                    "product_id": p["id"], "afbeelding_id": afbeelding["id"],
                    "titel": p.get("title") or "", "src": afbeelding.get("src") or "",
                    "soort": p.get("product_type") or "", "merk": p.get("vendor") or "",
                })
        if len(_kale_tekst(p.get("body_html"))) < TEKST_ONDERGRENS:
            dunne_tekst.append({
                "product_id": p["id"], "titel": p.get("title") or "",
                "soort": p.get("product_type") or "", "merk": p.get("vendor") or "",
                "tags": p.get("tags") or "", "huidig": _kale_tekst(p.get("body_html")),
                "prijs": ((p.get("variants") or [{}])[0] or {}).get("price"),
            })

    heeft_faq = any(
        re.search(r"faq|veelgestelde|vragen", (pg.get("handle") or "") + " " + (pg.get("title") or ""),
                  re.I)
        for pg in paginas)

    return {
        "producten_bekeken": len(producten),
        "zonder_alt": zonder_alt,
        "dunne_tekst": dunne_tekst,
        "heeft_faq": heeft_faq,
        "paginas": len(paginas),
        "voorbeeldproducten": [
            {"titel": p.get("title"), "soort": p.get("product_type"),
             "tekst": _kale_tekst(p.get("body_html"))[:400]}
            for p in producten[:8]],
    }


# ---------------------------------------------------------------- het schrijven

def _model(webshop_url):
    try:
        import anthropic
    except Exception:
        return None, "De bibliotheek van het model ontbreekt op de server."
    sleutel = os.environ.get("ANTHROPIC_API_KEY")
    if not sleutel:
        return None, "ANTHROPIC_API_KEY staat niet ingesteld."
    rem = kosten.mag_doorgaan(webshop_url=webshop_url)
    if not rem["mag"]:
        return None, f"Kostenrem: {rem['reden']}"
    return anthropic.Anthropic(api_key=sleutel), None


def _vraag_json(client, prompt, webshop_url, soort, max_tokens=4000):
    gestart = time.monotonic()
    antwoord = client.messages.create(
        model=MODEL, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    try:
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=antwoord.usage.input_tokens,
            uitvoer_tokens=antwoord.usage.output_tokens,
            soort=soort, webshop_url=webshop_url,
            duur_ms=int((time.monotonic() - gestart) * 1000))
    except Exception as e:
        print(f"Kosten vastleggen mislukt ({soort}): {e}")
    ruw = (antwoord.content[0].text or "").strip()
    if ruw.startswith("```"):
        stukken = ruw.split("```")
        ruw = stukken[1] if len(stukken) > 1 else ruw
        if ruw.startswith("json"):
            ruw = ruw[4:]
    begin, eind = ruw.find("["), ruw.rfind("]")
    if begin == -1 or eind <= begin:
        begin, eind = ruw.find("{"), ruw.rfind("}")
    if begin == -1 or eind <= begin:
        raise ValueError("Het model gaf geen bruikbaar antwoord terug.")
    return json.loads(ruw[begin:eind + 1])


def _taalregel(markt):
    taal = (markt or {}).get("taal") or "Nederlands"
    return (f"Schrijf alles in het {taal}, in de taal van de winkel zelf. "
            f"Gebruik gewone woorden, geen vakjargon, en geen gedachtestreepjes.")


def maak_alt_voorstellen(winkel, sleutel, gebreken, markt, hoeveel=VOORSTELLEN_PER_KEER):
    """Beschrijvingen bij afbeeldingen die er geen hebben.

    Waarom dit ertoe doet: een AI-assistent leest geen plaatje. Staat er niets
    bij, dan is een productfoto voor hem een lege plek op de pagina."""
    lijst = (gebreken.get("zonder_alt") or [])[:hoeveel]
    if not lijst:
        return {"gelukt": True, "voorstellen": []}
    client, fout = _model(winkel)
    if not client:
        return {"gelukt": False, "fout": fout, "voorstellen": []}

    regels = [{"nummer": i, "product": r["titel"], "soort": r["soort"], "merk": r["merk"]}
              for i, r in enumerate(lijst)]
    prompt = f"""Je schrijft korte beschrijvingen bij productfoto's van een webwinkel.

{_taalregel(markt)}

Per foto één zin van hooguit twaalf woorden die zegt wat er te zien is.
Noem het product en waar het van gemaakt of voor bedoeld is, als dat uit de
naam blijkt. Verzin niets: geen kleuren, maten of materialen die er niet staan.
Begin niet met "Foto van" of "Afbeelding van".

De producten:
{json.dumps(regels, ensure_ascii=False, indent=1)}

Antwoord ALLEEN met een JSON-lijst, niets ervoor of erna:
[{{"nummer": 0, "tekst": "..."}}]
"""
    try:
        uit = _vraag_json(client, prompt, winkel, "shopify-alt", max_tokens=2000)
    except Exception as e:
        return {"gelukt": False, "fout": f"{type(e).__name__}: {e}"[:250], "voorstellen": []}

    voorstellen = []
    for regel in uit if isinstance(uit, list) else []:
        try:
            bron = lijst[int(regel["nummer"])]
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        tekst = (regel.get("tekst") or "").strip()[:250]
        if not tekst:
            continue
        voorstellen.append({
            "id": f"shopify:alt:{bron['product_id']}:{bron['afbeelding_id']}",
            "soort": "alt",
            "wat": "Beschrijving bij een productfoto",
            "waar": f"{bron['titel']} (foto)",
            "link": _productlink(winkel, bron["product_id"]),
            "afbeelding": bron["src"],
            "oud": "",
            "nieuw": tekst,
            "product_id": bron["product_id"],
            "afbeelding_id": bron["afbeelding_id"],
        })
    return {"gelukt": True, "voorstellen": voorstellen}


def maak_tekst_voorstellen(winkel, sleutel, gebreken, markt, hoeveel=6):
    """Productteksten voor producten die er (bijna) geen hebben.

    Wij vullen alleen aan waar het leeg is. Staat er al een tekst van de
    eigenaar, dan blijft die staan, ook als wij hem beter zouden kunnen."""
    lijst = [r for r in (gebreken.get("dunne_tekst") or [])][:hoeveel]
    if not lijst:
        return {"gelukt": True, "voorstellen": []}
    client, fout = _model(winkel)
    if not client:
        return {"gelukt": False, "fout": fout, "voorstellen": []}

    regels = [{"nummer": i, "product": r["titel"], "soort": r["soort"],
               "merk": r["merk"], "labels": r["tags"], "staat_er_nu": r["huidig"]}
              for i, r in enumerate(lijst)]
    prompt = f"""Je schrijft productteksten voor een webwinkel.

{_taalregel(markt)}

Per product drie tot vijf zinnen. Zeg wat het is, voor wie het bedoeld is en
wanneer je het gebruikt. Dat is wat een AI-assistent nodig heeft om dit product
aan iemand aan te raden.

Heel belangrijk: verzin geen feiten. Geen maten, gewichten, materialen,
garantietermijnen, keurmerken of levertijden die je niet uit de naam of de
bestaande tekst kunt afleiden. Liever een korte tekst die klopt dan een lange
die niet klopt. Schrijf ook geen superlatieven ("het beste", "topkwaliteit").

Gewone tekst, geen opmaaktekens, geen kopjes.

De producten:
{json.dumps(regels, ensure_ascii=False, indent=1)}

Antwoord ALLEEN met een JSON-lijst, niets ervoor of erna:
[{{"nummer": 0, "tekst": "..."}}]
"""
    try:
        uit = _vraag_json(client, prompt, winkel, "shopify-producttekst", max_tokens=4000)
    except Exception as e:
        return {"gelukt": False, "fout": f"{type(e).__name__}: {e}"[:250], "voorstellen": []}

    voorstellen = []
    for regel in uit if isinstance(uit, list) else []:
        try:
            bron = lijst[int(regel["nummer"])]
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        tekst = (regel.get("tekst") or "").strip()
        if len(tekst) < 40:
            continue
        alineas = "".join(f"<p>{html.escape(s.strip())}</p>"
                          for s in tekst.split("\n") if s.strip())
        voorstellen.append({
            "id": f"shopify:tekst:{bron['product_id']}",
            "soort": "tekst",
            "wat": "Producttekst",
            "waar": bron["titel"],
            "link": _productlink(winkel, bron["product_id"]),
            "afbeelding": "",
            "oud": bron["huidig"],
            "nieuw": tekst,
            "nieuw_html": alineas,
            "product_id": bron["product_id"],
        })
    return {"gelukt": True, "voorstellen": voorstellen}


def maak_faq_voorstel(winkel, sleutel, gebreken, markt):
    """Een pagina met veelgestelde vragen.

    Dit is de enige plek waar wij iets nieuws maken in plaats van iets
    aanvullen. Heeft de winkel al zo'n pagina, dan doen wij niets."""
    if gebreken.get("heeft_faq"):
        return {"gelukt": True, "voorstellen": []}
    client, fout = _model(winkel)
    if not client:
        return {"gelukt": False, "fout": fout, "voorstellen": []}

    prompt = f"""Je schrijft een pagina met veelgestelde vragen voor een webwinkel.

{_taalregel(markt)}

Zes vragen met een antwoord van twee tot vier zinnen. Vragen die een klant
echt stelt voordat hij bestelt: wat verkopen jullie precies, voor wie is dit
bedoeld, hoe kies ik het juiste, hoe zit het met bestellen, hoe kom ik in
contact.

Heel belangrijk: schrijf GEEN antwoorden over levertijd, verzendkosten,
retourtermijn, garantie of betaalmethoden. Die cijfers weet je niet en een
verkeerd getal op de eigen site van een winkel is schadelijk. Blijf bij wat je
uit de producten hieronder kunt afleiden, en verwijs voor de rest naar de
contactpagina.

Wat deze winkel verkoopt:
{json.dumps(gebreken.get("voorbeeldproducten") or [], ensure_ascii=False, indent=1)}

Antwoord ALLEEN met een JSON-lijst, niets ervoor of erna:
[{{"vraag": "...", "antwoord": "..."}}]
"""
    try:
        uit = _vraag_json(client, prompt, winkel, "shopify-faq", max_tokens=3000)
    except Exception as e:
        return {"gelukt": False, "fout": f"{type(e).__name__}: {e}"[:250], "voorstellen": []}

    paren = [(str(r.get("vraag") or "").strip(), str(r.get("antwoord") or "").strip())
             for r in (uit if isinstance(uit, list) else [])]
    paren = [(v, a) for v, a in paren if v and a]
    if not paren:
        return {"gelukt": False, "fout": "Het model gaf geen vragen terug.", "voorstellen": []}

    body = "".join(f"<h2>{html.escape(v)}</h2><p>{html.escape(a)}</p>" for v, a in paren)
    leesbaar = "\n\n".join(f"{v}\n{a}" for v, a in paren)
    return {"gelukt": True, "voorstellen": [{
        "id": "shopify:faq",
        "soort": "faq",
        "wat": "Nieuwe pagina met veelgestelde vragen",
        "waar": "Winkel, Pagina's",
        "link": f"https://{shopify_app._schoon(winkel)}/admin/pages",
        "afbeelding": "",
        "oud": "",
        "nieuw": leesbaar,
        "nieuw_html": body,
    }]}


def maak_voorstellen(winkel, sleutel, markt=None):
    """Alles bij elkaar: kijken wat er mis is en er tekst voor maken.

    Er gaat hier nog niets de winkel in. Dit is wat de eigenaar te zien krijgt
    voordat hij op de knop drukt."""
    gebreken = zoek_gebreken(winkel, sleutel)
    alles, fouten = [], []
    for stuk in (maak_faq_voorstel(winkel, sleutel, gebreken, markt),
                 maak_tekst_voorstellen(winkel, sleutel, gebreken, markt),
                 maak_alt_voorstellen(winkel, sleutel, gebreken, markt)):
        alles.extend(stuk.get("voorstellen") or [])
        if not stuk.get("gelukt") and stuk.get("fout"):
            fouten.append(stuk["fout"])
    # Hoeveel er nu nog blijven liggen. Wij maken per keer een behapbaar aantal
    # voorstellen, want honderd voorstellen kijkt niemand na. Maar dan moet er
    # wel staan hoeveel er nog wachten, anders denkt de eigenaar dat hij klaar
    # is terwijl er nog zestig producten zonder tekst staan.
    gemaakt_per_soort = {}
    for stuk in alles:
        gemaakt_per_soort[stuk["soort"]] = gemaakt_per_soort.get(stuk["soort"], 0) + 1
    rest = (max(0, len(gebreken["zonder_alt"]) - gemaakt_per_soort.get("alt", 0))
            + max(0, len(gebreken["dunne_tekst"]) - gemaakt_per_soort.get("tekst", 0)))

    return {"gebreken": {k: v for k, v in gebreken.items() if k != "voorbeeldproducten"},
            "aantallen": {"zonder_alt": len(gebreken["zonder_alt"]),
                          "dunne_tekst": len(gebreken["dunne_tekst"]),
                          "faq_ontbreekt": not gebreken["heeft_faq"],
                          "producten_bekeken": gebreken["producten_bekeken"],
                          "nog_te_gaan": rest},
            "voorstellen": alles,
            "fouten": fouten}


# ---------------------------------------------------------------- toepassen

VRAAG_FOTO = """
query Foto($id: ID!) {
  node(id: $id) { ... on MediaImage { id alt } }
}
"""

VRAAG_PRODUCTTEKST = """
query Producttekst($id: ID!) {
  product(id: $id) { id descriptionHtml }
}
"""

ZET_ALT = """
mutation ZetAlt($bestanden: [FileUpdateInput!]!) {
  fileUpdate(files: $bestanden) {
    files { ... on MediaImage { id alt } }
    userErrors { field message code }
  }
}
"""

ZET_TEKST = """
mutation ZetTekst($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { id }
    userErrors { field message }
  }
}
"""

MAAK_PAGINA = """
mutation MaakPagina($pagina: PageCreateInput!) {
  pageCreate(page: $pagina) {
    page { id title handle }
    userErrors { field message code }
  }
}
"""

WEG_PAGINA = """
mutation VerwijderPagina($id: ID!) {
  pageDelete(id: $id) {
    deletedPageId
    userErrors { field message code }
  }
}
"""


def _zet_alt(winkel, sleutel, afbeelding_id, tekst):
    """De beschrijving bij één foto zetten.

    De oude manier hiervoor (productImageUpdate) bestaat niet meer. Een foto
    is bij Shopify tegenwoordig een bestand, en de beschrijving hoort bij dat
    bestand. Vandaar fileUpdate met het gid van de MediaImage."""
    return _muteer(winkel, sleutel, ZET_ALT,
                   {"bestanden": [{"id": _gid("MediaImage", afbeelding_id),
                                   "alt": tekst or ""}]},
                   "fileUpdate")


def _zet_producttekst(winkel, sleutel, product_id, html_tekst):
    """De beschrijving van één product zetten.

    Het veld heet hier descriptionHtml. En let op de naam van het invoerveld:
    dat is "product", niet "input". Dat laatste bestaat nog wel maar is
    verouderd, en op verouderde velden willen wij niet bouwen als de reden van
    deze hele verbouwing juist goedkeuring door Shopify is."""
    return _muteer(winkel, sleutel, ZET_TEKST,
                   {"product": {"id": _gid("Product", product_id),
                                "descriptionHtml": html_tekst or ""}},
                   "productUpdate")


def _huidige_waarde(winkel, sleutel, voorstel):
    """Wat er NU staat, opgehaald op het moment van schrijven.

    Niet wat er stond toen wij het voorstel maakten. Daar kan een uur tussen
    zitten waarin de eigenaar zelf iets heeft ingevuld, en dan moeten wij van
    zijn tekst afblijven."""
    soort = voorstel.get("soort")
    if soort == "alt":
        uit = _graphql(winkel, sleutel, VRAAG_FOTO,
                       {"id": _gid("MediaImage", voorstel["afbeelding_id"])})
        if not uit["gelukt"]:
            return None, uit["fout"]
        knoop = (uit["gegevens"] or {}).get("node")
        if knoop is None:
            # De foto is er niet meer. Dan weten wij de oude waarde niet, en
            # dus schrijven wij ook niet.
            return None, "Deze foto bestaat niet meer in de winkel."
        return knoop.get("alt") or "", None
    if soort == "tekst":
        uit = _graphql(winkel, sleutel, VRAAG_PRODUCTTEKST,
                       {"id": _gid("Product", voorstel["product_id"])})
        if not uit["gelukt"]:
            return None, uit["fout"]
        product = (uit["gegevens"] or {}).get("product")
        if product is None:
            return None, "Dit product bestaat niet meer in de winkel."
        return product.get("descriptionHtml") or "", None
    if soort == "faq":
        return "", None
    return None, "Onbekend soort wijziging."


def pas_toe(winkel, sleutel, voorstel, klant_url):
    """Zet één voorstel in de winkel.

    De volgorde hier is het hele punt. Eerst kijken wat er staat, dan de oude
    waarde vastleggen, en pas dan schrijven. Lukt het vastleggen niet, dan
    stoppen wij: een wijziging die niet terug kan mogen wij niet maken."""
    if not voorstel or not voorstel.get("id"):
        return {"gelukt": False, "fout": "Geen voorstel meegegeven."}

    huidig, fout = _huidige_waarde(winkel, sleutel, voorstel)
    if huidig is None:
        return {"gelukt": False, "fout": fout or "Kon de huidige waarde niet ophalen."}

    soort = voorstel["soort"]
    if soort in ("alt", "tekst"):
        kaal = _kale_tekst(huidig)
        grens = 1 if soort == "alt" else TEKST_ONDERGRENS
        if len(kaal) >= grens:
            return {"gelukt": False, "overgeslagen": True,
                    "fout": "Hier staat inmiddels al een tekst. Die laten wij staan."}

    if soort == "faq":
        for pagina in haal_paginas(winkel, sleutel):
            if (pagina.get("handle") or "") == FAQ_HANDLE:
                return {"gelukt": False, "overgeslagen": True,
                        "fout": "Deze pagina bestaat al."}

    bewaard = db.bewaar_wijziging(
        webshop_url=klant_url, taak_id=voorstel["id"], wat=voorstel.get("wat"),
        waar=voorstel.get("waar"), oude_waarde=huidig,
        nieuwe_waarde=voorstel.get("nieuw_html") or voorstel.get("nieuw"))
    if not bewaard:
        return {"gelukt": False,
                "fout": "Wij konden de oude tekst niet bewaren, dus wij hebben niets "
                        "veranderd. Zo kan alles altijd terug."}

    if soort == "alt":
        uit = _zet_alt(winkel, sleutel, voorstel["afbeelding_id"], voorstel["nieuw"])
    elif soort == "tekst":
        uit = _zet_producttekst(winkel, sleutel, voorstel["product_id"],
                                voorstel.get("nieuw_html") or voorstel["nieuw"])
    elif soort == "faq":
        titel = "Veelgestelde vragen"
        uit = _muteer(winkel, sleutel, MAAK_PAGINA,
                      {"pagina": {"title": titel, "handle": FAQ_HANDLE,
                                  "body": voorstel.get("nieuw_html") or voorstel["nieuw"],
                                  "isPublished": True}},
                      "pageCreate")
        if uit["gelukt"]:
            nieuwe = _nummer(((uit["gegevens"] or {}).get("page") or {}).get("id"))
            db.bewaar_wijziging(
                webshop_url=klant_url, taak_id=voorstel["id"], wat=voorstel.get("wat"),
                waar=f"pagina {nieuwe}", oude_waarde="",
                nieuwe_waarde=voorstel.get("nieuw_html") or voorstel["nieuw"])
    else:
        return {"gelukt": False, "fout": "Onbekend soort wijziging."}

    if not uit["gelukt"]:
        # De vastgelegde wijziging weer weghalen. Anders staat er in het
        # overzicht dat wij iets veranderd hebben terwijl er niets veranderd is,
        # en dat is het soort leugen waar een klant later over valt.
        db.verwijder_wijziging(klant_url, voorstel["id"])
        return {"gelukt": False, "fout": uit["fout"]}
    return {"gelukt": True, "id": voorstel["id"]}


def zet_terug(winkel, sleutel, wijziging, klant_url=None):
    """Eén wijziging ongedaan maken, met de bewaarde oude waarde."""
    taak_id = (wijziging or {}).get("taak_id") or ""
    oud = (wijziging or {}).get("oude_waarde")
    if not taak_id.startswith("shopify:"):
        return {"gelukt": False, "fout": "Dit is geen wijziging in een Shopify-winkel."}
    delen = taak_id.split(":")

    # Uit het kenmerk halen wij de nummers, en daar maken wij het gid weer van
    # dat GraphQL nodig heeft. Het kenmerk zelf blijft dus precies zoals het in
    # de database staat, ook bij wijzigingen van voor deze verbouwing.
    if delen[1] == "alt" and len(delen) == 4:
        uit = _zet_alt(winkel, sleutel, delen[3], oud or "")
    elif delen[1] == "tekst" and len(delen) == 3:
        uit = _zet_producttekst(winkel, sleutel, delen[2], oud or "")
    elif delen[1] == "faq":
        pagina_id = None
        for pagina in haal_paginas(winkel, sleutel):
            if (pagina.get("handle") or "") == FAQ_HANDLE:
                pagina_id = pagina["id"]
        if pagina_id is None:
            # De pagina is er al niet meer. Dan is er niets terug te zetten en
            # is dit gewoon gelukt.
            if klant_url:
                db.verwijder_wijziging(klant_url, taak_id)
            return {"gelukt": True, "id": taak_id}
        uit = _muteer(winkel, sleutel, WEG_PAGINA,
                      {"id": _gid("Page", pagina_id)}, "pageDelete")
    else:
        return {"gelukt": False, "fout": "Onbekend soort wijziging."}

    if not uit["gelukt"]:
        return {"gelukt": False, "fout": uit["fout"]}
    return {"gelukt": True, "id": taak_id}
