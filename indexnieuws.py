"""Maandelijks nieuws uit de index (stap 92, 28 september).

WAAROM DIT BESTAAT. Profound en AthenaHQ groeiden mede doordat ze hun eigen
meetdata als nieuws brachten: "wie wint er in AI bij X". Krillo heeft precies
zulke data, per categorie en per land, en niemand anders heeft die voor
Nederlandse en Belgische webshops. Vakmedia (Emerce, Twinkle, Ecommercenews,
Retailtrends, Marketingfacts) zoeken zulk nieuws. Een artikel daar is bereik
bij precies de goede lezers, gratis, en een link die AI-assistenten meetellen.

WAT HET MAAKT
- overzicht(land): per categorie de nummer 1 (en of die nieuw is), de grootste
  stijger en de grootste daler ten opzichte van de vorige meting.
- Een openbare pagina /news/<land> in het Engels (de site is Engels).
- Een persbericht in het NEDERLANDS voor Nino (/admin/persbericht): de
  ontvangers zijn Nederlandse en Vlaamse redacties. Hij kopieert en stuurt het.

REGELS: alleen wat de meting zegt; namen van winkels staan al openbaar in de
index; geen afgemelde winkels (die haalt de ranglijst er al uit); alleen
categorieen met genoeg winkels (MIN_WINKELS).
"""
from datetime import datetime

import db
import categorieen

MIN_WINKELS = 10
MIN_BEWEGING = 3
MAANDEN_NL = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
              "september", "oktober", "november", "december"]
LANDNAAM_NL = {"nl": "Nederland", "be": "België"}


def _naam(rij):
    naam = rij.get("naam")
    if naam and not str(naam).startswith("http"):
        return naam
    return (rij.get("webshop_url") or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def overzicht(land, ranglijst=None, categorielijst=None):
    """Het nieuws van de laatste meting in dit land. Geeft
    {"land", "datum", "categorieen": [...], "winkels", "nieuwe_nummer_een"}."""
    land = (land or "").lower()
    ranglijst = ranglijst or db.ranglijst_per_land
    cats = categorielijst if categorielijst is not None else db.categorieen_per_land(land)
    uit, datum, winkels = [], None, 0
    for c in cats:
        slug = c["categorie"]
        lijst = ranglijst(slug, land, 1000) or {}
        rijen = lijst.get("rijen") or []
        if len(rijen) < MIN_WINKELS:
            continue
        winkels += len(rijen)
        if c.get("afgerond_op") and (datum is None or c["afgerond_op"] > datum):
            datum = c["afgerond_op"]
        een = rijen[0]
        bewegers = [r for r in rijen if r.get("vorige_positie")]
        stijger = max(bewegers, key=lambda r: r["vorige_positie"] - r["positie"], default=None)
        daler = max(bewegers, key=lambda r: r["positie"] - r["vorige_positie"], default=None)
        uit.append({
            "slug": slug, "naam": categorieen.naam_en(slug), "naam_nl": categorieen.naam_van(slug),
            "winkels": len(rijen),
            "nummer_een": _naam(een),
            "nieuw_bovenaan": bool(een.get("vorige_positie") and een["vorige_positie"] != 1),
            "was": een.get("vorige_positie"),
            "stijger": ({"naam": _naam(stijger), "van": stijger["vorige_positie"], "naar": stijger["positie"]}
                        if stijger and stijger["vorige_positie"] - stijger["positie"] >= MIN_BEWEGING else None),
            "daler": ({"naam": _naam(daler), "van": daler["vorige_positie"], "naar": daler["positie"]}
                      if daler and daler["positie"] - daler["vorige_positie"] >= MIN_BEWEGING else None),
        })
    uit.sort(key=lambda c: (not c["nieuw_bovenaan"], -(c["winkels"])))
    return {"land": land, "datum": datum, "categorieen": uit, "winkels": winkels,
            "nieuwe_nummer_een": sum(1 for c in uit if c["nieuw_bovenaan"])}


def persbericht_nl(ov, basis_url="https://krilloai.com", embed=None):
    """Het persbericht voor Nederlandse en Vlaamse redacties. Platte tekst.
    Geeft None als er te weinig te melden is."""
    if not ov["categorieen"]:
        return None
    land = LANDNAAM_NL.get(ov["land"], ov["land"].upper())
    maand = ""
    if isinstance(ov.get("datum"), datetime):
        maand = f"{MAANDEN_NL[ov['datum'].month - 1]} {ov['datum'].year}"
    nieuws = [c for c in ov["categorieen"] if c["nieuw_bovenaan"]][:3]
    stijgers = sorted([c for c in ov["categorieen"] if c["stijger"]],
                      key=lambda c: -(c["stijger"]["van"] - c["stijger"]["naar"]))[:3]
    regels = [f"Deze webshops raden ChatGPT en Gemini aan in {land}: de Krillo Index van {maand}".strip(), ""]
    regels.append(
        f"Amsterdam. Welke webshop noemt ChatGPT als een koper in {land} vraagt waar hij iets moet kopen? "
        f"Krillo stelt die koopvragen elke maand aan ChatGPT en Gemini, in {len(ov['categorieen'])} "
        f"categorieën met samen {ov['winkels']} webshops, en maakt per categorie een openbare ranglijst.")
    regels.append("")
    if nieuws:
        regels.append("Nieuw bovenaan deze maand:")
        for c in nieuws:
            regels.append(f"- {c['naam_nl']}: {c['nummer_een']} (vorige maand nummer {c['was']})")
        regels.append("")
    if stijgers:
        regels.append("Grootste stijgers:")
        for c in stijgers:
            s = c["stijger"]
            regels.append(f"- {c['naam_nl']}: {s['naam']}, van plek {s['van']} naar plek {s['naar']}")
        regels.append("")
    regels.append("De vaste nummers 1:")
    for c in [c for c in ov["categorieen"] if not c["nieuw_bovenaan"]][:5]:
        regels.append(f"- {c['naam_nl']}: {c['nummer_een']}")
    regels.append("")
    regels.append(
        "Waarom dit ertoe doet: de helft van de Nederlanders gebruikt AI bij het winkelen, en een op de vijf "
        "begint een zoektocht naar een product bij een AI-assistent (Q&A Retail, mei 2026). Wie daar niet "
        "genoemd wordt, bestaat voor die koper niet.")
    regels.append("")
    regels.append(f"Alle ranglijsten en de meetmethode: {basis_url}/index/{ov['land']} en {basis_url}/how-we-measure")
    regels.append("")
    # Stap 164: de ranglijst om in het artikel te plakken. Een redactie hoeft
    # niets over te typen, en elke plaatsing is een link terug.
    if embed:
        regels.append("Ranglijst in uw artikel? Plak deze code (de top 5, werkt zichzelf bij). Voor een andere "
                      "categorie staat de code onderaan elke ranglijst:")
        regels.append(embed(ov["land"], ov["categorieen"][0]["slug"]))
        regels.append("")
    regels.append("Over Krillo: Krillo meet voor webshops of AI-assistenten ze aanbevelen, en helpt ze hoger "
                  "te komen. Contact: hello@krilloai.com")
    return "\n".join(regels)


def linkedin_post(ov, basis_url="https://krilloai.com"):
    """Stap 131: een korte post voor de LinkedIn-bedrijfspagina van Krillo (niet
    het eigen profiel van Nino). Engels, zoals de site. Alleen wat de meting zegt."""
    if not ov["categorieen"]:
        return None
    import sitetaal
    land = sitetaal.landnaam(ov["land"], "en")
    maand = ov["datum"].strftime("%B %Y") if isinstance(ov.get("datum"), datetime) else "this month"
    regels = [f"Which webshops do ChatGPT and Gemini recommend in {land}? The Krillo Index for {maand}.", ""]
    nieuw = [c for c in ov["categorieen"] if c["nieuw_bovenaan"]][:3]
    for c in nieuw:
        regels.append(f"New at #1 in {c['naam']}: {c['nummer_een']} (was #{c['was']})")
    for c in [c for c in ov["categorieen"] if c["stijger"]][:2]:
        s = c["stijger"]
        regels.append(f"Biggest climber in {c['naam']}: {s['naam']}, from #{s['van']} to #{s['naar']}")
    if not nieuw:
        for c in ov["categorieen"][:3]:
            regels.append(f"#1 in {c['naam']}: {c['nummer_een']}")
    regels += ["", f"{len(ov['categorieen'])} categories, {ov['winkels']} stores, the same buying questions for "
               f"every store. Where does your store rank?", f"{basis_url}/index/{ov['land']}"]
    return "\n".join(regels)
