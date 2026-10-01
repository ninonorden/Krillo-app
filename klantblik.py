"""De klantblik: elke ochtend alle pagina's nalopen zoals een klant ze ziet (1 oktober 2026).

WAAROM DIT BESTAAT. Nino: "we vinden steeds wel fouten. Kunnen we hier niet iets
op verzinnen dat echt gebruikersfouten worden gevonden in plaats van dat ik jou
steeds moet vragen om te checken?" Klopt: elke controle met de hand vond iets
(een lege waarde, een datum die al voorbij was, Nederlands op een Engelse
pagina, een link die nergens heen ging). De nachtcontrole keek alleen of een
handvol pagina's laadt. Dat is te weinig.

WAT HIJ DOET, elke ochtend voor het ochtendbericht, zonder AI en dus gratis:
1. Hij opent elke openbare pagina, de demo, een paar ranglijsten met hun
   winkelpagina's, en het dashboard van Nino's eigen testwinkels (alle
   pagina's), precies zoals een bezoeker ze krijgt.
2. Hij volgt elke link op die pagina's en kijkt of die werkt.
3. Op elke pagina zoekt hij naar wat een klant als fout ziet:
   - een pagina die niet laadt, of een link naar een pagina die niet bestaat;
   - resten van het sjabloon ({{ of {%), "None", "nan", "undefined";
   - een datum die als "next" of "around" wordt beloofd maar al voorbij is;
   - een bedrag op een prijspagina dat geen prijs van Krillo is;
   - Nederlandse zinnen op een Engelse pagina;
   - lange streepjes (Nino's regel), kladtekst (TODO, Lorem ipsum);
   - een pagina zonder titel, en een pagina die langer dan 4 seconden duurt.
4. Wat hij vindt, staat in het ochtendbericht (alleen de echte fouten) en op
   /admin/klantblik (alles, met een tekst om aan Claude te geven).

WAT HIJ BEWUST NIET DOET
- Pagina's met een code van een echte winkel of klant openen (/uitkomst, /mijn
  van een klant, /bureau). Dat telt als "bekeken" en zou de verkoopagent laten
  denken dat iemand keek. Alleen Nino's testwinkels.
- Iets repareren. Hij vindt; Claude repareert, met een test erbij, zodat
  dezelfde fout niet terugkomt.
"""
import gc
import html
import json
import re
import time
from datetime import date, datetime

import db

SLEUTEL = "klantblik"
KENMERK = "KrilloKlantblik/1.0 (headless)"
MAX_PAGINAS = 160
MAX_LINKS = 260
PER_PATROON = 6
TRAAG_SECONDEN = 4.0

# Openbare pagina's zonder code in het adres die een bezoeker kan openen.
START = ["/", "/about", "/agencies", "/articles", "/brands", "/changelog", "/chatgpt-visibility-tracker",
         "/compare", "/demo", "/faq", "/gemini-visibility-tracker", "/get-my-link", "/how-we-measure", "/index",
         "/news", "/onderzoek", "/partners", "/privacy", "/shopify-ai-visibility", "/terms", "/tools",
         "/withdrawal", "/login", "/llms.txt", "/robots.txt", "/sitemap.xml"]

# Nooit openen: beheer, achterkant, en alles met de code van een echte winkel.
OVERSLAAN = re.compile(
    r"^/(admin|api|cron|webhooks?|afmelden|uitloggen|static|wakker|shopify(/|$)|oauth|betaal|checkout|mollie|"
    r"embed|v/|plekmelding|lijstje|healthz|\.well-known|uitkomst|bureau|monitoring|mijn/|rapport|r/|badge)"
    r"|\.(png|jpe?g|svg|gif|webp|ico|pdf|zip|webmanifest)$")

# Pagina's waar prijzen staan. Daar moet elk bedrag een prijs van Krillo zijn.
PRIJSPAGINAS = ("/", "/faq", "/terms", "/agencies", "/brands", "/demo/plan", "/shopify-ai-visibility",
                "/chatgpt-visibility-tracker", "/gemini-visibility-tracker")

MAANDEN = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
MAANDEN.update({m: i for i, m in enumerate(
    "januari februari maart april mei juni juli augustus september oktober november december".split(), 1)})

RESTEN = [
    (re.compile(r"\{\{|\}\}|\{%|%\}"), "resten van het sjabloon ({{ of {%)"),
    (re.compile(r"\bNone\b(?! of\b)"), "het woord None (een lege waarde)"),
    (re.compile(r"\bnan\b|\bNaN\b"), "nan (een rekenfout)"),
    (re.compile(r"\bundefined\b"), "undefined (een lege waarde)"),
    (re.compile(r"\[object Object\]"), "[object Object]"),
    (re.compile(r"Traceback \(most recent"), "een foutmelding van de server"),
    (re.compile(r"\bTODO\b|\bFIXME\b|[Ll]orem ipsum"), "kladtekst (TODO of Lorem ipsum)"),
]

NL = set("""de het een en van je jouw niet wij we voor met zijn wordt worden deze dit naar ook maar nog bij uit als
dan wat hoe waar welke winkel winkels jij hebt heeft kun kunt staat staan meer geen alle onze ons""".split())
EN = set("the and of to your you is are for with in on this that it be we our not can store stores".split())


def zichtbare_tekst(bron):
    """De tekst die een bezoeker leest: zonder scripts, stijl, opmerkingen en tags."""
    t = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", bron or "")
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return " ".join(html.unescape(t).split())


def _taal(bron):
    m = re.search(r"<html[^>]*\blang=[\"']?([a-zA-Z]{2})", bron or "")
    return m.group(1).lower() if m else None


def _datum(dag, maand, vandaag):
    try:
        d = date(vandaag.year, MAANDEN[maand.lower()], int(dag))
    except (KeyError, ValueError):
        return None
    # "around 2 January" in oktober betekent volgend jaar.
    if (vandaag - d).days > 200:
        d = date(vandaag.year + 1, d.month, d.day)
    return d


BELOFTE = re.compile(r"\b(next|around|upcoming|expected|volgende|rond|verwacht)\b[^.!?]{0,50}?\b(\d{1,2})"
                     r"(?:st|nd|rd|th)?\s+(" + "|".join(MAANDEN) + r")\b", re.I)


def voorbije_beloftes(tekst, vandaag=None):
    """Datums die als toekomst worden beloofd ("next around 30 October") maar al voorbij zijn."""
    vandaag = vandaag or date.today()
    uit = []
    for m in BELOFTE.finditer(tekst or ""):
        d = _datum(m.group(2), m.group(3), vandaag)
        if d and d < vandaag:
            uit.append(m.group(0)[-60:])
    return uit


def toegestane_prijzen():
    """Elke prijs van Krillo, als getal: 49, 490, 149, 1490, ... plus 0 (gratis)."""
    import payments
    uit = {0.0}
    for p in payments.PAKKETTEN.values():
        for veld in ("prijs", "jaarprijs"):
            if p.get(veld):
                uit.add(float(p[veld]["value"]))
    return uit


def _getal(ruw):
    ruw = ruw.strip().rstrip(".,")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", ruw):
        ruw = ruw.replace(",", "")
    elif re.fullmatch(r"\d+,\d{2}", ruw):
        ruw = ruw.replace(",", ".")
    try:
        return float(ruw)
    except ValueError:
        return None


def vreemde_bedragen(tekst, toegestaan=None):
    toegestaan = toegestaan or toegestane_prijzen()
    uit = []
    for m in re.finditer(r"(?:€|EUR)\s?(\d[\d.,]*)", tekst or ""):
        n = _getal(m.group(1))
        if n is not None and n not in toegestaan:
            uit.append(m.group(0))
    return sorted(set(uit))


def nederlandse_zinnen(tekst):
    """Zinnen die duidelijk Nederlands zijn (voor een Engelse pagina)."""
    uit = []
    for zin in re.split(r"(?<=[.!?])\s+", tekst or ""):
        # Bewust Nederlands en dus geen fout: de koopvragen (zoals Nederlandse
        # kopers ze stellen, eindigen op een vraagteken) en wat AI letterlijk
        # antwoordde (tussen aanhalingstekens, of met winkeladressen erin).
        if zin.rstrip().endswith("?") or "\u201c" in zin or "\u201d" in zin or \
                re.search(r"\b[\w-]+\.(nl|be|com|de|fr|eu|shop|store)\b", zin):
            continue
        woorden = re.findall(r"[a-zA-Z']+", zin.lower())
        if len(woorden) < 6:
            continue
        nl = {w for w in woorden if w in NL}
        en = sum(1 for w in woorden if w in EN)
        if len(nl) >= 3 and len(nl) > en:
            uit.append(zin[:90])
    return uit


def keur(pad, bron, soort="text/html", vandaag=None, toegestaan=None):
    """Alle tekstcontroles op een pagina. Geeft lijst van (ernst, tekst)."""
    uit = []
    if "html" not in soort:
        for patroon, wat in RESTEN[:1]:
            if patroon.search(bron or ""):
                uit.append(("fout", wat))
        return uit
    tekst = zichtbare_tekst(bron)
    for patroon, wat in RESTEN:
        if patroon.search(tekst):
            uit.append(("fout", wat))
    for b in voorbije_beloftes(tekst, vandaag)[:2]:
        uit.append(("fout", f"een datum die al voorbij is maar als toekomst staat: \"{b}\""))
    if pad.split("?")[0] in PRIJSPAGINAS or re.match(r"^/mijn/[^/]+/plan$", pad):
        for b in vreemde_bedragen(tekst, toegestaan):
            uit.append(("fout", f"het bedrag {b} is geen prijs van Krillo"))
    if _taal(bron) == "en":
        for z in nederlandse_zinnen(tekst)[:2]:
            uit.append(("fout", f"Nederlands op een Engelse pagina: \"{z}\""))
    if "—" in tekst:
        i = tekst.index("—")
        uit.append(("waarschuwing", f"een lang streepje: \"{tekst[max(0, i - 30):i + 20]}\""))
    if not re.search(r"<title>\s*[^<\s][^<]*</title>", bron or "", re.I):
        uit.append(("waarschuwing", "geen titel (het tabblad en Google tonen dan niets)"))
    return uit


def _patroon(pad):
    stukken = [s for s in pad.split("?")[0].split("/") if s]
    if len(stukken) <= 1:
        return pad
    return "/" + stukken[0] + "/*" * (len(stukken) - 1)


def testklanten(limiet=2):
    """Nino's eigen testwinkels met een dashboard. Echte klanten nooit."""
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT klant_token FROM klanten WHERE is_test AND klant_token IS NOT NULL
                           AND opgezegd_op IS NULL ORDER BY aangemaakt_op DESC LIMIT %s""", (int(limiet),))
            return [r[0] for r in cur.fetchall()]
    except Exception as e:
        print(f"Klantblik, testklanten ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def ronde(app, vandaag=None, extra=None):
    """Alles nalopen. Geeft {"op", "paginas", "links", "fout": [...], "waarschuwing": [...]}."""
    import dashboardpaginas
    begin = time.time()
    client = app.test_client()
    kop = {"User-Agent": KENMERK}
    toegestaan = toegestane_prijzen()
    bevindingen = {}          # (ernst, tekst) -> [paden]
    gezien, status = set(), {}
    per_patroon = {}

    def noteer(ernst, tekst, pad):
        lijst = bevindingen.setdefault((ernst, tekst), [])
        if pad not in lijst:
            lijst.append(pad)

    eigen = []
    for t in testklanten():
        eigen.append(f"/mijn/{t}")
        eigen += [f"/mijn/{t}/{pad}" for _, pad, _ in dashboardpaginas.PAGINAS if pad]
    demo = [f"/demo/{pad}" for _, pad, _ in dashboardpaginas.PAGINAS if pad]
    rij = list(START) + demo + eigen + list(extra or [])
    toegelaten_mijn = tuple(f"/mijn/{p.split('/')[2]}" for p in eigen)

    def mag(pad):
        if re.search(r"\.(png|jpe?g|svg|gif|webp|ico|pdf|zip|webmanifest)$", pad):
            return False  # een pdf maken kost geheugen; laden zegt niets over de tekst
        if pad.startswith(toegelaten_mijn):
            return True
        return not OVERSLAAN.search(pad)

    def haal(pad):
        if pad in status:
            return status[pad], None, None, 0
        t0 = time.time()
        try:
            r = client.get(pad, headers=kop)
            code = r.status_code
        except Exception as e:
            status[pad] = 500
            noteer("fout", f"de pagina geeft een fout: {type(e).__name__}", pad)
            return 500, None, None, 0
        status[pad] = code
        return code, r, (r.mimetype or ""), time.time() - t0

    bron_van = {}             # link -> de pagina waar hij op stond
    i = 0
    while i < len(rij) and len(gezien) < MAX_PAGINAS:
        pad = rij[i]
        i += 1
        if pad in gezien:
            continue
        gezien.add(pad)
        code, r, soort, duur = haal(pad)
        waar = bron_van.get(pad)
        if code >= 400:
            if waar:
                noteer("fout", f"een link naar {pad} werkt niet ({code})", waar)
            else:
                noteer("fout", f"de pagina laadt niet ({code})", pad)
            continue
        if r is None or code != 200:
            continue
        if duur > TRAAG_SECONDEN:
            noteer("waarschuwing", f"traag: meer dan {TRAAG_SECONDEN:g} seconden", pad)
        if not (soort.startswith("text/") or soort.endswith(("json", "xml"))):
            continue  # een plaatje of pdf: geladen is goed genoeg
        try:
            bron = r.get_data(as_text=True)
        except UnicodeDecodeError:
            continue
        for ernst, tekst in keur(pad, bron, soort, vandaag, toegestaan):
            noteer(ernst, tekst, pad)
        if "html" not in soort:
            continue
        # Alleen eigen adressen; "//fonts.googleapis.com" begint ook met een
        # schuine streep maar is een andere site.
        for link in re.findall(r'href="(/(?!/)[^"#]*)"', bron):
            link = html.unescape(link).split("?")[0] or "/"
            if link in gezien or link in bron_van or link in rij or not mag(link) or "{{" in link:
                continue
            bron_van[link] = pad
            p = _patroon(link)
            if per_patroon.get(p, 0) < PER_PATROON:
                # Openen en lezen, net als de rest.
                per_patroon[p] = per_patroon.get(p, 0) + 1
                rij.append(link)
            elif len(status) < MAX_LINKS:
                # Genoeg van dit soort gelezen: alleen kijken of de link werkt.
                c2, _, _, _ = haal(link)
                if c2 >= 400:
                    noteer("fout", f"een link naar {link} werkt niet ({c2})", pad)
    gc.collect()

    def lijst(ernst):
        uit = [{"tekst": t, "paginas": p[:8], "aantal": len(p)} for (e, t), p in bevindingen.items() if e == ernst]
        return sorted(uit, key=lambda x: -x["aantal"])

    return {"op": datetime.now().isoformat(timespec="minutes"), "paginas": len(gezien),
            "links": len(status), "duur": round(time.time() - begin, 1), "gelezen": sorted(gezien),
            "fout": lijst("fout"), "waarschuwing": lijst("waarschuwing")}


def draai(app):
    """Voor de wachtklok: nalopen en bewaren. Mag nooit iets laten omvallen."""
    try:
        uit = ronde(app)
    except Exception as e:
        uit = {"op": datetime.now().isoformat(timespec="minutes"), "paginas": 0, "links": 0,
               "fout": [{"tekst": f"de klantblik zelf liep vast: {type(e).__name__}: {e}"[:200],
                         "paginas": [], "aantal": 1}], "waarschuwing": []}
    # Bewaren zonder de lijst gelezen pagina's, en nooit afgekapt (afgekapte
    # JSON is onleesbaar): te lang, dan minder voorbeelden per bevinding.
    bewaar = {k: v for k, v in uit.items() if k != "gelezen"}
    tekst = json.dumps(bewaar)
    if len(tekst) > 60000:
        for ernst in ("fout", "waarschuwing"):
            bewaar[ernst] = [dict(f, paginas=f["paginas"][:2]) for f in bewaar[ernst][:40]]
        tekst = json.dumps(bewaar)
    try:
        db.zet_instelling(SLEUTEL, tekst)
    except Exception as e:
        print(f"Klantblik bewaren mislukt: {e}")
    print(f"Klantblik: {uit['paginas']} pagina's, {len(uit['fout'])} fout(en), "
          f"{len(uit['waarschuwing'])} waarschuwing(en).")
    return uit


def laatste():
    try:
        return json.loads(db.get_instelling(SLEUTEL) or "{}")
    except Exception:
        return {}


def tekst_voor_claude(uit=None):
    uit = uit or laatste()
    if not uit.get("fout") and not uit.get("waarschuwing"):
        return ""
    regels = [f"De klantblik van {uit.get('op', '?')} vond dit op krilloai.com. Repareer het, met een test "
              f"erbij zodat het niet terugkomt:"]
    for ernst in ("fout", "waarschuwing"):
        for f in uit.get(ernst) or []:
            regels.append(f"- [{ernst}] {f['tekst']} (op {f['aantal']} pagina's, o.a. {', '.join(f['paginas'][:3])})")
    return "\n".join(regels)
