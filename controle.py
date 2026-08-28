"""
Krillo - fase 5 stap 9: klopt wat AI over je zegt?

AI kan je noemen en er tegelijk naast zitten. Een verkeerde levertijd, een
retourtermijn die niet klopt, een product dat je helemaal niet verkoopt. Voor
een winkel is dat erger dan niet genoemd worden: een koper die op onjuiste
informatie afkomt haakt af bij de kassa.

Dit is goedkoop te bouwen omdat het zware werk al gedaan is. De antwoorden
staan in de database en de beoordeling heeft er al per antwoord een citaat
uitgehaald. We hoeven alleen die uitspraken naast de site te leggen.

Eerlijkheid boven volledigheid. We scannen een paar pagina's, geen hele
webshop. Een uitspraak die we niet kunnen terugvinden is daarom niet fout, die
is onbekend. Dat verschil staat overal in terug, want een klant een fout
melden die geen fout is, is erger dan zwijgen.
"""

import json
import os
import time

import anthropic

import beoordeling
import kosten

MODEL = os.environ.get("CONTROLE_MODEL", "claude-sonnet-4-6")
MAX_UITSPRAKEN = int(os.environ.get("CONTROLE_MAX_UITSPRAKEN", "25"))
MAX_SITETEKST = int(os.environ.get("CONTROLE_MAX_SITETEKST", "12000"))


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def verzamel_uitspraken(beoordelingen):
    """Haalt de citaten op waarin de winkel genoemd wordt.

    Dat citaat is precies wat de AI over deze winkel beweerde, dus dat is wat
    gecontroleerd moet worden. Dubbele citaten gooien we eruit, want twee
    modellen die hetzelfde zeggen is een uitspraak, geen twee."""
    gezien = set()
    uitspraken = []
    for b in beoordelingen:
        bewijs = (b.get("bewijs") or "").strip()
        if not b.get("genoemd") or not bewijs:
            continue
        sleutel = " ".join(bewijs.lower().split())
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        uitspraken.append({"vraag": b.get("vraag"), "uitspraak": bewijs})
        if len(uitspraken) >= MAX_UITSPRAKEN:
            break
    return uitspraken


def controleer(webshop_url, winkelnaam, uitspraken, sitetekst):
    """Legt de uitspraken naast wat er op de site staat.

    Een aanroep voor alle uitspraken samen, niet een per stuk. Dat is goedkoper
    en het model kan de site dan een keer lezen in plaats van vijfentwintig
    keer."""
    client = _get_client()
    if client is None or not uitspraken or not sitetekst:
        return []

    genummerd = "\n".join(
        f'{i+1}. Bij de vraag "{u["vraag"]}" zei AI: "{u["uitspraak"]}"'
        for i, u in enumerate(uitspraken)
    )

    prompt = f"""Je controleert of wat AI-assistenten over een webshop zeggen ook klopt.

De webshop is {winkelnaam or webshop_url} ({webshop_url}).

Hieronder staat eerst de tekst die we van de site zelf hebben opgehaald, en
daarna de uitspraken die AI over deze winkel deed. Bepaal per uitspraak of die
klopt met wat er op de site staat.

DE TEKST VAN DE SITE:
{sitetekst}

DE UITSPRAKEN:
{genummerd}

Regels die je strikt volgt:
- "klopt": de site bevestigt dit.
- "klopt niet": de site zegt aantoonbaar iets anders. Bijvoorbeeld AI zegt
  veertien dagen retour en op de site staat dertig dagen.
- "onbekend": je kan het niet terugvinden in deze tekst. Dit is GEEN fout. Wij
  halen maar een paar pagina's op, dus het meeste zal onbekend zijn. Kies dit
  ook bij smaakoordelen als "tijdloos" of "sfeervol", want die zijn niet te
  controleren.
- Twijfel je tussen "klopt niet" en "onbekend", kies dan altijd "onbekend".
  Een klant een fout melden die geen fout is, is erger dan zwijgen.
- Bij "klopt niet" is het veld watzegtdesite verplicht: schrijf daar wat er
  volgens de sitetekst wel klopt.

Antwoord ALLEEN met geldige JSON, niets ervoor of erna:

{{
  "uitkomsten": [
    {{"nummer": 1, "oordeel": "klopt", "watzegtdesite": null, "toelichting": "korte uitleg"}}
  ]
}}"""

    try:
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            print(f"Controle geblokkeerd door de kostenrem: {rem['reden']}")
            return []

        gestart = time.monotonic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=response.usage.input_tokens,
            uitvoer_tokens=response.usage.output_tokens,
            soort="uitspraken-controleren",
            webshop_url=webshop_url,
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        data = beoordeling._schoon_json(response.content[0].text)

        resultaat = []
        for u in data.get("uitkomsten", []):
            nummer = u.get("nummer")
            if not isinstance(nummer, int) or not (1 <= nummer <= len(uitspraken)):
                continue
            oordeel = u.get("oordeel")
            if oordeel not in ("klopt", "klopt niet", "onbekend"):
                oordeel = "onbekend"
            bron = uitspraken[nummer - 1]
            resultaat.append({
                "vraag": bron["vraag"],
                "uitspraak": bron["uitspraak"],
                "oordeel": oordeel,
                "watzegtdesite": u.get("watzegtdesite") or None,
                "toelichting": u.get("toelichting") or None,
            })
        return resultaat
    except Exception as e:
        print(f"Uitspraken controleren mislukt: {e}")
        return []


def vat_samen(uitkomsten):
    """De cijfers zoals ze getoond worden. Onbekend is een eigen categorie en
    telt niet als fout, anders lijkt elke onvindbare uitspraak een probleem."""
    fout = [u for u in uitkomsten if u["oordeel"] == "klopt niet"]
    return {
        "gecontroleerd": len(uitkomsten),
        "klopt": len([u for u in uitkomsten if u["oordeel"] == "klopt"]),
        "klopt_niet": len(fout),
        "onbekend": len([u for u in uitkomsten if u["oordeel"] == "onbekend"]),
        "fouten": fout,
    }
