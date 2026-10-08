"""De Krillo-pixel: bezoek, bestellingen en omzet uit AI, automatisch (stap 304, 7 oktober 2026).

WAAROM DIT BESTAAT

Nino, 7 oktober: "dit moet toch automatisch berekend worden, niet dat de klant
dit hoeft in te vullen". Klopt. Krillo ziet de bestellingen van een winkel
niet; die staan in zijn eigen Shopify of Google Analytics. De Shopify-app
(stap 256) wacht op goedkeuring en een koppeling met Google Analytics vraagt
weken controle door Google. Een eigen pixel kan meteen:

- Shopify: de klant plakt een stukje code bij Instellingen > Klantgebeurtenissen
  (een "aangepaste pixel"). Daar is geen app-goedkeuring voor nodig.
- WooCommerce en andere platforms: een stukje code in de kop van de site.

Wat de pixel doet, en niet meer dan dat:
- komt een bezoeker binnen vanaf ChatGPT, Gemini, Perplexity of Copilot (aan
  het adres waar hij vandaan komt, of aan utm_source dat ChatGPT zelf meegeeft),
  dan telt hij een AI-bezoek, een keer per bezoek;
- rekent die bezoeker af, dan telt hij een bestelling met het bedrag.
Er gaan geen namen, mailadressen of andere persoonsgegevens naar Krillo. Het
ordernummer gaat mee, alleen om dezelfde bestelling niet twee keer te tellen.

De sleutel in de code is NIET de dashboardlink van de klant (die is zijn
inlog). Elke winkel krijgt een eigen, losse pixelsleutel.
"""
import secrets

import db

AI_BRONNEN = {
    "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT",
    "gemini.google.com": "Gemini", "bard.google.com": "Gemini",
    "perplexity.ai": "Perplexity", "www.perplexity.ai": "Perplexity",
    "copilot.microsoft.com": "Copilot",
}
SOORTEN = ("sessie", "order")
# 8 oktober (Nino: "hoe weet ik dat de pixel erin staat?"). Een testbezoek met
# ?utm_source=krillo-check komt binnen als soort "test" (en een bestelling in
# dat bezoek als "testorder"). Zo kan de knop "Check my pixel" zien dat de
# pixel werkt, zonder dat het testbezoek meetelt als bezoek uit AI.
TEST_BRON = "krillo-check"
TEST_NAAM = "Test"


def _sql(opdracht, waarden=None, alles=False):
    conn = db._get_connection()
    if conn is None:
        return [] if alles else None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(opdracht, waarden)
                if cur.description is None:
                    return None
                return cur.fetchall() if alles else cur.fetchone()
    finally:
        conn.close()


def maak_tabel():
    _sql("""CREATE TABLE IF NOT EXISTS pixel_sleutels (
                sleutel TEXT PRIMARY KEY,
                webshop_url TEXT UNIQUE NOT NULL,
                aangemaakt_op TIMESTAMPTZ DEFAULT now())""")
    _sql("""CREATE TABLE IF NOT EXISTS pixel_meldingen (
                id SERIAL PRIMARY KEY,
                webshop_url TEXT NOT NULL,
                soort TEXT NOT NULL,
                bron TEXT,
                bedrag NUMERIC,
                valuta TEXT,
                order_id TEXT,
                op TIMESTAMPTZ DEFAULT now())""")
    _sql("CREATE INDEX IF NOT EXISTS pixel_meldingen_winkel ON pixel_meldingen (webshop_url, op)")
    # Dezelfde bestelling telt maar een keer, ook als de bedanktpagina twee keer laadt.
    _sql("""CREATE UNIQUE INDEX IF NOT EXISTS pixel_order_uniek ON pixel_meldingen (webshop_url, order_id)
            WHERE order_id IS NOT NULL""")


def sleutel_voor(webshop_url):
    """De pixelsleutel van een winkel; maakt er een als die er nog niet is."""
    maak_tabel()
    rij = _sql("SELECT sleutel FROM pixel_sleutels WHERE webshop_url = %s", (webshop_url,))
    if rij:
        return rij[0]
    nieuw = "kp_" + secrets.token_hex(8)
    _sql("""INSERT INTO pixel_sleutels (sleutel, webshop_url) VALUES (%s, %s)
            ON CONFLICT (webshop_url) DO NOTHING""", (nieuw, webshop_url))
    rij = _sql("SELECT sleutel FROM pixel_sleutels WHERE webshop_url = %s", (webshop_url,))
    return rij[0] if rij else nieuw


def winkel_bij_sleutel(sleutel):
    if not sleutel or not str(sleutel).startswith("kp_") or len(sleutel) > 40:
        return None
    maak_tabel()
    rij = _sql("SELECT webshop_url FROM pixel_sleutels WHERE sleutel = %s", (sleutel,))
    return rij[0] if rij else None


def _bedrag(waarde):
    try:
        n = round(float(str(waarde).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None
    # Een bedrag onder nul of absurd hoog is een fout in de pagina, geen bestelling.
    return n if 0 <= n < 1_000_000 else None


def noteer(sleutel, soort, bron=None, bedrag=None, valuta=None, order_id=None):
    """Een melding van de pixel. Geeft True als hij is opgeslagen."""
    webshop_url = winkel_bij_sleutel(sleutel)
    if not webshop_url or soort not in SOORTEN:
        return False
    test = bron == TEST_NAAM
    bron = bron if (bron in set(AI_BRONNEN.values()) or test) else None
    if soort == "order":
        bedrag = _bedrag(bedrag)
        if bedrag is None:
            return False
    else:
        bedrag = None
    if test:
        soort = "testorder" if soort == "order" else "test"
    try:
        _sql("""INSERT INTO pixel_meldingen (webshop_url, soort, bron, bedrag, valuta, order_id)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
             (webshop_url, soort, bron, bedrag, (valuta or "EUR")[:3].upper(),
              (str(order_id)[:64] if order_id else None)))
        return True
    except Exception as e:
        print(f"Pixelmelding opslaan mislukt voor {webshop_url}: {e}")
        return False


def per_maand(webshop_url):
    """{"2026-10": {"bezoek": n, "orders": n, "omzet": euro}} uit de pixel."""
    try:
        maak_tabel()
        rijen = _sql("""SELECT to_char(op AT TIME ZONE 'Europe/Amsterdam', 'YYYY-MM'),
                               count(*) FILTER (WHERE soort = 'sessie'),
                               count(*) FILTER (WHERE soort = 'order'),
                               coalesce(sum(bedrag) FILTER (WHERE soort = 'order'), 0)
                          FROM pixel_meldingen WHERE webshop_url = %s GROUP BY 1""",
                     (webshop_url,), alles=True) or []
    except Exception as e:
        print(f"Pixel per maand mislukt voor {webshop_url}: {e}")
        return {}
    return {m: {"bezoek": b, "orders": o, "omzet": float(z)} for m, b, o, z in rijen}


def status(webshop_url):
    """Is de pixel verbonden? De laatste melding, of None."""
    try:
        maak_tabel()
        rij = _sql("SELECT max(op), count(*) FROM pixel_meldingen WHERE webshop_url = %s", (webshop_url,))
    except Exception:
        return {"verbonden": False}
    # 8 oktober (Nino: "ik zie niet dat er is besteld"). Een testbestelling telt
    # bewust niet mee als omzet uit AI; dus apart laten zien dat hij binnenkwam.
    # Tijden in Amsterdamse tijd: "08:37" terwijl het 10:37 was, verwarde.
    try:
        test = _sql("""SELECT op, bedrag, valuta FROM pixel_meldingen
                        WHERE webshop_url = %s AND soort = 'testorder' ORDER BY op DESC LIMIT 1""",
                    (webshop_url,))
    except Exception:
        test = None
    return {"verbonden": bool(rij and rij[1]), "laatst": _amsterdam(rij[0]) if rij else None,
            "meldingen": (rij[1] if rij else 0),
            "testorder": ({"op": _amsterdam(test[0]), "bedrag": float(test[1]) if test[1] is not None else None,
                           "valuta": test[2]} if test else None)}


def _amsterdam(moment):
    if not moment:
        return moment
    try:
        from zoneinfo import ZoneInfo
        return moment.astimezone(ZoneInfo("Europe/Amsterdam"))
    except Exception:
        return moment


# ---------------------------------------------------------------------------
# De code die de klant plakt
# ---------------------------------------------------------------------------

def _bronnen_js():
    alle = dict(AI_BRONNEN, **{TEST_BRON: TEST_NAAM})
    return "{" + ",".join(f'"{h}":"{n}"' for h, n in alle.items()) + "}"


def sinds(webshop_url, vanaf):
    """Wat de pixel binnenstuurde na een tijdstip (voor de knop "Check my
    pixel"). Geeft {"gezien": bool, "test": bool, "order": bedrag of None}."""
    try:
        maak_tabel()
        rijen = _sql("""SELECT soort, bedrag FROM pixel_meldingen
                         WHERE webshop_url = %s AND op >= %s ORDER BY op""",
                     (webshop_url, vanaf), alles=True) or []
    except Exception as e:
        print(f"Pixelcheck mislukt voor {webshop_url}: {e}")
        return {"gezien": False, "test": False, "order": None}
    order = next((float(b) for s, b in rijen if s in ("order", "testorder") and b is not None), None)
    return {"gezien": bool(rijen), "test": any(s == "test" for s, _ in rijen), "order": order}


def shopify_code(sleutel, basis="https://krilloai.com"):
    """Voor Shopify, Instellingen > Klantgebeurtenissen > Aangepaste pixel.

    Draait in de afgeschermde omgeving van Shopify (analytics.subscribe,
    browser.sessionStorage). Bij het eerste bezoek vanaf AI een sessie, bij
    checkout_completed de bestelling als het bezoek van AI kwam."""
    return f"""// Krillo: visits, orders and revenue from AI. No personal data.
const K = "{sleutel}", U = "{basis.rstrip('/')}/api/pixel", B = {_bronnen_js()};
function bron(url, ref) {{
  try {{ const s = new URL(url).searchParams.get("utm_source") || "";
    for (const h in B) if (s.indexOf(h) > -1) return B[h]; }} catch (e) {{}}
  try {{ const h = new URL(ref).hostname; return B[h] || B[h.replace(/^www\\./, "")] || null; }} catch (e) {{ return null; }}
}}
function stuur(d) {{ fetch(U, {{method: "POST", keepalive: true, body: JSON.stringify(Object.assign({{k: K}}, d))}}); }}
analytics.subscribe("page_viewed", async (e) => {{
  if (await browser.sessionStorage.getItem("krillo_ai")) return;
  const b = bron(e.context.document.location.href, e.context.document.referrer);
  if (b) {{ await browser.sessionStorage.setItem("krillo_ai", b); stuur({{t: "sessie", b: b}}); }}
}});
analytics.subscribe("checkout_completed", async (e) => {{
  const b = await browser.sessionStorage.getItem("krillo_ai");
  if (!b) return;
  const c = e.data.checkout;
  stuur({{t: "order", b: b, v: c.totalPrice && c.totalPrice.amount, c: c.currencyCode,
         o: (c.order && c.order.id) || c.token}});
}});
"""


def site_code(sleutel, basis="https://krilloai.com"):
    """Voor WooCommerce, WordPress en andere platforms: in de kop van elke pagina.

    Telt het AI-bezoek overal. Een bestelling telt hij op de bedankpagina van
    WooCommerce (order-received); op andere platforms alleen het bezoek, tenzij
    die zelf het bedrag doorgeven (window.krilloOrder)."""
    return f"""<script>/* Krillo: visits, orders and revenue from AI. No personal data. */
(function(){{var K="{sleutel}",U="{basis.rstrip('/')}/api/pixel",B={_bronnen_js()};
function s(d){{d.k=K;try{{navigator.sendBeacon?navigator.sendBeacon(U,JSON.stringify(d)):fetch(U,{{method:"POST",keepalive:true,body:JSON.stringify(d)}})}}catch(e){{}}}}
function bron(){{try{{var u=new URLSearchParams(location.search).get("utm_source")||"";for(var h in B)if(u.indexOf(h)>-1)return B[h]}}catch(e){{}}
try{{var r=new URL(document.referrer).hostname;return B[r]||B[r.replace(/^www\\./,"")]||null}}catch(e){{return null}}}}
var b=null;try{{b=sessionStorage.getItem("krillo_ai")}}catch(e){{}}
if(!b){{b=bron();if(b){{try{{sessionStorage.setItem("krillo_ai",b)}}catch(e){{}}s({{t:"sessie",b:b}})}}}}
if(!b)return;
/* De bestelling pas lezen als de pagina er staat: de code zit in de kop. */
function order(){{var o=window.krilloOrder;
var m=location.pathname.match(/order-received\\/(\\d+)/);
if(!o&&m){{var t=document.querySelector(".woocommerce-order-overview__total .amount, .order_details tfoot tr:last-child .amount");
if(t)o={{id:m[1],total:t.textContent.replace(/[^0-9,.]/g,"").replace(/\\.(?=\\d{{3}}\\b)/g,"").replace(",",".")}}}}
if(o&&o.id)s({{t:"order",b:b,v:o.total,c:o.currency||"EUR",o:o.id}})}}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",order);else order();
}})();</script>"""
