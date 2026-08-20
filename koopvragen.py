"""
Krillo - koopvragen genereren.

Voor het meten van vermeldingen hebben we per webshop de vragen nodig die een
koper daadwerkelijk aan een AI-assistent zou stellen. Die verschillen per
branche: iemand die hardloopschoenen zoekt vraagt iets heel anders dan iemand
die een koffiemachine zoekt.

Dit is echt werk voor een agent en niet voor een vast script, want de agent
moet eerst begrijpen wat de webshop verkoopt en aan wie, voordat hij kan
bedenken wat kopers vragen.

We verdelen de vragen bewust over verschillende soorten koopintenties, zodat
dertig vragen niet dertig varianten van hetzelfde blijken te zijn.
"""

import os
import json

import time

import anthropic
import requests

import kosten
from bs4 import BeautifulSoup

MODEL = "claude-sonnet-4-6"

# De soorten vragen die kopers stellen. Per soort minstens een paar vragen,
# zodat we een eerlijk beeld krijgen en niet alleen meten op een smal stukje.
INTENTIES = [
    ("algemeen", "Iemand zoekt het beste product in deze categorie, zonder verdere eisen."),
    ("prijs", "Iemand zoekt binnen een bepaald budget, of juist het goedkoopste of het beste voor de prijs."),
    ("doelgroep", "Iemand zoekt iets voor een specifieke situatie of persoon, bijvoorbeeld voor beginners, voor kinderen, of voor intensief gebruik."),
    ("alternatief", "Iemand zoekt een alternatief voor een bekend merk of product."),
    ("winkel", "Iemand zoekt niet een product maar een betrouwbare Nederlandse of Belgische webshop om het te kopen."),
    ("praktisch", "Iemand let op levertijd, retourneren, voorraad of garantie, maar vraagt WEL naar een winkel die dat goed geregeld heeft. Dus niet 'hoe lang duurt levering', wel 'welke Nederlandse webshop levert servies het snelst'."),
]


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _haal_winkelinfo_op(webshop_url, extra_paginas=None):
    """Haalt op wat de webshop verkoopt, zodat de agent weet waar hij vragen
    over moet bedenken. Zonder dit zou hij gokken."""
    urls = [webshop_url] + (extra_paginas or [])
    stukken = []
    for pagina_url in urls[:4]:
        url = pagina_url if pagina_url.startswith(("http://", "https://")) else "https://" + pagina_url
        try:
            resp = requests.get(url, headers={"User-Agent": "KrilloBot/0.4 (+https://www.krillo.nl)"}, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            titel = soup.title.string.strip() if soup.title and soup.title.string else ""
            omschrijving_tag = soup.find("meta", attrs={"name": "description"})
            omschrijving = omschrijving_tag["content"].strip() if omschrijving_tag and omschrijving_tag.get("content") else ""
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            tekst = " ".join(soup.get_text(" ", strip=True).split())[:900]
            stukken.append(f"--- {pagina_url} ---\nTitel: {titel}\nOmschrijving: {omschrijving}\nTekst: {tekst}")
        except Exception:
            continue
    return "\n\n".join(stukken) if stukken else ""


def genereer_koopvragen(webshop_url, extra_paginas=None, aantal=30):
    """Laat een agent bepalen wat deze webshop verkoopt, en daaruit de
    koopvragen afleiden die mensen aan een AI-assistent stellen.

    Geeft een lijst terug met per vraag de tekst en de soort intentie.
    Geeft None terug als er geen AI-sleutel is."""
    client = _get_client()
    if client is None:
        return None

    winkelinfo = _haal_winkelinfo_op(webshop_url, extra_paginas)
    if not winkelinfo:
        return None

    intentie_uitleg = "\n".join(f"- {naam}: {uitleg}" for naam, uitleg in INTENTIES)
    per_intentie = max(2, aantal // len(INTENTIES))

    prompt = f"""Je helpt bij het meten of een webshop wordt aanbevolen door AI-assistenten.

Hieronder staat de inhoud van een webshop. Bepaal eerst zelf wat deze winkel
verkoopt, aan wie, en in welke prijsklasse. Bedenk daarna de vragen die een
koper echt aan ChatGPT of Gemini zou stellen als hij zoiets wil kopen.

De webshop:
{winkelinfo}

Verdeel de vragen over deze soorten koopintenties, ongeveer {per_intentie} per soort:
{intentie_uitleg}

Belangrijke regels:
- Schrijf de vragen zoals een gewoon mens ze typt, in het Nederlands. Dus
  "welke wandelschoenen zijn goed voor brede voeten" en niet "wandelschoenen
  brede voeten kopen".
- Noem de naam van deze webshop NIET in de vragen. We willen meten of de shop
  uit zichzelf genoemd wordt, niet of AI de naam kan herhalen.
- Maak de vragen niet te breed. "Wat is een goede webshop" zegt niets. Maak ze
  specifiek voor wat deze winkel verkoopt.
- Elke vraag moet om een aanbeveling vragen: een winkel, een merk of een
  product. Stel geen vragen waar alleen algemene uitleg uit komt. "Hoe lang heb
  ik bedenktijd bij een online aankoop" levert een antwoord op waar geen enkele
  winkel in voorkomt, en zo'n vraag kan dus nooit meten of deze shop genoemd
  wordt. Twijfel je, stel jezelf de vraag: kan het antwoord hierop een winkel
  of merk noemen? Zo nee, bedenk een andere vraag.
- Zorg dat de vragen echt van elkaar verschillen. Dertig varianten van dezelfde
  vraag meten niets.
- Als de winkel duidelijk op Nederland of Belgie gericht is, laat dat in een
  deel van de vragen terugkomen.

Antwoord ALLEEN met geldige JSON, in dit formaat, niets ervoor of erna:

{{
  "wat_verkoopt_deze_winkel": "een of twee zinnen",
  "vragen": [
    {{"vraag": "de vraag zoals iemand hem stelt", "intentie": "algemeen"}}
  ]
}}
"""

    try:
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            print(f"AI-aanroep geblokkeerd door de kostenrem: {rem['reden']}")
            return None

        gestart = time.monotonic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=response.usage.input_tokens,
            uitvoer_tokens=response.usage.output_tokens,
            soort="koopvragen-bedenken", webshop_url=webshop_url,
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        ruw = response.content[0].text.strip()
        if ruw.startswith("```"):
            ruw = ruw.split("```")[1]
            if ruw.startswith("json"):
                ruw = ruw[4:]
        data = json.loads(ruw)
        vragen = data.get("vragen", [])
        geldige_intenties = {naam for naam, _ in INTENTIES}
        opgeschoond = [
            {"vraag": v["vraag"].strip(), "intentie": v.get("intentie", "algemeen")}
            for v in vragen
            if v.get("vraag") and v.get("intentie", "algemeen") in geldige_intenties
        ]
        return {
            "omschrijving": data.get("wat_verkoopt_deze_winkel", ""),
            "vragen": opgeschoond,
        }
    except Exception as e:
        print(f"Koopvragen genereren mislukt: {e}")
        return None


def vind_dubbele_vragen(vragen):
    """Stap 2: bepaalt welke vragen in feite hetzelfde vragen.

    Dit kan geen simpel woordvergelijk zijn. 'Wat zijn goede alternatieven voor
    Funda' en 'welke online alternatieven zijn er voor Pararius of Funda' delen
    weinig woorden maar vragen hetzelfde. Andersom kunnen twee vragen bijna
    identiek klinken en toch iets anders bedoelen.

    Geeft per dubbeling terug welke vraag je zou houden en welke je kan laten
    vallen, met de reden."""
    client = _get_client()
    if client is None or len(vragen) < 2:
        return []

    genummerd = "\n".join(
        f"{i+1}. {v['vraag']} [{v.get('intentie', '?')}]" for i, v in enumerate(vragen)
    )

    prompt = f"""Hieronder staan koopvragen die we aan AI-assistenten gaan stellen om te meten
of een webshop wordt aanbevolen.

Het probleem: als twee vragen in feite hetzelfde vragen, meten we hetzelfde
twee keer en verspillen we een meetplek. Zoek de vragen die zo sterk op elkaar
lijken dat het antwoord vrijwel zeker hetzelfde zal zijn.

Let op:
- Kijk naar de bedoeling, niet naar de woorden. Twee vragen kunnen heel anders
  klinken en toch hetzelfde vragen.
- Twee vragen over hetzelfde onderwerp maar met een ander accent zijn NIET
  dubbel. "Beste hardloopschoenen" en "beste hardloopschoenen voor beginners"
  leveren andere antwoorden op en moeten allebei blijven.
- De toets is hard: zou een AI op beide vragen vrijwel dezelfde winkels of
  merken noemen, in vrijwel dezelfde volgorde? Alleen dan is het dubbel.
- Deze zijn NIET dubbel, ook al lijken ze op elkaar:
  "hoe lang duurt de levering" en "hoe lang heb ik bedenktijd" (het een gaat
  over bezorgen, het ander over retourrecht);
  "cadeau voor iemand die graag bakt" en "cadeau voor een stel dat gaat
  samenwonen" (andere ontvanger, dus ander antwoord);
  "waar koop ik servies onder 50 euro" en "welke webshop verkoopt goedkoop
  keukengerei" (ander product).
- Wees terughoudend. Bij twijfel is het geen dubbeling. Liever een vraag te
  veel dan een blinde vlek in de meting. Markeer nooit meer dan een kwart van
  de vragen als dubbel.

De vragen:
{genummerd}

Antwoord ALLEEN met geldige JSON, niets ervoor of erna:

{{
  "dubbelingen": [
    {{"houden": 3, "weglaten": 7, "reden": "korte uitleg waarom dit hetzelfde vraagt"}}
  ]
}}

Is er niets dubbel, geef dan een lege lijst terug."""

    try:
        gestart = time.monotonic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=response.usage.input_tokens,
            uitvoer_tokens=response.usage.output_tokens,
            soort="vragen-ontdubbelen",
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        ruw = response.content[0].text.strip()
        if ruw.startswith("```"):
            ruw = ruw.split("```")[1]
            if ruw.startswith("json"):
                ruw = ruw[4:]
        data = json.loads(ruw)
        resultaat = []
        for d in data.get("dubbelingen", []):
            houden, weglaten = d.get("houden"), d.get("weglaten")
            if not (isinstance(houden, int) and isinstance(weglaten, int)):
                continue
            if not (1 <= houden <= len(vragen) and 1 <= weglaten <= len(vragen)):
                continue
            if houden == weglaten:
                continue
            resultaat.append({
                "houden": vragen[houden - 1]["vraag"],
                "weglaten": vragen[weglaten - 1]["vraag"],
                "reden": d.get("reden", ""),
            })
        return resultaat
    except Exception as e:
        print(f"Dubbele vragen zoeken mislukt: {e}")
        return []


DOEL_PER_INTENTIE = int(os.environ.get("KOOPVRAGEN_PER_INTENTIE", "5"))


def tel_tekort(actieve_vragen, doel_per_intentie=None):
    """Kijkt per intentie hoeveel vragen er nog missen om op het doel te komen.

    Zonder dit loopt de vragenset elke keer leeg: ontdubbelen haalt vragen weg
    en er komt nooit iets voor terug. Na een paar keer klikken hou je twee
    winkelvragen over, precies de soort vraag waar het ons om te doen is."""
    doel = doel_per_intentie or DOEL_PER_INTENTIE
    aanwezig = {naam: 0 for naam, _ in INTENTIES}
    for v in actieve_vragen:
        naam = v.get("intentie")
        if naam in aanwezig:
            aanwezig[naam] += 1
    return {naam: doel - aantal for naam, aantal in aanwezig.items() if aantal < doel}


def vul_vragen_aan(webshop_url, omschrijving, tekort, al_bedacht):
    """Bedenkt alleen de vragen die nog missen, voor de intenties die te dun
    zijn. Gebruikt de omschrijving die we al van deze winkel hebben, dus de
    website hoeft niet opnieuw gescand te worden.

    al_bedacht bevat ook de uitgezette vragen. Die geven we mee zodat de AI
    niet opnieuw bedenkt wat we net hebben weggegooid."""
    client = _get_client()
    if client is None or not tekort:
        return []

    intentie_uitleg = dict(INTENTIES)
    gevraagd = "\n".join(
        f"- {naam}: {aantal} vragen. {intentie_uitleg.get(naam, '')}"
        for naam, aantal in tekort.items()
    )
    bestaande = "\n".join(f"- {v}" for v in al_bedacht)

    prompt = f"""Voor deze webshop meten we of AI-assistenten hem noemen bij koopvragen.

Wat deze winkel verkoopt:
{omschrijving}

Er missen nog vragen bij een paar soorten koopintentie. Bedenk er precies zoveel
als hier gevraagd wordt, niet meer en niet minder:
{gevraagd}

Deze vragen bestaan al of zijn eerder afgevallen. Bedenk niets wat hier
inhoudelijk op lijkt:
{bestaande}

Belangrijke regels:
- Schrijf ze zoals een gewoon mens ze typt, in het Nederlands.
- Noem de naam van deze webshop NIET in de vragen.
- Elke vraag moet om een aanbeveling vragen: een winkel, een merk of een
  product. Geen vragen waar alleen algemene uitleg uit komt.
- Maak ze specifiek voor wat deze winkel verkoopt.

Antwoord ALLEEN met geldige JSON, niets ervoor of erna:

{{
  "vragen": [
    {{"vraag": "de vraag zoals iemand hem stelt", "intentie": "winkel"}}
  ]
}}
"""

    try:
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            print(f"Aanvullen geblokkeerd door de kostenrem: {rem['reden']}")
            return []

        gestart = time.monotonic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=response.usage.input_tokens,
            uitvoer_tokens=response.usage.output_tokens,
            soort="vragen-aanvullen",
            webshop_url=webshop_url,
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        ruw = response.content[0].text.strip()
        if ruw.startswith("```"):
            ruw = ruw.split("```")[1]
            if ruw.startswith("json"):
                ruw = ruw[4:]
        data = json.loads(ruw)
        geldig = {naam for naam, _ in INTENTIES}
        bekend = {v.lower().strip() for v in al_bedacht}
        return [
            {"vraag": v["vraag"].strip(), "intentie": v["intentie"]}
            for v in data.get("vragen", [])
            if v.get("vraag") and v.get("intentie") in geldig
            and v["vraag"].lower().strip() not in bekend
        ]
    except Exception as e:
        print(f"Vragen aanvullen mislukt: {e}")
        return []
