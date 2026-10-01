"""Stap 184: het maandrapport als PDF van een pagina (1 oktober 2026).

WAAROM. Een eigenaar wil zijn plek kunnen doorsturen: naar een compagnon, zijn
bureau, of zichzelf over een maand. Een dashboard met een geheime link deel je
niet graag. Een PDF van een pagina wel: plek, verschuiving, genoemd en
aangeraden, de drie koopvragen die hij het meest verliest met wie er wel
genoemd werd, en wat AI over hem zegt. Alles uit dezelfde maandmeting als het
dashboard en de openbare ranglijst: nooit een tweede cijfer.

Getekend met PIL (zelfde letters als de deelbeelden), geen extra pakket nodig.
A4 staand, 1240 x 1754 pixels (150 dpi).
"""
import io

W, H = 1240, 1754


def _winkel(url):
    return (url or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def pdf(beeld, categorienaam, landnaam, imago=None, maand=""):
    """Geeft de PDF als bytes. beeld: klantbeeld.bouw()."""
    from PIL import Image, ImageDraw
    import linkedinagent as la
    im = Image.new("RGB", (W, H), la.WIT)
    d = ImageDraw.Draw(im)
    f = la._font
    mono = lambda n: f("IBMPlexMono-Medium.ttf", n)  # noqa: E731
    bold = lambda n: f("SpaceGrotesk-Bold.ttf", n)  # noqa: E731
    med = lambda n: f("SpaceGrotesk-Medium.ttf", n)  # noqa: E731
    L, R = 90, W - 90

    d.rectangle((0, 0, W, 10), fill=la.BLAUW)
    d.text((L, 90), "KRILLO", font=bold(34), fill=la.INKT, anchor="ls")
    d.text((L + d.textlength("KRILLO", font=bold(34)) + 12, 90), "INDEX", font=mono(18), fill=la.GRIJS, anchor="ls")
    d.text((R, 90), f"MONTHLY REPORT{(' · ' + maand.upper()) if maand else ''}", font=mono(18), fill=la.GRIJS,
           anchor="rs")

    y = 190
    for regel in la._regels_passend(d, _winkel(beeld["webshop_url"]), bold(60), R - L)[:2]:
        d.text((L, y), regel, font=bold(60), fill=la.INKT, anchor="ls")
        y += 66
    d.text((L, y), f"{categorienaam} · {landnaam} · ChatGPT and Gemini", font=mono(20), fill=la.GRIJS, anchor="ls")

    # De vier cijfers.
    y += 70
    vak = (R - L) // 4
    telbaar = beeld.get("telbaar") or 0
    cijfers = [(f"#{beeld['positie']}", f"of {beeld.get('van')} stores"),
               (f"{beeld.get('genoemd') or 0}/{telbaar}", "questions where AI names you"),
               (str(beeld.get("aanbevolen") or 0), "where AI recommends you"),
               ((f"{'+' if beeld['verschil'] > 0 else ''}{beeld['verschil']}" if beeld.get("verschil") else "="),
                f"places since last month" if beeld.get("vorige_positie") else "first measurement")]
    for i, (groot, klein) in enumerate(cijfers):
        x = L + i * vak
        d.text((x, y + 60), groot, font=bold(58), fill=la.INKT, anchor="ls")
        for j, regel in enumerate(la._regels_passend(d, klein, med(20), vak - 20)[:2]):
            d.text((x, y + 96 + j * 26), regel, font=med(20), fill=la.GRIJS, anchor="ls")
    y += 190
    d.line((L, y, R, y), fill=la.LIJN, width=2)

    # De verloren vragen.
    y += 60
    d.text((L, y), "Questions you lose, and who AI named instead", font=bold(30), fill=la.INKT, anchor="ls")
    y += 20
    vragen = [v for v in beeld.get("gemiste_vragen") or [] if v.get("vraag")][:3]
    if not vragen:
        y += 40
        d.text((L, y), "None this month: AI named you in every question.", font=med(24), fill=la.INKT, anchor="ls")
    for v in vragen:
        y += 50
        vraag = v["vraag"][:1].upper() + v["vraag"][1:]
        for regel in la._regels_passend(d, f"“{vraag}”", med(24), R - L)[:2]:
            d.text((L, y), regel, font=med(24), fill=la.INKT, anchor="ls")
            y += 32
        wie = ", ".join(n for n in (v.get("concurrenten") or [])[:3] if n) or "no store"
        d.text((L, y), f"Named instead: {wie}"[:90], font=mono(18), fill=la.GRIJS, anchor="ls")
        y += 10

    # Wat AI zegt.
    if imago and (imago.get("kenmerken") or imago.get("citaten")):
        y += 70
        d.line((L, y - 40, R, y - 40), fill=la.LIJN, width=2)
        d.text((L, y), "What AI says about you", font=bold(30), fill=la.INKT, anchor="ls")
        if imago.get("kenmerken"):
            y += 44
            tekst = "Mentions: " + ", ".join(f"{label.lower()} ({n}x)" for label, n in imago["kenmerken"][:5])
            for regel in la._regels_passend(d, tekst, med(22), R - L)[:2]:
                d.text((L, y), regel, font=med(22), fill=la.INKT, anchor="ls")
                y += 30
        for c in (imago.get("citaten") or [])[:2]:
            y += 30
            d.rectangle((L, y - 22, L + 5, y + 40), fill=la.BLAUW)
            zin = ("…" if c["zin"][:1].islower() else "") + c["zin"]
            for regel in la._regels_passend(d, f"“{zin}”", med(21), R - L - 24)[:3]:
                d.text((L + 22, y), regel, font=med(21), fill=la.INKT, anchor="ls")
                y += 28
            d.text((L + 22, y), c.get("assistent") or "", font=mono(16), fill=la.GRIJS, anchor="ls")
            y += 8

    # Onderaan: hoe er gemeten is, en waar de rest staat.
    d.line((L, H - 150, R, H - 150), fill=la.LIJN, width=2)
    uitleg = (f"Measured by asking ChatGPT and Gemini {telbaar} buying questions shoppers in {landnaam} ask, the same "
              f"for every store in this category. The full ranking and every question: krilloai.com/index.")
    yy = H - 110
    for regel in la._regels_passend(d, uitleg, med(19), R - L)[:3]:
        d.text((L, yy), regel, font=med(19), fill=la.GRIJS, anchor="ls")
        yy += 26

    uit = io.BytesIO()
    im.save(uit, "PDF", resolution=150)
    return uit.getvalue()
