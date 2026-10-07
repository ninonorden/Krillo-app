"""De wekelijkse digest voor betalende winkels (2 oktober 2026, goedgekeurd door Nino als test).

WAAROM. De maandmeting en het maandrapport zijn het grote beeld. Een winkel die
iets verbeterd heeft, wil binnen een week zien of het werkt. De wekelijkse
snelmeting (snelmeting.py) meet dat al; deze mail brengt het naar de inbox.

REGELS
- Alleen na een snelmeting met iets te zeggen, en alleen naar een betalende,
  niet opgezegde, niet-test klant die de mail niet uitzette.
- Kort: een regel met het getal (en vorige week), wat er veranderde per vraag,
  welke producten AI noemde (productkaart.py), en een knop naar het dashboard.
- Geen nieuwe plek: die komt uit de maandmeting, en dat staat erbij.
- Uitzetten met een klik (/mijn/<token>/weekmail/uit). Langs de controleagent
  zoals elke klantmail (emailing.send_klantbericht).
- Hoogstens een keer per zes dagen per winkel.
"""
import db

UIT_SLEUTEL = "weekmail_uit:{}"


def staat_uit(webshop_url):
    return (db.get_instelling(UIT_SLEUTEL.format(webshop_url)) or "") == "ja"


def zet_uit(webshop_url, uit=True):
    db.zet_instelling(UIT_SLEUTEL.format(webshop_url), "ja" if uit else "")


def acties_voor(webshop_url, maximaal=3):
    """Stap 291 (7 oktober): de drie dingen die deze week het meest opleveren.

    Dezelfde aanpak als op de pagina Fixes (vraagaanpak.py), de verloren vragen
    met de gekozen vragen eerst. Per vraag de eerste concrete stap. Nooit een
    fout: lukt het niet, dan staat er gewoon geen actieblok in de mail."""
    try:
        import klantbeeld
        import dashboardpaginas as dp
        import vraagaanpak
        beeld = klantbeeld.bouw(webshop_url)
        if not beeld or not beeld.get("ronde"):
            return []
        naam = beeld.get("naam") or webshop_url
        vo = dp.vragen_overzicht(beeld["ronde"], webshop_url, naam)
        lijst = vraagaanpak.voor_dashboard(vo, db.gekozen_vragen(webshop_url), None, en=True,
                                           maximaal=maximaal)
        return [{"vraag": a["vraag"], "stap": (a.get("stappen") or [""])[0]} for a in lijst if a.get("stappen")]
    except Exception as e:
        print(f"Acties voor de weekmail mislukt voor {webshop_url}: {e}")
        return []


def alineas(snel, kaart=None, alarm=None, acties=None):
    """De alinea's van de mail, of None als er niets te melden is.

    acties: de drie acties van deze week (stap 291, acties_voor).

    alarm: het concurrent-alarm van deze week (stap 241, concurrentalarm.py)."""
    if not snel or not snel.get("van"):
        return None
    regel = f"This week AI named your store in <strong>{snel['genoemd']} of {snel['van']}</strong> answers"
    if snel.get("vorige_van"):
        verschil = snel["genoemd"] - (snel.get("vorige_genoemd") or 0)
        regel += (f", up from {snel['vorige_genoemd']} last week" if verschil > 0 else
                  f", down from {snel['vorige_genoemd']} last week" if verschil < 0 else ", the same as last week")
    uit = ["Hi,", regel + ". We asked ChatGPT and Gemini your five most important buying questions again."]
    nu = [v for v in snel.get("vragen") or [] if v.get("was") is not None and v["was"] != v["nu"]]
    for v in nu[:3]:
        uit.append(("Now named: " if v["nu"] else "No longer named: ") + f"“{v['vraag']}”.")
    # Stap 241: wie er deze week bij kwam, en wie jouw plek innam.
    if alarm:
        import concurrentalarm
        uit += concurrentalarm.zinnen_week(alarm)
    # Stap 291: niet alleen cijfers, ook wat je deze week doet.
    for i, a in enumerate((acties or [])[:3], start=1):
        uit.append((f"This week, do this. " if i == 1 else "") + f"{i}. For “{a['vraag']}”: {a['stap']}")
    if kaart and kaart.get("genoemd"):
        namen = ", ".join(p["naam"] for p in kaart["genoemd"][:3])
        uit.append(f"Products AI named by name: {namen}.")
    uit.append("Your rank in the index comes from the monthly measurement, so it does not change with this.")
    return uit


def stuur_voor(webshop_url, email, klant_token, basis_url="https://krilloai.com", stuur=None):
    """Na de snelmeting van een winkel. Geeft True als er een mail uitging."""
    import emailing
    import snelmeting
    if not email or staat_uit(webshop_url):
        return False
    if not db.claim_moment(f"weekmail:{webshop_url}", 6 * 24 * 3600):
        return False
    try:
        import productkaart
        kaart = productkaart.kaart(webshop_url)
    except Exception:
        kaart = None
    try:
        import concurrentalarm
        alarm = concurrentalarm.week_voor(webshop_url)
    except Exception:
        alarm = None
    tekst = alineas(snelmeting.overzicht(webshop_url), kaart, alarm, acties_voor(webshop_url))
    if not tekst:
        return False
    basis = basis_url.rstrip("/")
    # Een link in de tekst wordt door de mail ge-escaped (alleen <strong> mag),
    # dus het adres als gewone tekst; mailprogramma's maken er zelf een link van.
    tekst.append(f"Rather not get this every week? Turn it off here: {basis}/mijn/{klant_token}/weekmail/uit")
    stuur = stuur or emailing.send_klantbericht
    return bool(stuur(email, "Your week in AI answers", tekst, f"{basis}/mijn/{klant_token}",
                      knop="Open my dashboard"))
