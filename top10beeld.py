"""Stap 382: het Top 10-plaatje van een ranglijst (15 oktober 2026).

WAAROM. Krillo heeft bijna geen bezoek. Een winkel in de top 10 van zijn
categorie is trots op die plek en deelt hem graag, en elke deling stuurt
mensen naar de ranglijst. Daarnaast is dit het voorbeeldplaatje (og:image) van
de ranglijstpagina: wie de link deelt op LinkedIn, WhatsApp of Slack ziet de
top 10 in plaats van een kale link. Dat haalt meer kliks uit dezelfde deling.

1200 x 630, het formaat dat LinkedIn, Facebook, X en WhatsApp verwachten.
Alleen winkels die echt genoemd zijn, uit dezelfde meting als de pagina.
"""
import io

MAX = 10


def regels(rijen):
    """[(positie, naam)] van de genoemde winkels, hoogstens tien."""
    uit = []
    for r in rijen or []:
        if (r.get("genoemd") or 0) <= 0:
            continue
        naam = r.get("naam")
        if not naam or str(naam).startswith("http"):
            naam = (r.get("webshop_url") or "").replace("https://", "").replace("http://", "") \
                .replace("www.", "").rstrip("/")
        uit.append((r.get("positie"), str(naam)))
        if len(uit) >= MAX:
            break
    return uit


def titel(naam_en, naam_lokaal=None):
    """15 oktober (Nino: "alles Engels, maar voor de markten"). De kop is Engels,
    net als de hele site; de naam van de categorie in de taal van het land staat
    erachter, want dat is het woord waarop een koper daar zoekt. Zo werkt
    hetzelfde plaatje straks ook in Duitsland of Frankrijk zonder ombouwen."""
    kop = f"Top 10 {naam_en.lower()} stores according to ChatGPT and Gemini"
    if naam_lokaal and naam_lokaal.strip().lower() != naam_en.strip().lower():
        kop += f" ({naam_lokaal.lower()})"
    return kop


def png(rijen, naam_en, naam_lokaal, landnaam, maand=""):
    from PIL import Image, ImageDraw
    import linkedinagent as la
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), la.WIT)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 10), fill=la.BLAUW)
    merk = la._font("SpaceGrotesk-Bold.ttf", 30)
    d.text((60, 70), "KRILLO", font=merk, fill=la.INKT, anchor="ls")
    d.text((60 + d.textlength("KRILLO", font=merk) + 10, 70), "INDEX",
           font=la._font("IBMPlexMono-Medium.ttf", 17), fill=la.GRIJS, anchor="ls")
    tf = la._font("SpaceGrotesk-Bold.ttf", 40)
    y = 132
    for regel in la._regels_passend(d, titel(naam_en, naam_lokaal), tf, W - 120)[:2]:
        d.text((60, y), regel, font=tf, fill=la.INKT, anchor="ls")
        y += 48
    klein = la._font("IBMPlexMono-Medium.ttf", 18)
    d.text((60, y), f"{landnaam}{(' · ' + maand) if maand else ''} · krilloai.com/index", font=klein,
           fill=la.GRIJS, anchor="ls")
    lijst = regels(rijen)
    naamf = la._font("SpaceGrotesk-Medium.ttf", 26)
    plekf = la._font("SpaceGrotesk-Bold.ttf", 26)
    top = y + 64
    kolom = 2 if len(lijst) > 5 else 1
    per_kolom = 5
    breedte = (W - 120) // kolom
    for i, (positie, n) in enumerate(lijst):
        k, rij = divmod(i, per_kolom)
        x0, y0 = 60 + k * breedte, top + rij * 72
        d.rounded_rectangle((x0, y0 - 42, x0 + breedte - 24, y0 + 18), radius=10,
                            fill=(247, 247, 249) if i else (236, 240, 253))
        d.text((x0 + 16, y0), f"{positie}", font=plekf, fill=la.BLAUW if i == 0 else la.INKT, anchor="ls")
        tekst = n
        while d.textlength(tekst, font=naamf) > breedte - 110 and len(tekst) > 4:
            tekst = tekst[:-2]
        if tekst != n:
            tekst = tekst.rstrip() + "…"
        d.text((x0 + 70, y0), tekst, font=naamf, fill=la.INKT, anchor="ls")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
