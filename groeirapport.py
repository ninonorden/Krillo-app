"""Het maandelijkse AI-groeirapport (stap 292, 7 oktober 2026).

WAAROM DIT BESTAND BESTAAT

Nino, 7 oktober: elke maand een kort rapport met de rank, de grootste winst
en daling, nieuwe en verloren vragen, wie je inhaalde, welke fixes live gingen
en wat AI opleverde. Het meeste stond al in de maandmail (plek, rendement,
concurrent-alarm). Dit bestand voegt de twee dingen toe die nog ontbraken:
- welke koopvragen je deze maand WON en welke je VERLOOR, tegen de vorige meting;
- hoeveel fixes er de afgelopen maand live gingen.
Zo ziet een klant (of het bureau dat het doorstuurt) in een mail wat er
veranderde en waardoor. Kost niets: alles komt uit metingen die er al zijn.
"""
import db

MAX_VRAGEN = 3


def vorige_ronde(ronde):
    """De meting van dezelfde categorie en hetzelfde land die hiervoor kwam."""
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT max(r.id) FROM categorie_rondes r, categorie_rondes d
                            WHERE d.id = %s AND r.categorie = d.categorie
                              AND r.land IS NOT DISTINCT FROM d.land
                              AND r.id < d.id AND r.afgerond_op IS NOT NULL""", (ronde,))
            rij = cur.fetchone()
            return rij[0] if rij else None
    except Exception as e:
        print(f"Vorige ronde ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def _gewonnen(ronde, webshop_url, naam=None):
    import dashboardpaginas as dp
    vo = dp.vragen_overzicht(ronde, webshop_url, naam)
    return {v["vraag"] for v in (vo or {}).get("vragen", []) if v.get("gewonnen")}


def vragen_verschil(nu, toen):
    """Puur rekenwerk: twee verzamelingen gewonnen vragen."""
    return {"nieuw": sorted(nu - toen)[:MAX_VRAGEN], "kwijt": sorted(toen - nu)[:MAX_VRAGEN],
            "aantal_nieuw": len(nu - toen), "aantal_kwijt": len(toen - nu)}


def fixes_afgelopen_maand(webshop_url):
    conn = db._get_connection()
    if conn is None:
        return 0
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT count(*) FROM uitvoeringen WHERE webshop_url = %s
                              AND opgeleverd_op > now() - interval '31 days'""", (webshop_url,))
            return cur.fetchone()[0] or 0
    except Exception:
        return 0
    finally:
        conn.close()


def zinnen(verschil, fixes=0, taal="en"):
    """De regels voor de maandmail. Leeg als er niets te melden is."""
    uit = []
    nl = taal == "nl"
    if verschil.get("aantal_nieuw"):
        vb = "; ".join(f"“{v}”" for v in verschil["nieuw"])
        uit.append((f"Nieuw gewonnen: {verschil['aantal_nieuw']} vraag/vragen waar AI je nu noemt, zoals {vb}."
                    if nl else
                    f"Won this month: {verschil['aantal_nieuw']} question{'s' if verschil['aantal_nieuw'] != 1 else ''} "
                    f"where AI now names you, such as {vb}."))
    if verschil.get("aantal_kwijt"):
        vb = "; ".join(f"“{v}”" for v in verschil["kwijt"])
        uit.append((f"Verloren: {verschil['aantal_kwijt']}, zoals {vb}. Op je dashboard staat wat je eraan doet."
                    if nl else
                    f"Lost this month: {verschil['aantal_kwijt']}, such as {vb}. Your dashboard shows what to do."))
    if fixes:
        uit.append((f"Live gezet: {fixes} fix(es) in je winkel." if nl else
                    f"Went live: {fixes} fix{'es' if fixes != 1 else ''} in your store."))
    return uit


def voor_klant(ronde, webshop_url, naam=None, taal="en"):
    """Alles voor een klant na een meting. Nooit een fout: dan een lege lijst."""
    try:
        vorige = vorige_ronde(ronde)
        if not vorige:
            return zinnen({}, fixes_afgelopen_maand(webshop_url), taal)
        verschil = vragen_verschil(_gewonnen(ronde, webshop_url, naam), _gewonnen(vorige, webshop_url, naam))
        return zinnen(verschil, fixes_afgelopen_maand(webshop_url), taal)
    except Exception as e:
        print(f"Groeirapport mislukt voor {webshop_url}: {e}")
        return []
