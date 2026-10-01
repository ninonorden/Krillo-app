"""Stap 187: de kaart van een categorie, genoemd tegen aanbevolen (30 september 2026).

WAAROM. Een ranglijst zegt wie het vaakst genoemd wordt. Maar genoemd is iets
anders dan aangeraden: een winkel die in veel antwoorden staat maar nooit de
tip is, heeft een ander probleem dan een winkel die nergens staat. Op een kaart
zie je dat in een oogopslag: rechtsonder staan de winkels die AI wel kent maar
niet aanraadt. Dat is precies het gesprek dat Krillo met een winkel wil voeren,
en het plaatje is goed deelbaar op LinkedIn (de PNG-versie).

Twee vormen uit dezelfde berekening:
- svg(): op de ranglijstpagina, schaalt mee op een telefoon;
- png(): 1200 x 1200 voor LinkedIn, op /index/<land>/<slug>/map.png.
"""
from html import escape

MAX_LABELS = 6


def punten(rijen, telbaar):
    """[(naam, x, y)] met x = deel van de vragen waarin genoemd, y = aangeraden.

    Alleen winkels die minstens een keer genoemd zijn: de rest staat allemaal
    op 0,0 en vertelt niets."""
    telbaar = max(int(telbaar or 0), 1)
    uit = []
    for r in rijen or []:
        g = int(r.get("genoemd") or 0)
        if g <= 0:
            continue
        naam = r.get("naam")
        if not naam or str(naam).startswith("http"):
            naam = (r.get("webshop_url") or "").replace("https://", "").replace("http://", "").replace(
                "www.", "").rstrip("/")
        uit.append((naam, min(g / telbaar, 1.0), min(int(r.get("aanbevolen") or 0) / telbaar, 1.0)))
    return uit


def _schaal(p):
    """De assen lopen tot het hoogste punt (afgerond naar boven op 10%), niet
    altijd tot 100%: anders staat alles in een hoekje."""
    hoogste = max([max(x, y) for _, x, y in p] + [0.1])
    return min(1.0, (int(hoogste * 10) + 1) / 10)


def _vrije_regel(geplaatst, x, y, hoogte, links):
    """Schuift een naam omlaag of omhoog tot hij geen andere naam raakt.

    Zonder dit liggen twee winkels met bijna dezelfde cijfers met hun naam over
    elkaar (1 oktober, toysshop5 en toysshop6 op de testkaart)."""
    for stap in (0, 1, -1, 2, -2, 3, -3):
        kandidaat = y + stap * hoogte
        if all(abs(kandidaat - gy) >= hoogte or abs(x - gx) > hoogte * 12 or gl != links
               for gx, gy, gl in geplaatst):
            geplaatst.append((x, kandidaat, links))
            return kandidaat
    geplaatst.append((x, y, links))
    return y


def svg(rijen, telbaar, breedte=640, hoogte=420, markeer=None):
    """markeer: het webadres van de klant op zijn eigen dashboard. Die stip krijgt
    altijd een naam met "(you)" erachter en een ring, ook als hij buiten de top valt."""
    p = punten(rijen, telbaar)
    jij = None
    if markeer:
        eigen = [r for r in rijen or [] if r.get("webshop_url") == markeer and int(r.get("genoemd") or 0) > 0]
        if eigen:
            jij = punten(eigen, telbaar)[0][0]
    if len(p) < 3:
        return ""
    s = _schaal(p)
    L, R, T, B = 56, 20, 20, 50
    bw, bh = breedte - L - R, hoogte - T - B

    def xy(x, y):
        return L + x / s * bw, T + bh - y / s * bh

    delen = [f'<svg viewBox="0 0 {breedte} {hoogte}" role="img" style="width:100%;height:auto;display:block" '
             f'aria-label="Map: how often each store is named against how often it is recommended">',
             f'<rect x="{L}" y="{T}" width="{bw}" height="{bh}" fill="#FAFAF7" stroke="#E4E2DA"/>',
             # De diagonaal: op die lijn is elke noeming ook een aanrader.
             f'<line x1="{L}" y1="{T + bh}" x2="{L + bw}" y2="{T}" stroke="#E4E2DA" stroke-dasharray="4 4"/>']
    for i in range(0, 11):
        v = s * i / 10
        if i % 2:
            continue
        x, _ = xy(v, 0)
        _, y = xy(0, v)
        delen.append(f'<text x="{x:.0f}" y="{T + bh + 18}" font-size="11" text-anchor="middle" '
                     f'fill="#6E7079" font-family="monospace">{round(v * 100)}%</text>')
        delen.append(f'<text x="{L - 8}" y="{y + 4:.0f}" font-size="11" text-anchor="end" '
                     f'fill="#6E7079" font-family="monospace">{round(v * 100)}%</text>')
    delen.append(f'<text x="{L + bw / 2:.0f}" y="{hoogte - 8}" font-size="12" text-anchor="middle" fill="#0B0C14">'
                 f'Named in % of buying questions</text>')
    delen.append(f'<text x="14" y="{T + bh / 2:.0f}" font-size="12" text-anchor="middle" fill="#0B0C14" '
                 f'transform="rotate(-90 14 {T + bh / 2:.0f})">Recommended in %</text>')
    delen.append(f'<text x="{L + bw - 8}" y="{T + bh - 10}" font-size="11" text-anchor="end" fill="#6E7079">'
                 f'Known, not recommended</text>')
    volgorde = sorted(p, key=lambda t: -(t[1] + t[2]))
    geplaatst = []
    for i, (naam, x, y) in enumerate(volgorde):
        cx, cy = xy(x, y)
        if naam == jij:
            delen.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="none" stroke="#0B0C14" stroke-width="2"/>')
        delen.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{6 if i < MAX_LABELS or naam == jij else 4}" '
                     f'fill="{"#1B3FE0" if i < MAX_LABELS else "#A8B6F5"}"><title>{escape(naam)}</title></circle>')
        if i < MAX_LABELS or naam == jij:
            links = cx > L + bw * 0.7
            ly = _vrije_regel(geplaatst, cx, cy + 4, 14, links)
            tekst = escape(naam[:28]) + (" (you)" if naam == jij else "")
            delen.append(f'<text x="{cx + (-14 if links else 14):.1f}" y="{ly:.1f}" font-size="12" '
                         f'text-anchor="{"end" if links else "start"}" fill="#0B0C14" '
                         f'font-weight="{700 if naam == jij else 400}">{tekst}</text>')
    delen.append("</svg>")
    return "".join(delen)


def png(rijen, telbaar, titel, land, maand=""):
    """1200 x 1200 voor LinkedIn, in de stijl van de andere deelbeelden."""
    from PIL import Image, ImageDraw
    import linkedinagent as la
    p = punten(rijen, telbaar)
    S, N = 2, 1200
    W = N * S
    im = Image.new("RGB", (W, W), la.WIT)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 16 * S), fill=la.BLAUW)
    kop = la._font("SpaceGrotesk-Bold.ttf", 44 * S)
    d.text((80 * S, 120 * S), "KRILLO", font=kop, fill=la.INKT, anchor="ls")
    d.text((80 * S + d.textlength("KRILLO", font=kop) + 16 * S, 120 * S), "INDEX",
           font=la._font("IBMPlexMono-Medium.ttf", 24 * S), fill=la.GRIJS, anchor="ls")
    tf = la._font("SpaceGrotesk-Bold.ttf", 60 * S)
    y = 230 * S
    for regel in la._regels_passend(d, f"{titel}: named is not recommended", tf, W - 160 * S)[:2]:
        d.text((80 * S, y), regel, font=tf, fill=la.INKT, anchor="ls")
        y += 72 * S
    klein = la._font("IBMPlexMono-Medium.ttf", 24 * S)
    d.text((80 * S, y), f"{land} · ChatGPT and Gemini{(' · ' + maand) if maand else ''}", font=klein,
           fill=la.GRIJS, anchor="ls")
    L, T = 150 * S, y + 100 * S
    bw, bh = W - L - 80 * S, W - T - 170 * S
    d.rectangle((L, T, L + bw, T + bh), outline=la.LIJN, width=2 * S)
    d.line((L, T + bh, L + bw, T), fill=la.LIJN, width=2 * S)
    s = _schaal(p) if p else 1.0
    for i in range(0, 11, 2):
        v = s * i / 10
        d.text((L + v / s * bw, T + bh + 36 * S), f"{round(v * 100)}%", font=klein, fill=la.GRIJS, anchor="ms")
        d.text((L - 14 * S, T + bh - v / s * bh + 8 * S), f"{round(v * 100)}%", font=klein, fill=la.GRIJS,
               anchor="rs")
    asf = la._font("SpaceGrotesk-Medium.ttf", 28 * S)
    d.text((L + bw / 2, W - 60 * S), "Named in % of buying questions", font=asf, fill=la.INKT, anchor="ms")
    d.text((L + bw - 16 * S, T + bh - 20 * S), "Known, not recommended", font=klein, fill=la.GRIJS, anchor="rs")
    d.text((L - 14 * S, T - 26 * S), "Recommended in %", font=asf, fill=la.INKT, anchor="ls")
    naamf = la._font("SpaceGrotesk-Medium.ttf", 26 * S)
    geplaatst = []
    for i, (naam, x, yv) in enumerate(sorted(p, key=lambda t: -(t[1] + t[2]))):
        cx, cy = L + x / s * bw, T + bh - yv / s * bh
        r = (12 if i < MAX_LABELS else 8) * S
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=la.BLAUW if i < MAX_LABELS else la.LICHT)
        if i < MAX_LABELS:
            links = cx > L + bw * 0.7
            ly = _vrije_regel(geplaatst, cx, cy + 9 * S, 32 * S, links)
            d.text((cx + (-20 if links else 20) * S, ly), naam[:26], font=naamf, fill=la.INKT,
                   anchor="rs" if links else "ls")
    im = im.resize((N, N), Image.LANCZOS)
    import io
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
