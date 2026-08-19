"""
Krillo - echte AI-gegenereerde audit-inhoud.

Vervangt de vaste sjablonen door daadwerkelijk door Claude geschreven,
site-specifieke tekst: voor elk gevonden probleem een concrete uitleg en
een kant-en-klare oplossing (herschreven tekst, of technische code).

Vereist de omgevingsvariabele ANTHROPIC_API_KEY in Render.
"""

import os
import json

import anthropic

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


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def generate_ai_fixes(webshop_url, checks):
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

    prompt = f"""{HUISSTIJL_INSTRUCTIES}

Dit zijn de gevonden problemen voor de webshop {webshop_url}:

{problemen_tekst}

Schrijf voor ELK van deze problemen een concrete oplossing. Voor tekstuele
problemen (titel, omschrijving, veelgestelde vragen): schrijf de daadwerkelijke
nieuwe tekst, alsof die al voor deze specifieke webshop is geschreven. Voor
technische problemen (ontbrekende code, sitemap, robots.txt): geef de exacte
code of instructie die opgelost moet worden.

Antwoord ALLEEN met geldige JSON, in dit exacte formaat, niets ervoor of erna:

{{
  "fixes": [
    {{
      "titel": "Korte titel van de fix",
      "uitleg": "Een of twee zinnen die uitleggen waarom dit belangrijk is voor deze webshop",
      "oplossing": "De concrete tekst of code die het probleem oplost"
    }}
  ]
}}
"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
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
