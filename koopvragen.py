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

import anthropic
import requests
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
    ("praktisch", "Iemand let op levertijd, retourneren, voorraad of garantie."),
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
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
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
