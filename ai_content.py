"""
Krillo - echte AI-gegenereerde audit-inhoud.

Vervangt de vaste sjablonen door daadwerkelijk door Claude geschreven,
site-specifieke tekst: voor elk gevonden probleem een concrete uitleg en
een kant-en-klare oplossing (herschreven tekst, of technische code).

Vereist de omgevingsvariabele ANTHROPIC_API_KEY in Render.
"""

import os
import json

import time

import anthropic
import requests

import kosten
import scan_engine
from bs4 import BeautifulSoup

MODEL = "claude-sonnet-4-6"

HUISSTIJL_INSTRUCTIES = """
Je schrijft voor Krillo, een tool die webshops helpt om beter gevonden en
aanbevolen te worden door AI-assistenten zoals ChatGPT en Gemini.

Schrijfregels, altijd aanhouden:
- Nederlands, doodgewone taal, geen jargon (dus geen woorden als 'dashboard',
  'schema-markup', 'crawler', 'AI-modellen' zonder uitleg).
- Nooit gedachtestreepjes/em-dashes gebruiken.
- Korte, directe zinnen. Geen overdreven marketingtaal.
- Je schrijft voor een webshop-eigenaar zonder marketingbureau, niet voor een
  marketeer die de vaktermen al kent.
"""


def _get_page_context(webshop_url, extra_page_urls=None):
    """Haalt de daadwerkelijke pagina('s) op en trekt er bruikbare context uit
    (titel, omschrijving, en een stuk zichtbare tekst), zodat de AI de
    sector en toon van de webshop kan meewegen, over meerdere pagina's heen
    in plaats van alleen de homepage."""
    alle_urls = [webshop_url] + (extra_page_urls or [])
    context_stukken = []
    for pagina_url in alle_urls[:4]:  # maximaal 4 pagina's, om de prompt behapbaar te houden
        url = pagina_url
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            # Dezelfde aanmelding als de scan. Een onbekende robotnaam levert
            # bij grotere webshops een beveiligingspagina op, en dan schrijft
            # het model een tekst over "Even geduld" in plaats van over servies.
            resp = requests.get(url, headers=scan_engine.HEADERS, timeout=12)
            if scan_engine.lijkt_op_blokkadepagina(resp.text):
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            desc_tag = soup.find("meta", attrs={"name": "description"})
            description = desc_tag["content"].strip() if desc_tag and desc_tag.get("content") else ""
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            visible_text = " ".join(soup.get_text(" ", strip=True).split())[:800]
            context_stukken.append(
                f"--- Pagina: {pagina_url} ---\nTitel: {title}\nOmschrijving: {description}\nTekst (fragment): {visible_text}"
            )
        except Exception:
            continue
    if not context_stukken:
        return "Kon de pagina-inhoud niet ophalen, baseer je alleen op de bevindingen hieronder."
    return "\n\n".join(context_stukken)


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _zonder_markdown(tekst):
    """Haalt opmaaktekens uit een tekst die iemand letterlijk gaat plakken.

    Een model schrijft graag **vet** en # koppen. In het tekstvak van Shopify
    of WordPress verschijnen die sterretjes gewoon op de website. De belofte
    boven dit blok is "neem dit letterlijk over", dus dan moet er ook niets
    meer opgeruimd hoeven worden. Vangnet naast de instructie in de opdracht,
    want een model vergeet zo'n regel soms."""
    import re as _re
    if not (tekst or "").strip():
        return ""

    schoon = []
    for regel in tekst.split("\n"):
        # Regels die code bevatten laten we met rust. In JSON-LD of HTML kan
        # een sterretje of een accolade gewoon bij de code horen, en een
        # opgeschoonde regel code is stukke code.
        if any(teken in regel for teken in ("<", ">", "{", "}", '":')):
            schoon.append(regel)
            continue
        regel = _re.sub(r"\*\*(.+?)\*\*", r"\1", regel)                    # **vet**
        regel = _re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", regel)  # *schuin*
        regel = _re.sub(r"^#{1,6}\s+", "", regel)                          # # koppen
        # Opsommingstekens laten we staan. "- Log in op Shopify" leest in een
        # gewoon tekstvak prima; die weghalen maakt een lijstje juist
        # onleesbaar. Alleen een sterretje als opsommingsteken wordt een
        # streepje, want dat leest als markdown.
        regel = _re.sub(r"^(\s*)\*\s+", r"\1- ", regel)
        schoon.append(regel)
    return "\n".join(schoon).strip()


def genereer_taakoplossing(webshop_url, taak_id, taak_titel, wat_moet_er_gebeuren,
                           extra_page_urls=None, platform=None):
    """Schrijft voor ÉÉN taak uit het actieplan de kant-en-klare oplossing.

    Dit is het verschil tussen een scan en een oplossing. "Zet vragen en
    antwoorden op je site" is een opdracht. Vijf uitgeschreven vragen met
    antwoorden over jouw producten, plus de route waar je ze plakt, is iets wat
    je vanmiddag af hebt.

    Bewust per taak en niet alles in een keer zoals de audit doet. Het
    actieplan toont er hoogstens drie, dus meer laten schrijven is geld
    uitgeven aan tekst die niemand ziet. De aanroeper bewaart de uitkomst, dus
    dit gebeurt een keer per taak per winkel en niet elke week opnieuw.

    Geeft altijd een woordenboek terug met "gelukt". Bij een mislukking staat
    er ook "fout" in, met de echte reden. Bewust niet stilletjes None: dan zie
    je alleen een leeg vak op de klantpagina en weet je niet of de sleutel
    ontbreekt, de rem dicht stond of het antwoord onleesbaar was. Die fout
    hebben we bij de bronanalyse al een keer gemaakt.

    De taak blijft bij een mislukking gewoon staan met de algemene uitleg
    eronder, alleen zonder plakbare tekst. Nooit laten klappen op een tekst die
    niet geschreven kon worden."""
    client = _get_client()
    if client is None:
        return {"gelukt": False, "fout": "Geen ANTHROPIC_API_KEY ingesteld in Render."}

    pagina_context = _get_page_context(webshop_url, extra_page_urls)

    # Het platform komt uit de scan (herken_platform) en staat bij het
    # winkelprofiel. Weten we het niet, dan vragen we bewust om twee routes in
    # plaats van er een te gokken: een klant die "ga naar Winkelinstellingen"
    # leest terwijl hij WooCommerce heeft, denkt dat het product niet klopt.
    if platform:
        platform_regel = (
            f"Deze webshop draait op {platform}. Beschrijf bij \"waar\" ALLEEN de "
            f"route binnen {platform}, met de menunamen zoals ze daar heten, en "
            f"noem geen andere platforms. Klopt {platform} volgens jou niet met "
            f"wat je op de pagina hierboven ziet, zeg dat dan in een zin aan het "
            f"begin van \"waar\" en geef daarna de route die wel klopt."
        )
    else:
        platform_regel = (
            "We hebben niet kunnen vaststellen op welk platform deze webshop "
            "draait. Geef bij \"waar\" daarom de route in Shopify en de route in "
            "WooCommerce of WordPress, allebei kort, zodat de lezer de zijne "
            "herkent. Verzin geen menunamen die je niet zeker weet."
        )

    prompt = f"""{HUISSTIJL_INSTRUCTIES}

Dit is de daadwerkelijke inhoud van de webshop {webshop_url}. Gebruik dit zodat
je oplossing echt over DEZE winkel gaat, met zijn producten en zijn toon, en
niet over een willekeurige webshop:

{pagina_context}

De eigenaar van deze webshop heeft één taak op zijn lijst staan:

TAAK: {taak_titel}
WAT ER MOET GEBEUREN: {wat_moet_er_gebeuren}

Schrijf de oplossing die hij letterlijk kan overnemen. Niet uitleggen wat hij
zou kunnen doen, maar het werk voor hem doen.

- Gaat het om tekst (vragen en antwoorden, een titel, een omschrijving, een
  bericht aan een redactie), schrijf dan de echte tekst, af, over de producten
  van deze winkel. Verzin geen feiten die je niet uit de pagina hierboven kan
  halen: weet je een levertijd of een prijs niet, laat dan duidelijk
  [vul je eigen levertijd in] staan, zodat hij ziet wat hij zelf moet aanvullen.
- Gaat het om code, geef dan de exacte code, kant en klaar.
- Gaat het om een instelling, geef dan de exacte stappen.

SCHRIJF GEWONE TEKST, GEEN MARKDOWN. Dus geen sterretjes om woorden heen voor
vet, geen hekjes voor koppen, geen streepjes voor opsommingen. Deze tekst wordt
letterlijk geplakt in het tekstvak van Shopify of WordPress, en die kennen geen
markdown. Een kop is gewoon een regel tekst met een lege regel eronder. Iemand
die jouw tekst overneemt moet er niets meer aan hoeven opruimen.

SCHRIJF PLATTE TEKST, GEEN MARKDOWN. Geen sterretjes om iets vet te maken,
geen hekjes voor koppen. Deze tekst wordt letterlijk geplakt in het tekstvak
van een webshop, en daar blijven die tekens gewoon staan: dan zet een klant
"**Veelgestelde vragen**" op zijn website. Wil je een kop, zet die dan op een
eigen regel met een lege regel eronder. De enige uitzondering is code, die
geef je precies zoals hij moet zijn.

De lezer heeft geen technische kennis en heeft nog nooit in de instellingen van
zijn webshop gekeken. Bij "waar" leg je stap voor stap uit waar dit heen moet.

{platform_regel}

Is het echt te technisch om zelf te doen, zeg dat dan eerlijk en schrijf de
tekst die hij kan doorsturen naar de bouwer van zijn site.

Antwoord ALLEEN met geldige JSON, niets ervoor of erna:

{{
  "oplossing": "de echte tekst, code of stappen om over te nemen",
  "waar": "stap voor stap waar dit neergezet wordt, in gewone taal"
}}
"""

    try:
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            print(f"Taakoplossing geblokkeerd door de kostenrem: {rem['reden']}")
            return {"gelukt": False, "fout": f"Kostenrem: {rem['reden']}"}

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
            soort="taakoplossing", webshop_url=webshop_url,
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        ruw = response.content[0].text.strip()
        if ruw.startswith("```"):
            ruw = ruw.split("```")[1]
            if ruw.startswith("json"):
                ruw = ruw[4:]
        # Het stuk tussen de eerste accolade en de laatste. Zet een model er
        # een zin voor of achter, dan klapt json.loads op de hele tekst.
        begin, eind = ruw.find("{"), ruw.rfind("}")
        if begin != -1 and eind > begin:
            ruw = ruw[begin:eind + 1]
        data = json.loads(ruw)
        oplossing = _zonder_markdown(data.get("oplossing"))
        if not oplossing:
            return {"gelukt": False, "fout": "Het model gaf een leeg antwoord terug."}
        return {"gelukt": True, "taak_id": taak_id, "titel": taak_titel,
                "oplossing": oplossing, "waar": _zonder_markdown(data.get("waar"))}
    except Exception as e:
        fout = f"{type(e).__name__}: {e}"[:300]
        print(f"Taakoplossing genereren mislukt voor {taak_id}: {fout}")
        return {"gelukt": False, "fout": fout}


def generate_ai_fixes(webshop_url, checks, extra_page_urls=None):
    """Genereert voor elk probleem (status != ok) een concrete, site-specifieke
    oplossing via Claude. Geeft een lijst met fixes terug, of None als er geen
    AI-sleutel is (dan valt de aanroepende code terug op de sjabloon-versie)."""
    client = _get_client()
    if client is None:
        return None

    problemen = [c for c in checks if c["status"] != "ok"]
    if not problemen:
        return []

    problemen_tekst = "\n".join(
        f"- {p['titel']} ({p['categorie']}): {p['uitleg']}" for p in problemen
    )
    pagina_context = _get_page_context(webshop_url, extra_page_urls)

    prompt = f"""{HUISSTIJL_INSTRUCTIES}

Dit is de daadwerkelijke inhoud van de pagina, gebruik dit om de sector, toon
en het soort producten van deze webshop mee te wegen in je tekst, zodat het
niet generiek aanvoelt:

{pagina_context}

Dit zijn de gevonden problemen voor de webshop {webshop_url}:

{problemen_tekst}

Schrijf voor ELK van deze problemen een concrete oplossing. Gebruik de sector,
producten en toon van de pagina hierboven, zodat de tekst duidelijk over déze
specifieke webshop gaat, niet over een willekeurige webshop. Voor tekstuele
problemen (titel, omschrijving, veelgestelde vragen): schrijf de daadwerkelijke
nieuwe tekst, alsof die al voor deze specifieke webshop is geschreven. Voor
technische problemen (ontbrekende code, sitemap, robots.txt): geef de exacte
code of instructie die opgelost moet worden.

HEEL BELANGRIJK: de lezer is een webshop-eigenaar zonder technische kennis. Leg
bij elke oplossing in het veld "waar" stap voor stap uit waar hij dit precies
moet neerzetten, in gewone taal, alsof je het aan iemand uitlegt die nog nooit
in de instellingen van zijn webshop heeft gekeken. Noem waar mogelijk de
concrete route in de meestgebruikte webshopsystemen (Shopify: Winkel beheren,
Thema's, Code bewerken, theme.liquid. WooCommerce of WordPress: Weergave,
Thema-bestanden, header.php, of een plugin voor kopteksten). Als het echt te
technisch is om zelf te doen, zeg dat er eerlijk bij en adviseer om het door de
bouwer van de site te laten doen, met de tekst die hij kan doorsturen.

Antwoord ALLEEN met geldige JSON, in dit exacte formaat, niets ervoor of erna:

{{
  "fixes": [
    {{
      "titel": "Korte titel van de fix",
      "uitleg": "Een of twee zinnen die uitleggen waarom dit belangrijk is voor deze webshop",
      "oplossing": "De concrete tekst of code die het probleem oplost",
      "waar": "Stap voor stap waar je dit neerzet, in gewone taal, zonder jargon"
    }}
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
            soort="audit-teksten", webshop_url=webshop_url,
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        data = json.loads(raw_text)
        return data.get("fixes", [])
    except Exception as e:
        print(f"AI-fixes genereren mislukt: {e}")
        return None
