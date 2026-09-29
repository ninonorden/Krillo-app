"""De controleagent: keurt tekst voordat hij naar buiten gaat (stap 38, 28 september).

WAAROM DIT BESTAAT. Krillo verkoopt vertrouwen. Een mail met "Hi None," of
"{naam}", een verzonnen levertijd, een belofte die we niet waar kunnen maken
("guaranteed #1 in ChatGPT") of een Nederlands woord midden in een Engelse
mail kost meer dan een mail die niet verstuurd wordt. De agents schrijven hun
mails uit vaste sjablonen met echte cijfers; deze keuring is het laatste hek.

TWEE SOORTEN BEVINDINGEN
- fout: de tekst gaat NIET weg (kapotte invulling, beloofd resultaat,
  verzonnen termijn of garantie). De agent slaat hem over en het staat in de log.
- waarschuwing: de tekst gaat wel weg, maar Nino ziet het (lange streepjes,
  Nederlandse woorden in Engelse tekst). Die maken een mail slechter, niet fout.

Bewust ZONDER AI: dezelfde tekst krijgt altijd hetzelfde oordeel, het kost
niets, en het is te testen. De proefset staat in tests/test_tekstkeuring.py.
"""
import re

# Termijnen die op onze eigen site en in de voorwaarden staan: die mogen.
_TOEGESTANE_TERMIJNEN = (
    "within one working day", "within a working day", "within 14 days", "within fourteen days",
    "within 30 days", "for 12 months", "for 30 days", "60 days", "same day", "binnen een werkdag",
    "binnen 14 dagen", "binnen veertien dagen", "binnen 30 dagen",
)

_KAPOT = [
    (re.compile(r"\bNone\b(?! of)"), "het woord 'None' (een lege invulling)"),
    (re.compile(r"\bnan\b|\bnull\b|\bundefined\b"), "een lege invulling (nan, null of undefined)"),
    (re.compile(r"\{\{?\s*\w+\s*\}?\}"), "een niet ingevulde plek tussen accolades"),
    (re.compile(r"\[(naam|name|winkel|store|TODO)\]", re.I), "een niet ingevulde plek tussen haken"),
    (re.compile(r"\bTODO\b|\bXXX\b|lorem ipsum", re.I), "een aantekening of opvultekst"),
    (re.compile(r"#0\b|\b0 of 0\b"), "een plek of telling van nul"),
]

_BELOFTE = [
    (re.compile(r"\bguarantee[ds]?\b|\bgarantie\b|\bgegarandeerd\b", re.I), "een garantie"),
    (re.compile(r"\b(we|will) (get|make|put) you (to )?(#|number )?1\b", re.I), "een beloofde plek"),
    (re.compile(r"\b(always|100%) (named|recommended|at the top)\b", re.I), "een beloofd resultaat"),
    (re.compile(r"\b(delivered|delivery|levertijd|geleverd) (within|in|binnen) \d+", re.I), "een levertijd"),
]

_TERMIJN = re.compile(r"\b(within|binnen|in)\s+(\d+|one|two|three|a)\s+(hours?|days?|weeks?|uur|dagen|weken|werkdagen?)\b", re.I)

_NL_WOORDEN = re.compile(r"\b(de|het|een|jouw|jij|wij|niet|voor|maar|ook|winkel|klant|bedankt|groet)\b", re.I)


def keur(tekst, taal="en"):
    """Keur een tekst. Geeft {"ok", "fouten", "waarschuwingen"}.
    ok is False als er een fout is: dan gaat de tekst niet weg."""
    tekst = tekst or ""
    fouten, waarschuwingen = [], []
    if not tekst.strip():
        return {"ok": False, "fouten": ["lege tekst"], "waarschuwingen": []}
    for patroon, wat in _KAPOT + _BELOFTE:
        if patroon.search(tekst):
            fouten.append(wat)
    for m in _TERMIJN.finditer(tekst):
        if not any(m.group(0).lower() in t for t in _TOEGESTANE_TERMIJNEN):
            fouten.append(f"een termijn die nergens in onze voorwaarden staat ('{m.group(0)}')")
    if "\u2014" in tekst:
        waarschuwingen.append("een lang streepje")
    if taal == "en":
        # Winkelnamen en koopvragen mogen Nederlands zijn; pas bij drie of meer
        # Nederlandse woorden is het waarschijnlijk een Nederlandse zin.
        nl = _NL_WOORDEN.findall(re.sub(r"<strong>.*?</strong>|\"[^\"]*\"|'[^']*'", "", tekst))
        if len(nl) >= 3:
            waarschuwingen.append(f"Nederlandse woorden in een Engelse tekst ({', '.join(sorted(set(n.lower() for n in nl))[:5])})")
    return {"ok": not fouten, "fouten": fouten, "waarschuwingen": waarschuwingen}


def keur_mail(onderwerp, alineas, taal="en"):
    """Keur onderwerp en alinea's samen, zoals een agent ze verstuurt."""
    return keur("\n".join([onderwerp or ""] + list(alineas or [])), taal)
