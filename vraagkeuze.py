"""Welke gemiste vraag past bij wat een winkel ECHT verkoopt (24 september).

WAAROM DIT BESTAND BESTAAT

De koude mail aan keekabuu.com liet de vraag "Welke Nederlandse webshop
verkoopt betrouwbare kinderwagens?" zien, met "keekabuu.com was not named".
Keekabuu verkoopt geen kinderwagens. De vraag hoort wel bij de categorie
(babyspullen en verzorging), maar niet bij deze winkel. Wie zo'n mail opent,
denkt: logisch dat ik daar niet genoemd word, dit is gewoon een machine. En
dan is de mail zijn geloofwaardigheid kwijt.

Een categorie is breder dan een winkel. Dus kiezen wij per winkel de gemiste
vraag die past bij zijn eigen assortiment:
1. Wat verkoopt de winkel? Uit ons winkelprofiel, anders uit de titel en de
   omschrijving van zijn homepage.
2. Een klein, goedkoop model krijgt die omschrijving en de gemiste vragen, en
   geeft terug welke vragen passen, beste eerst. Past er geen een, dan geen:
   liever geen voorbeeld dan een verkeerd voorbeeld.
3. Werkt het model niet, dan een eenvoudige woordvergelijking met de
   homepage. Weten wij helemaal niets van de winkel, dan geen voorbeeldvraag.
   Ook dan liever niets dan iets wat niet klopt.
"""
import html as _html
import os
import re
import time

import db

MODEL = os.environ.get("VRAAGKEUZE_MODEL", "claude-haiku-4-5-20251001")

# Woorden die in bijna elke koopvraag staan en dus niets zeggen over het
# assortiment.
_LEEG = set("""welke waar wat wie hoe een het de van voor met bij online webshop winkel
kopen koop koopt verkoopt goede goed beste beter betrouwbare betrouwbaar nederlandse
belgische nederland belgie snel snelle goedkoop goedkope leuke mooie is zijn in op te en
of die dat dit ik je jij mijn voor om aan kan kun je kunnen heeft hebben""".split())


def _woorden(tekst):
    return {w for w in re.findall(r"[a-zà-ÿ]{4,}", (tekst or "").lower()) if w not in _LEEG}


def wat_verkoopt(webshop_url, ophalen=None):
    """Een korte omschrijving van het assortiment, of een lege tekst."""
    try:
        profiel = db.get_winkelprofiel(webshop_url) or {}
        if (profiel.get("omschrijving") or "").strip():
            return profiel["omschrijving"].strip()[:600]
    except Exception:
        pass
    try:
        if ophalen is None:
            import scan_engine
            resp = scan_engine.fetch(webshop_url, pogingen=1)
            pagina = resp.text if resp is not None else ""
        else:
            pagina = ophalen(webshop_url) or ""
    except Exception:
        pagina = ""
    stukken = []
    for patroon in (r"<title[^>]*>(.*?)</title>",
                    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
                    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
                    r"<h1[^>]*>(.*?)</h1>"):
        m = re.search(patroon, pagina or "", re.I | re.S)
        if m:
            stukken.append(re.sub(r"<[^>]+>|\s+", " ", _html.unescape(m.group(1))).strip())
    return " | ".join(s for s in stukken if s)[:600]


def _kies_met_model(omschrijving, vragen):
    import beoordeling
    import categoriemeting
    import kosten
    client = categoriemeting._client()
    if client is None:
        return None
    genummerd = "\n".join(f"{i}. {v}" for i, v in enumerate(vragen))
    prompt = (
        "Een webwinkel beschrijft zichzelf zo:\n"
        f"{omschrijving}\n\n"
        "Hieronder staan koopvragen die kopers aan een AI-assistent stelden. Welke gaan "
        "over iets wat DEZE winkel verkoopt? Een vraag over een product dat de winkel "
        "niet voert, past niet, ook als het in dezelfde branche hoort. Twijfel je, dan "
        "past hij niet.\n\n"
        f"{genummerd}\n\n"
        'Antwoord ALLEEN met JSON: {"passend": [nummers, best passend eerst]}. '
        'Past er geen enkele, antwoord dan {"passend": []}.')
    gestart = time.monotonic()
    antwoord = client.messages.create(model=MODEL, max_tokens=200,
                                      messages=[{"role": "user", "content": prompt}])
    kosten.registreer_aanroep(
        provider="anthropic", model=MODEL,
        invoer_tokens=antwoord.usage.input_tokens,
        uitvoer_tokens=antwoord.usage.output_tokens,
        soort="vraagkeuze", duur_ms=int((time.monotonic() - gestart) * 1000))
    data = beoordeling._schoon_json(antwoord.content[0].text) or {}
    uit = []
    for n in data.get("passend") or []:
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if 0 <= n < len(vragen) and n not in uit:
            uit.append(n)
    return uit


def passende_vragen(webshop_url, gemiste, ophalen=None):
    """De gemiste vragen die bij deze winkel passen, beste eerst.

    gemiste: de lijst uit klantbeeld (elk een dict met "vraag"). Geeft een
    (mogelijk lege) lijst terug in hetzelfde formaat. Nooit een fout."""
    gemiste = [g for g in (gemiste or []) if g.get("vraag")]
    if not gemiste:
        return []
    omschrijving = wat_verkoopt(webshop_url, ophalen=ophalen)
    if not omschrijving:
        return []
    vragen = [g["vraag"] for g in gemiste]
    try:
        keuze = _kies_met_model(omschrijving, vragen)
    except Exception as e:
        print(f"Vraagkeuze via het model mislukt voor {webshop_url}: {e}")
        keuze = None
    if keuze is None:
        # Zonder model: alleen vragen die een inhoudelijk woord delen met wat
        # de winkel over zichzelf zegt.
        eigen = _woorden(omschrijving)
        keuze = [i for i, v in enumerate(vragen) if _woorden(v) & eigen]
    return [gemiste[i] for i in keuze]
