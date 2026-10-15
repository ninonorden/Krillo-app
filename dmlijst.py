"""Persoonlijke berichten op LinkedIn aan de top van de ranglijsten (15 oktober 2026).

WAAROM. Ruim 1100 koude mails leverden 0 klanten op, en 96 opvolgmails 0
doorkliks. Een mail van een onbekend bedrijf wordt niet vertrouwd. Een
persoonlijk bericht van een echte ondernemer op LinkedIn wel veel vaker, zeker
als het begint met goed nieuws: "jullie staan op #2". Dit is de warmste opening
die we hebben, en het kost Nino twee minuten per winkel.

Wat dit doet: elke dag hoogstens DAG_MAX winkels uit de top 5 van een
ranglijst, nog nooit benaderd op deze manier, geen klant, niet afgemeld. Per
winkel een kort bericht dat past in een connectieverzoek op LinkedIn (300
tekens), met de link naar de ranglijst. Geen verkooppraatje: een vraag, zodat
er een gesprek komt. Nino stuurt het zelf vanaf zijn eigen profiel (LinkedIn
verbiedt automatisch versturen) en klikt daarna op Gedaan.

Nederlands voor winkels in Nederland en Belgie (het is een persoonlijk bericht
van een Nederlandse ondernemer, net als mailversie e), anders Engels.
"""
import db

DAG_MAX = 10
MAX_PLEK = 5
MAX_TEKENS = 300
SLEUTEL = "dm_linkedin:"


def gedaan(webshop_url):
    return bool(db.get_instelling(SLEUTEL + (webshop_url or "").lower()[:180]))


def zet_gedaan(webshop_url):
    if webshop_url:
        db.zet_instelling(SLEUTEL + webshop_url.lower()[:180], "ja")


def _naam(r):
    naam = r.get("naam")
    if naam and not str(naam).startswith("http"):
        return str(naam)
    return (r.get("webshop_url") or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def bericht(winkel, plek, categorie, land, url):
    """Het bericht, nooit langer dan MAX_TEKENS (de grens van een connectieverzoek)."""
    if (land or "").lower() in ("nl", "be"):
        tekst = (f"Hoi! {winkel} staat op #{plek} in de Krillo Index voor {categorie.lower()}: de webshops die "
                 f"ChatGPT en Gemini aanraden. De top 10: {url} Doen jullie hier bewust iets voor? Ben benieuwd.")
    else:
        tekst = (f"Hi! {winkel} is #{plek} in the Krillo Index for {categorie.lower()}: the stores ChatGPT and "
                 f"Gemini recommend. The top 10: {url} Do you work on this on purpose? Curious.")
    if len(tekst) > MAX_TEKENS:
        overschot = len(tekst) - MAX_TEKENS
        tekst = tekst.replace(winkel, winkel[:max(8, len(winkel) - overschot - 1)], 1)
    return tekst[:MAX_TEKENS]


def lijst_van_vandaag(ranglijsten, basis_url, uitsluiten=()):
    """ranglijsten: [(land, categorie, categorienaam, lijst)]. Geeft de winkels
    voor vandaag, beste plek eerst."""
    kandidaten = []
    gezien = set(u.lower() for u in uitsluiten)
    for land, categorie, naam, lijst in ranglijsten:
        for r in (lijst or {}).get("rijen") or []:
            url = (r.get("webshop_url") or "").lower()
            if not url or url in gezien or (r.get("genoemd") or 0) <= 0 or (r.get("positie") or 99) > MAX_PLEK:
                continue
            gezien.add(url)
            pagina = f"{basis_url.rstrip('/')}/index/{land}/{categorie}?utm_source=linkedin_dm"
            kandidaten.append({"webshop_url": r["webshop_url"], "winkel": _naam(r), "plek": r["positie"],
                               "categorie": naam, "land": land, "pagina": pagina,
                               "bericht": bericht(_naam(r), r["positie"], naam, land, pagina)})
    kandidaten.sort(key=lambda k: (k["plek"], k["categorie"]))
    uit = []
    for k in kandidaten:
        if len(uit) >= DAG_MAX:
            break
        if not gedaan(k["webshop_url"]):
            uit.append(k)
    return uit


def uitgesloten():
    """Klanten en afgemelde winkels krijgen geen bericht."""
    conn = db._get_connection()
    if conn is None:
        return set()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT webshop_url FROM benadering WHERE afgemeld
                               UNION SELECT webshop_url FROM klanten""")
                return {r[0] for r in cur.fetchall() if r[0]}
    except Exception as e:
        print(f"DM-lijst, uitsluiten mislukt: {e}")
        return set()
    finally:
        conn.close()
