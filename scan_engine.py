"""
Vezora - scan-engine, versie 3: de volledige gratis scan.

Dit haalt zoveel mogelijk uit een enkele scan van een pagina, verdeeld
over vier categorieen die samen bepalen of AI een site kan vinden,
lezen, begrijpen en vertrouwen:

1. TOEGANG      - kan AI de site technisch bezoeken en snel laden
2. LEESBAARHEID - staat de tekst er zonder gedoe, met duidelijke structuur
3. STRUCTUUR    - is de informatie machine-leesbaar gemaakt (schema.org,
                  sitemap, het nieuwe llms.txt-bestand, sociale metadata)
4. INHOUD       - is de inhoud zelf compleet genoeg (FAQ's, beschrijvende
                  tekst, afbeeldingen met alt-tekst)

Layer 3 uit het bedrijfsplan ("vertrouwen": wordt de site al genoemd door
AI-modellen zelf) zit hier bewust nog niet in. Dat vraagt een eigen
API-sleutel bij een AI-aanbieder om echte vragen te kunnen stellen, en is
de logische volgende uitbreiding zodra dat geregeld is.
"""

import json
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

AI_BOTS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "OAI-SearchBot", "anthropic-ai"]
TIMEOUT = 10
HEADERS = {"User-Agent": "VezoraScanBot/0.3 (+https://vezora.nl)"}


def normalize_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def fetch(url, measure_time=False):
    try:
        start = time.monotonic()
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        elapsed = time.monotonic() - start
        return (resp, elapsed) if measure_time else resp
    except requests.RequestException:
        return (None, None) if measure_time else None


def status_from_score(score):
    if score >= 80:
        return "ok"
    if score >= 40:
        return "deels"
    return "probleem"


def make_check(id_, titel, categorie, impact, score, uitleg):
    return {
        "id": id_, "titel": titel, "categorie": categorie, "impact": impact,
        "score": score, "status": status_from_score(score), "uitleg": uitleg,
    }


# ---------- Categorie: TOEGANG ----------

def check_https(base_url):
    is_https = base_url.startswith("https://")
    score = 100 if is_https else 0
    uitleg = ("De site gebruikt een beveiligde verbinding (https)." if is_https else
              "De site gebruikt geen beveiligde verbinding (https). AI-modellen en browsers vertrouwen onbeveiligde sites steeds minder.")
    return make_check("https", "Gebruikt de site een beveiligde verbinding?", "toegang", "hoog", score, uitleg)


def check_robots_txt(base_url):
    robots_url = urljoin(base_url, "/robots.txt")
    resp = fetch(robots_url)

    if resp is None or resp.status_code != 200:
        return make_check("robots", "Kunnen AI-robots je site bezoeken?", "toegang", "hoog", 100,
                           "Er is geen robots.txt gevonden op deze site. Dat is meestal geen probleem, AI-robots mogen dan gewoon overal binnen.")

    text = resp.text
    blocked_bots, current_agents = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            current_agents = [value]
        elif key == "disallow" and value == "/":
            for agent in current_agents:
                for bot in AI_BOTS:
                    if agent.lower() == bot.lower() or agent == "*":
                        blocked_bots.append(bot if agent != "*" else f"{bot} (via een algemene regel)")

    blocked_bots = sorted(set(blocked_bots))
    if blocked_bots:
        return make_check("robots", "Kunnen AI-robots je site bezoeken?", "toegang", "hoog", 0,
                           f"Deze site blokkeert actief de volgende AI-robots via robots.txt: {', '.join(blocked_bots)}.")
    return make_check("robots", "Kunnen AI-robots je site bezoeken?", "toegang", "hoog", 100,
                       "Er staat een robots.txt op deze site, en die laat AI-robots gewoon toe.")


def check_speed(elapsed):
    if elapsed is None:
        return make_check("snelheid", "Laadt de pagina snel genoeg?", "toegang", "gemiddeld", 0, "Kon de laadtijd niet meten.")
    ms = round(elapsed * 1000)
    if ms <= 800:
        score, uitleg = 100, f"De pagina reageerde in {ms} ms, dat is snel genoeg om geen probleem te zijn."
    elif ms <= 2000:
        score, uitleg = 65, f"De pagina reageerde in {ms} ms. Dat kan sneller, maar is geen groot probleem."
    else:
        score, uitleg = 25, f"De pagina reageerde pas na {ms} ms. Trage pagina's worden door zowel zoekmachines als AI-robots minder vaak volledig bezocht."
    return make_check("snelheid", "Laadt de pagina snel genoeg?", "toegang", "gemiddeld", score, uitleg)


# ---------- Categorie: LEESBAARHEID ----------

def check_javascript_dependency(html):
    if html is None:
        return make_check("leesbaarheid", "Is de belangrijkste tekst zichtbaar zonder te klikken?", "leesbaarheid", "hoog", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    word_count = len(soup.get_text(separator=" ", strip=True).split())

    if word_count >= 300:
        score, uitleg = 100, f"Er staan direct {word_count} woorden leesbare tekst op de pagina, ruim genoeg voor AI om te begrijpen waar de pagina over gaat."
    elif word_count >= 150:
        score, uitleg = 70, f"Er staan {word_count} woorden direct leesbare tekst op de pagina. Dat is bruikbaar, meer tekst geeft AI net wat meer houvast."
    elif word_count >= 80:
        score, uitleg = 40, f"Er staan maar {word_count} woorden direct leesbare tekst op de pagina. Een deel van je content verschijnt mogelijk pas na het uitvoeren van scripts."
    else:
        score, uitleg = 10, f"Er staan maar {word_count} woorden direct leesbare tekst in de ruwe pagina. Grote kans dat je belangrijkste content pas verschijnt nadat JavaScript is uitgevoerd, en dat missen de meeste AI-robots volledig."
    return make_check("leesbaarheid", "Is de belangrijkste tekst zichtbaar zonder te klikken?", "leesbaarheid", "hoog", score, uitleg)


def check_heading_structuur(html):
    if html is None:
        return make_check("koppen", "Is de pagina logisch opgebouwd met koppen?", "leesbaarheid", "gemiddeld", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")

    if len(h1_tags) == 1:
        score = 100
        uitleg = f'Precies één hoofdkop (H1) gevonden: "{h1_tags[0].get_text(" ", strip=True)[:60]}", plus {len(h2_tags)} subkoppen. Dat is de duidelijkste opbouw voor AI.'
    elif len(h1_tags) == 0:
        score = 20
        uitleg = "Geen hoofdkop (H1) gevonden. Zonder duidelijke hoofdkop is het voor AI lastiger te bepalen waar de pagina precies over gaat."
    else:
        score = 55
        uitleg = f"Er zijn {len(h1_tags)} hoofdkoppen (H1) gevonden op één pagina. Dat kan AI in verwarring brengen over wat het hoofdonderwerp is."
    return make_check("koppen", "Is de pagina logisch opgebouwd met koppen?", "leesbaarheid", "gemiddeld", score, uitleg)


def check_taal(html):
    if html is None:
        return make_check("taal", "Is duidelijk aangegeven in welke taal de pagina is?", "leesbaarheid", "laag", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    html_tag = soup.find("html")
    lang = html_tag.get("lang") if html_tag else None

    if lang:
        return make_check("taal", "Is duidelijk aangegeven in welke taal de pagina is?", "leesbaarheid", "laag", 100, f'De taal is expliciet aangegeven als "{lang}". Dat voorkomt dat AI de verkeerde taalversie aan iemand toont.')
    return make_check("taal", "Is duidelijk aangegeven in welke taal de pagina is?", "leesbaarheid", "laag", 30, "Er is geen taal ingesteld op de pagina (het lang-attribuut ontbreekt). AI moet dan zelf raden welke taal en welk land dit betreft.")


# ---------- Categorie: STRUCTUUR ----------

def check_structured_data(html):
    if html is None:
        return make_check("productinfo", "Kan AI de inhoud van deze pagina betrouwbaar uitlezen?", "structuur", "hoog", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", type="application/ld+json")
    found_types = set()
    for tag in scripts:
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                t = item.get("@type")
                found_types.update(t) if isinstance(t, list) else (found_types.add(t) if t else None)

    core_types = {"Product", "Offer", "FAQPage"}
    bonus_types = {"Organization", "BreadcrumbList", "LocalBusiness", "Article", "WebPage"}
    found_core = found_types & core_types
    found_bonus = found_types & bonus_types
    score = min(100, len(found_core) * 30 + len(found_bonus) * 10)

    if found_types:
        gevonden = ", ".join(sorted(found_types))
        if found_core:
            uitleg = f"Gevonden op deze pagina: {gevonden}. Daarmee kan AI belangrijke informatie betrouwbaar overnemen."
        else:
            uitleg = f"Gevonden op deze pagina: {gevonden}. Dit helpt, maar specifieke product- of vraag-en-antwoord-informatie ontbreekt nog."
    else:
        uitleg = "Er is geen machine-leesbare informatie (schema.org) gevonden op deze pagina. Let op: dit checkt de opgegeven pagina zelf; op een homepage is dit vaak leeg terwijl productpagina's dit wel hebben."
    return make_check("productinfo", "Kan AI de inhoud van deze pagina betrouwbaar uitlezen?", "structuur", "hoog", score, uitleg)


def check_sitemap(base_url):
    resp = fetch(urljoin(base_url, "/sitemap.xml"))
    if resp is not None and resp.status_code == 200 and "xml" in resp.headers.get("Content-Type", ""):
        return make_check("sitemap", "Kan AI makkelijk al je pagina's vinden?", "structuur", "gemiddeld", 100,
                           "Er is een sitemap.xml gevonden. Dat maakt het voor AI-robots makkelijker om al je pagina's te ontdekken, niet alleen de homepage.")
    return make_check("sitemap", "Kan AI makkelijk al je pagina's vinden?", "structuur", "gemiddeld", 30,
                       "Geen sitemap.xml gevonden op de standaardlocatie. Zonder sitemap moet AI zelf via links al je pagina's ontdekken.")


def check_llms_txt(base_url):
    resp = fetch(urljoin(base_url, "/llms.txt"))
    if resp is not None and resp.status_code == 200:
        return make_check("llms_txt", "Heeft de site specifieke instructies voor AI?", "structuur", "laag", 100,
                           "Er is een llms.txt-bestand gevonden. Dit is een nieuwe, opkomende standaard waarmee een site AI-modellen direct de belangrijkste informatie kan meegeven.")
    return make_check("llms_txt", "Heeft de site specifieke instructies voor AI?", "structuur", "laag", 40,
                       "Geen llms.txt gevonden. Dit is een nieuwe, nog weinig gebruikte standaard, dus dit is geen groot verlies, wel een kans om vroeg voorop te lopen.")


def check_social_preview(html):
    if html is None:
        return make_check("voorbeeldweergave", "Heeft de pagina een duidelijke samenvatting voor AI en social media?", "structuur", "gemiddeld", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    og_tags = {"og:title", "og:description", "og:image"}
    found = {tag.get("property") or tag.get("name") for tag in soup.find_all("meta")
             if (tag.get("property") or tag.get("name")) in og_tags and tag.get("content")}

    score = round((len(found) / len(og_tags)) * 100)
    if found:
        uitleg = f"Gevonden: {', '.join(sorted(found))}. Dit helpt platforms en AI om je pagina kort en correct samen te vatten."
    else:
        uitleg = "Geen Open Graph-gegevens (og:title, og:description, og:image) gevonden. Hierdoor moeten AI en social media zelf raden wat de pagina samenvat."
    return make_check("voorbeeldweergave", "Heeft de pagina een duidelijke samenvatting voor AI en social media?", "structuur", "gemiddeld", score, uitleg)


# ---------- Categorie: INHOUD ----------

def check_basics(html):
    if html is None:
        return make_check("basis", "Heeft de pagina een duidelijke titel en omschrijving?", "inhoud", "gemiddeld", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    desc_tag = soup.find("meta", attrs={"name": "description"})
    description = desc_tag["content"].strip() if desc_tag and desc_tag.get("content") else ""

    score, notes = 0, []
    if title and len(title) >= 10:
        score += 50
        notes.append(f'titel gevonden: "{title[:60]}"')
    else:
        notes.append("geen duidelijke paginatitel")

    if description and len(description) >= 40:
        score += 50
        notes.append(f'omschrijving gevonden: "{description[:80]}..."')
    else:
        notes.append("geen of een te korte omschrijving")

    uitleg = "; ".join(notes).capitalize() + "."
    return make_check("basis", "Heeft de pagina een duidelijke titel en omschrijving?", "inhoud", "gemiddeld", score, uitleg)


def check_faq_content(html):
    if html is None:
        return make_check("faq", "Beantwoordt de pagina veelgestelde vragen direct?", "inhoud", "gemiddeld", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    text_lower = soup.get_text(" ", strip=True).lower()
    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3", "h4"])]
    question_headings = [h for h in headings if h.strip().endswith("?")]

    has_faq_schema = False
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "FAQPage":
                has_faq_schema = True

    keyword_hit = any(k in text_lower for k in ["veelgestelde vragen", "faq", "vraag en antwoord", "veel gestelde vragen"])

    if has_faq_schema:
        score, uitleg = 100, "Er is machine-leesbare FAQ-informatie (FAQPage-schema) gevonden. Dit is precies het soort directe vraag-en-antwoord-content dat AI graag citeert."
    elif question_headings:
        score, uitleg = 65, f"Er zijn {len(question_headings)} koppen in vraagvorm gevonden (bijv. \"{question_headings[0][:60]}\"). Dat helpt AI, al is het sterker als dit ook als officiële FAQ-data staat gemarkeerd."
    elif keyword_hit:
        score, uitleg = 45, "Er lijkt een veelgestelde-vragen-sectie te zijn, maar die is niet als zodanig gemarkeerd voor AI. Voeg FAQ-schema toe om dit te laten meetellen."
    else:
        score, uitleg = 15, "Geen veelgestelde-vragen-content gevonden op deze pagina. Directe vraag-en-antwoord-content is een van de dingen die AI het vaakst letterlijk overneemt."
    return make_check("faq", "Beantwoordt de pagina veelgestelde vragen direct?", "inhoud", "gemiddeld", score, uitleg)


def check_alt_teksten(html):
    if html is None:
        return make_check("alt_tekst", "Hebben afbeeldingen een beschrijving voor AI?", "inhoud", "laag", 0, "Kon de pagina niet ophalen om dit te checken.")

    soup = BeautifulSoup(html, "html.parser")
    images = soup.find_all("img")
    if not images:
        return make_check("alt_tekst", "Hebben afbeeldingen een beschrijving voor AI?", "inhoud", "laag", 100, "Geen afbeeldingen gevonden op deze pagina, dus niets om hier te missen.")

    with_alt = [img for img in images if img.get("alt", "").strip()]
    ratio = len(with_alt) / len(images)
    score = round(ratio * 100)
    uitleg = f"{len(with_alt)} van de {len(images)} afbeeldingen hebben een beschrijving (alt-tekst). AI kan afbeeldingen zonder beschrijving niet interpreteren."
    return make_check("alt_tekst", "Hebben afbeeldingen een beschrijving voor AI?", "inhoud", "laag", score, uitleg)


# ---------- Score en samenvoegen ----------

def compute_score(checks):
    weights = {"hoog": 20, "gemiddeld": 10, "laag": 5}
    scorable = [c for c in checks if c["status"] != "onbekend"]
    if not scorable:
        return 0
    max_score = sum(weights.get(c["impact"], 10) for c in scorable)
    earned = sum(weights.get(c["impact"], 10) * (c["score"] / 100) for c in scorable)
    return round((earned / max_score) * 100)


# ---------- Voorbeeldfixes: wat de betaalde audit concreet oplevert ----------

def generate_fix_previews(url, checks, html):
    """Genereert 1-3 concrete voorbeeldfixes op basis van de gevonden problemen,
    zodat iemand kan zien wat de betaalde audit oplevert, niet alleen dat 'ie bestaat.
    Dit is nu op basis van regels/templates. Zodra er een AI-sleutel gekoppeld wordt,
    kan dit stuk vervangen worden door echt AI-gegenereerde, unieke teksten."""
    previews = []
    domain = urlparse(url).netloc.replace("www.", "")
    naam = domain.split(".")[0].capitalize()
    checks_by_id = {c["id"]: c for c in checks}

    # Voorbeeld 1: titel en omschrijving
    basis = checks_by_id.get("basis")
    if basis and basis["status"] != "ok":
        soup = BeautifulSoup(html, "html.parser") if html else None
        h1_raw = soup.find("h1").get_text(" ", strip=True) if soup and soup.find("h1") else naam
        h1 = " ".join(h1_raw.split())
        voor_titel = (soup.title.string.strip() if soup and soup.title and soup.title.string else "(geen titel)")
        na_titel = f"{h1} | {naam}: officiële webshop met snelle levering"
        na_omschrijving = f"Ontdek het assortiment van {naam}. {h1}, met duidelijke levertijden en eenvoudig te bestellen. Bekijk het volledige aanbod."
        previews.append({
            "titel": "Titel en omschrijving herschreven",
            "voor": voor_titel,
            "na": f'Titel: "{na_titel}"\nOmschrijving: "{na_omschrijving}"',
        })

    # Voorbeeld 2: productinformatie als machine-leesbare code
    productinfo = checks_by_id.get("productinfo")
    if productinfo and productinfo["status"] != "ok":
        voorbeeld_code = (
            "{\n"
            '  "@context": "https://schema.org",\n'
            '  "@type": "Organization",\n'
            f'  "name": "{naam}",\n'
            f'  "url": "{url}"\n'
            "}"
        )
        previews.append({
            "titel": "Machine-leesbare bedrijfsinfo toegevoegd (code, klaar om te plakken)",
            "voor": "Geen machine-leesbare informatie gevonden.",
            "na": voorbeeld_code,
        })

    # Voorbeeld 3: FAQ-content
    faq = checks_by_id.get("faq")
    if faq and faq["status"] != "ok":
        previews.append({
            "titel": "Veelgestelde vragen omgezet naar AI-leesbare vorm",
            "voor": "Geen (of niet als zodanig gemarkeerde) veelgestelde vragen.",
            "na": f'Voorbeeldvraag toegevoegd: "Wat zijn de levertijden bij {naam}?" met een direct, kort antwoord, plus de bijbehorende FAQ-code zodat AI dit als officieel vraag-en-antwoord herkent.',
        })

    return previews[:3]


def run_scan(url):
    """Voert de volledige gratis scan uit over alle categorieen en geeft score + checks terug."""
    url = normalize_url(url)
    parsed = urlparse(url)
    if not parsed.netloc:
        return {"error": "Dat is geen geldige URL."}

    resp, elapsed = fetch(url, measure_time=True)
    html = resp.text if resp is not None else None

    checks = [
        check_https(url),
        check_robots_txt(url),
        check_speed(elapsed),
        check_javascript_dependency(html),
        check_heading_structuur(html),
        check_taal(html),
        check_structured_data(html),
        check_sitemap(url),
        check_llms_txt(url),
        check_social_preview(html),
        check_basics(html),
        check_faq_content(html),
        check_alt_teksten(html),
    ]
    score = compute_score(checks)
    fix_previews = generate_fix_previews(url, checks, html)
    return {"url": url, "score": score, "checks": checks, "voorbeeldfixes": fix_previews}
