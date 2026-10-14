"""Neon-verbruik in het ochtendbericht (14 oktober 2026).

WAAROM DIT BESTAAT. Op 10 oktober liep het gratis plan van Neon tegen de grens
van 5 GB dataverkeer aan, en dat zag niemand aankomen: het stond nergens. Nu
staat het elke ochtend in het bericht, zodat een lek (zoals de winkelpagina's
die alle AI-antwoorden ophaalden) binnen een dag opvalt in plaats van na een
maand.

HOE. Neon geeft per project het verbruik van de lopende periode terug
(dataverkeer, rekentijd, opslag). Daarvoor zijn twee dingen nodig in Render:
NEON_API_KEY (een sleutel uit Neon, Account settings > API keys) en
NEON_PROJECT_ID (Neon, Project settings > General). Zonder die twee laten we
alleen de grootte van de database zien, want die kunnen we zelf vragen.

Geen sleutels in de code, en een fout hier mag het ochtendbericht nooit laten
omvallen: dan staat er "onbekend".
"""
import os

import db

API = "https://console.neon.tech/api/v2/projects/{}"

# Neon Launch, opgezocht op 14 oktober 2026 (neon.com/docs/introduction/plans).
# Een startpunt, geen contract: de factuur in Neon telt.
PRIJS_CU_UUR_DOLLAR = 0.106
INBEGREPEN_VERKEER_GB = 500
# Boven dit verkeer per periode komt er een regel bij "wat jij moet doen".
# Met de oplossingen van 14 oktober hoort het ver onder de 50 GB te blijven.
WAARSCHUW_GB = float(os.environ.get("NEON_WAARSCHUW_GB", "50"))


def _gb(b):
    return round((b or 0) / 1e9, 2)


def project(get=None):
    """Het verbruik van deze periode volgens Neon, of None (geen sleutels, of Neon onbereikbaar)."""
    sleutel, pid = os.environ.get("NEON_API_KEY"), os.environ.get("NEON_PROJECT_ID")
    if not sleutel or not pid:
        return None
    if get is None:
        import requests
        get = requests.get
    try:
        r = get(API.format(pid), headers={"Authorization": f"Bearer {sleutel}", "Accept": "application/json"},
                timeout=10)
        if r.status_code != 200:
            print(f"Neon-verbruik: status {r.status_code}")
            return None
        p = (r.json() or {}).get("project") or {}
    except Exception as e:
        print(f"Neon-verbruik ophalen mislukt: {e}")
        return None
    cu_uur = round((p.get("compute_time_seconds") or 0) / 3600, 1)
    return {
        "verkeer_gb": _gb(p.get("data_transfer_bytes")),
        "geschreven_gb": _gb(p.get("written_data_bytes")),
        "opslag_gb": _gb(p.get("synthetic_storage_size")),
        "cu_uur": cu_uur,
        "actief_uur": round((p.get("active_time_seconds") or 0) / 3600, 1),
        "rekenkosten_dollar": round(cu_uur * PRIJS_CU_UUR_DOLLAR, 2),
        "sinds": (p.get("consumption_period_start") or "")[:10],
    }


def database_mb():
    """Hoe groot de database is. Kan altijd, ook zonder Neon-sleutel."""
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database())")
                return round(cur.fetchone()[0] / 1e6, 1)
    except Exception as e:
        print(f"Databasegrootte mislukt: {e}")
        return None
    finally:
        conn.close()


def regels(get=None):
    """(regels voor 'wat de agents deden', waarschuwing of None)."""
    uit, waarschuwing = [], None
    p = project(get=get)
    if p:
        uit.append((f"Neon dataverkeer sinds {p['sinds'] or 'begin periode'} (GB, {INBEGREPEN_VERKEER_GB} inbegrepen)",
                    p["verkeer_gb"]))
        uit.append(("Neon rekentijd deze periode (CU-uur, ongeveer dollar)",
                    f"{p['cu_uur']} (${p['rekenkosten_dollar']:.2f})"))
        if p["verkeer_gb"] >= WAARSCHUW_GB:
            waarschuwing = (f"Neon: al {p['verkeer_gb']} GB dataverkeer deze periode (grens voor deze melding "
                            f"{WAARSCHUW_GB:g} GB). Er lekt weer iets: geef dit aan Claude")
    else:
        uit.append(("Neon-verbruik (zet NEON_API_KEY en NEON_PROJECT_ID in Render)", "onbekend"))
    mb = database_mb()
    uit.append(("Grootte van de database (MB)", mb if mb is not None else "onbekend"))
    return uit, waarschuwing
