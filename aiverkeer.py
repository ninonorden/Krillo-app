"""Brengt AI de klant bezoekers en verkoop? (7 oktober)

WAAROM DIT BESTAND BESTAAT

Nino, 7 oktober: "genoemd worden door AI is op zichzelf nog geen bewijs van
ROI. AI-zichtbaarheid, klik, engagement, conversie, omzet: dit moet een klant
echt zien." Krillo meet de eerste schakel (genoemd worden) zelf. De rest staat
in Google Analytics of Shopify van de klant, en daar kunnen wij nog niet bij
(de Shopify-app wacht op goedkeuring, stap 256).

Dus: de klant zet een keer per maand drie getallen uit zijn eigen statistieken
in het dashboard (bezoek uit AI, bestellingen daaruit, omzet daaruit). Wij
zetten ze naast zijn plek bij AI, met de eerste maand als nulmeting. Zo ziet
hij de hele keten op een plek, met zijn eigen cijfers, en verzinnen wij niets.

Opslag: een instelling per winkel, JSON per maand. Geen nieuwe tabel nodig.
"""
import json
import re

import db

MAANDVORM = re.compile(r"^20\d\d-(0[1-9]|1[0-2])$")


def _sleutel(webshop_url):
    return "aiverkeer:" + (webshop_url or "").strip().lower()[:200]


def lees(webshop_url):
    """Alle maanden, oudste eerst. Altijd een lijst.

    Stap 304 (7 oktober): staat de Krillo-pixel op de site, dan komen de
    cijfers daar vandaan en hoeft de klant niets in te vullen. Een maand die de
    klant zelf invulde en waar geen pixel voor is (een maand van voor de pixel)
    blijft staan. Elke rij zegt waar hij vandaan komt."""
    try:
        ruw = json.loads(db.get_instelling(_sleutel(webshop_url)) or "{}")
    except (ValueError, TypeError):
        ruw = {}
    rijen = {m: dict(maand=m, bron="handmatig", **ruw[m]) for m in ruw if MAANDVORM.match(m)}
    try:
        import pixel
        for m, w in pixel.per_maand(webshop_url).items():
            if MAANDVORM.match(m or ""):
                rijen[m] = dict(maand=m, bron="pixel", bezoek=w["bezoek"], orders=w["orders"],
                                omzet=round(w["omzet"], 2))
    except Exception as e:
        print(f"Pixelcijfers ophalen mislukt voor {webshop_url}: {e}")
    return [rijen[m] for m in sorted(rijen)]


def _getal(waarde, komma=False):
    """Een getal uit een formulierveld. Leeg of onzin wordt None, nooit een fout:
    een klant die een veld overslaat moet de rest gewoon kunnen bewaren."""
    tekst = str(waarde or "").strip().replace("€", "").replace(" ", "")
    if not tekst:
        return None
    # 1.234,56 en 1,234.56 en 1234,56: alles wat na de laatste scheiding twee
    # cijfers heeft is een bedrag met centen.
    if komma and re.search(r"[.,]\d{1,2}$", tekst):
        heel, cent = re.split(r"[.,](?=\d{1,2}$)", tekst)
        tekst = re.sub(r"[.,]", "", heel) + "." + cent
    else:
        tekst = re.sub(r"[.,]", "", tekst)
    try:
        getal = float(tekst) if komma else int(tekst)
    except ValueError:
        return None
    return getal if getal >= 0 else None


def bewaar(webshop_url, maand, bezoek, orders, omzet):
    """Een maand bewaren (of overschrijven). Geeft False bij een foute maand of
    als er niets bruikbaars is ingevuld."""
    if not MAANDVORM.match(maand or ""):
        return False
    rij = {"bezoek": _getal(bezoek), "orders": _getal(orders), "omzet": _getal(omzet, komma=True)}
    if all(v is None for v in rij.values()):
        return False
    try:
        ruw = json.loads(db.get_instelling(_sleutel(webshop_url)) or "{}")
    except (ValueError, TypeError):
        ruw = {}
    ruw[maand] = rij
    # Hooguit 24 maanden: twee jaar is genoeg om elke verandering te zien.
    for oud in sorted(ruw)[:-24]:
        ruw.pop(oud, None)
    db.zet_instelling(_sleutel(webshop_url), json.dumps(ruw))
    return True


def _plek_per_maand(verloop):
    """De plek bij AI per maand uit het verloop van de maandmeting."""
    uit = {}
    for r in verloop or []:
        op = r.get("afgerond_op")
        if op is not None and r.get("positie"):
            uit[op.strftime("%Y-%m")] = r["positie"]
    return uit


def fix_maanden(webshop_url):
    """De maanden waarin een fix live ging (uitvoeringen.opgeleverd_op).

    7 oktober (Nino): "markeer welke stijging samenvalt met Krillo-fixes". Zo
    ziet de klant in zijn eigen tabel welke maand na een fix kwam. Nooit een
    fout: dan geen markering."""
    if not webshop_url:
        return set()
    conn = db._get_connection()
    if conn is None:
        return set()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT to_char(opgeleverd_op AT TIME ZONE 'Europe/Amsterdam', 'YYYY-MM')
                             FROM uitvoeringen WHERE webshop_url = %s AND opgeleverd_op IS NOT NULL""",
                        (webshop_url,))
            return {r[0] for r in cur.fetchall()}
    except Exception as e:
        print(f"Fixmaanden ophalen mislukt voor {webshop_url}: {e}")
        return set()
    finally:
        conn.close()


def _verschil(nu, toen):
    if nu is None or not toen:
        return None
    return round((nu - toen) / toen * 100)


def overzicht(webshop_url, verloop=None, rijen=None, maandprijs=None):
    """De keten per maand en het oordeel van de laatste maand tegen de eerste.

    rijen: om een voorbeeld te tonen zonder database (demo en voorproef).
    maandprijs: wat Krillo deze klant per maand kost. Dan rekenen we ook het
    rendement uit (7 oktober, Nino: "laten zien dat de ROI omhoog gaat")."""
    voorbeeld = rijen is not None
    rijen = lees(webshop_url) if rijen is None else rijen
    plek = _plek_per_maand(verloop)
    fixen = set() if voorbeeld else fix_maanden(webshop_url)
    for r in rijen:
        r["fix"] = r.get("fix") or r["maand"] in fixen
    for r in rijen:
        r["plek"] = r.get("plek") or plek.get(r["maand"])
        b, o = r.get("bezoek"), r.get("orders")
        r["conversie"] = round(o / b * 100, 1) if b and o is not None else None
    oordeel = None
    if len(rijen) >= 2:
        eerst, laatst = rijen[0], rijen[-1]
        oordeel = {"van": eerst["maand"], "tot": laatst["maand"],
                   "bezoek": _verschil(laatst.get("bezoek"), eerst.get("bezoek")),
                   "orders": _verschil(laatst.get("orders"), eerst.get("orders")),
                   "omzet": _verschil(laatst.get("omzet"), eerst.get("omzet")),
                   "plek_van": eerst.get("plek"), "plek_tot": laatst.get("plek")}
        # Het rendement: extra omzet uit AI tegen de nulmeting, gedeeld door
        # wat Krillo die maand kost. Bewust de omzet van EEN maand tegen EEN
        # maandprijs, geen opgetelde bedragen: dat is na te rekenen door de
        # klant zelf, en het overdrijft niet.
        if laatst.get("omzet") is not None and eerst.get("omzet") is not None:
            extra = round(laatst["omzet"] - eerst["omzet"])
            oordeel["extra_omzet"] = extra
            if maandprijs and extra > 0:
                oordeel["maandprijs"] = maandprijs
                oordeel["keer"] = round(extra / maandprijs, 1)
    return {"rijen": rijen, "oordeel": oordeel}


def samen(minimum=3):
    """Alle klanten samen, zonder namen: hoeveel winkels, en hoeveel daarvan
    meer bezoek en omzet uit AI hebben dan in hun eerste maand.

    Dit is het publieke bewijs op /proof. Het verschijnt pas vanaf "minimum"
    winkels met twee of meer maanden: met een of twee winkels zegt het niets
    en kan je ze herkennen. Tot die tijd staat er niets, en zeggen we eerlijk
    dat de eerste uitkomsten nog lopen. Nooit verzonnen cijfers."""
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT waarde FROM instellingen WHERE sleutel LIKE 'aiverkeer:%%'")
            waarden = [r[0] for r in cur.fetchall()]
    except Exception as e:
        print(f"AI-verkeer samen ophalen mislukt: {e}")
        return None
    finally:
        conn.close()
    winkels = bezoek_op = omzet_op = 0
    for w in waarden:
        try:
            ruw = json.loads(w or "{}")
        except ValueError:
            continue
        maanden = [ruw[m] for m in sorted(ruw) if MAANDVORM.match(m)]
        if len(maanden) < 2:
            continue
        winkels += 1
        eerst, laatst = maanden[0], maanden[-1]
        if (laatst.get("bezoek") or 0) > (eerst.get("bezoek") or 0):
            bezoek_op += 1
        if (laatst.get("omzet") or 0) > (eerst.get("omzet") or 0):
            omzet_op += 1
    if winkels < minimum:
        return None
    return {"winkels": winkels, "bezoek_op": bezoek_op, "omzet_op": omzet_op}


# Het voorbeeld in /demo en de voorproef. Duidelijk een voorbeeld, nooit echte
# cijfers van iemand anders.
VOORBEELD = [
    {"maand": "2026-07", "bezoek": 41, "orders": 1, "omzet": 64.0, "plek": 14},
    {"maand": "2026-08", "bezoek": 58, "orders": 2, "omzet": 121.0, "plek": 9, "fix": True},
    {"maand": "2026-09", "bezoek": 96, "orders": 4, "omzet": 268.0, "plek": 5},
]


def voorbeeld():
    return overzicht(None, rijen=[dict(r) for r in VOORBEELD], maandprijs=49)
