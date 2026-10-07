"""Concurrent-alarm (stap 241, akkoord Nino 7 oktober).

WAAROM DIT BESTAND BESTAAT

Een klant betaalt elke maand. Daar heeft hij een reden voor nodig die vaker
komt dan een maandcijfer. "Er is een winkel die jou inhaalt" is zo'n reden:
dat wil je weten voordat je het aan je verkoop merkt, en het is precies wat
een eigenaar zelf niet kan zien.

Alles komt uit metingen die er al zijn, er wordt niets extra aan AI gevraagd
(geen extra kosten):
- WEKELIJKS uit de snelmeting (vijf vragen): welke winkels deze week in je
  antwoorden staan en vorige week in geen enkele, en bij welke vraag een andere
  winkel jouw plek innam (vorige week jij genoemd, nu niet, wel een ander).
- MAANDELIJKS uit de ranglijst: winkels die vorige maand onder je stonden en
  nu boven je, en nieuwe winkels in de top vijf.

Eerlijk: AI-antwoorden schommelen. Daarom tellen wij een nieuwe winkel pas als
hij vorige week nergens stond, en noemen wij hooguit drie namen.
"""
import json

MAX_NAMEN = 3


def _kaal(naam):
    """toysshop1.nl, https://www.toysshop1.nl/ en Toysshop1.nl zijn dezelfde."""
    t = (naam or "").strip().lower()
    for weg in ("https://", "http://", "www."):
        if t.startswith(weg):
            t = t[len(weg):]
    return t.rstrip("/")


def _lijst(anderen):
    if isinstance(anderen, str):
        try:
            anderen = json.loads(anderen)
        except ValueError:
            return []
    return [a for a in (anderen or []) if isinstance(a, str) and a.strip()]


def week(nu, vorige):
    """Puur rekenwerk: twee lijsten rijen uit de snelmeting (vraag, genoemd,
    anderen). Geeft {"nieuw": [...], "ingenomen": [{"vraag", "door"}]}."""
    if not nu or not vorige:
        return {"nieuw": [], "ingenomen": []}
    vorige_namen = {_kaal(a) for r in vorige for a in _lijst(r.get("anderen"))}
    nieuw, gezien = [], set()
    for r in nu:
        for a in _lijst(r.get("anderen")):
            k = _kaal(a)
            if k and k not in vorige_namen and k not in gezien:
                gezien.add(k)
                nieuw.append(a)
    was_genoemd = {}
    for r in vorige:
        was_genoemd[r["vraag"]] = was_genoemd.get(r["vraag"], False) or bool(r.get("genoemd"))
    per_vraag = {}
    for r in nu:
        v = per_vraag.setdefault(r["vraag"], {"genoemd": False, "anderen": []})
        v["genoemd"] = v["genoemd"] or bool(r.get("genoemd"))
        v["anderen"] += _lijst(r.get("anderen"))
    ingenomen = []
    for vraag, v in per_vraag.items():
        if was_genoemd.get(vraag) and not v["genoemd"] and v["anderen"]:
            ingenomen.append({"vraag": vraag, "door": list(dict.fromkeys(v["anderen"]))[:2]})
    return {"nieuw": nieuw[:MAX_NAMEN], "ingenomen": ingenomen[:MAX_NAMEN]}


def week_voor(webshop_url):
    """Het weekalarm uit de database. Nooit een fout: dan leeg."""
    try:
        import snelmeting
        snelmeting.maak_tabel()
        rondes = snelmeting._sql("""SELECT DISTINCT ronde_op FROM snelmetingen WHERE webshop_url = %s
                                    ORDER BY ronde_op DESC LIMIT 2""", (webshop_url,), alles=True) or []
        if len(rondes) < 2:
            return {"nieuw": [], "ingenomen": []}
        rijen = [snelmeting._sql("""SELECT vraag, genoemd, anderen FROM snelmetingen
                                     WHERE webshop_url = %s AND ronde_op = %s""",
                                 (webshop_url, r["ronde_op"]), alles=True) or [] for r in rondes]
        return week(rijen[0], rijen[1])
    except Exception as e:
        print(f"Weekalarm mislukt voor {webshop_url}: {e}")
        return {"nieuw": [], "ingenomen": []}


def maand(rijen, webshop_url):
    """Puur rekenwerk op een ranglijst (rijen met webshop_url, positie,
    vorige_positie). Geeft {"ingehaald": [...], "nieuw_top5": [...]}, elk met
    naam, nu en was."""
    leeg = {"ingehaald": [], "nieuw_top5": []}
    eigen = next((r for r in rijen or [] if r.get("webshop_url") == webshop_url), None)
    if not eigen or not eigen.get("positie"):
        return leeg
    ik_nu, ik_was = eigen["positie"], eigen.get("vorige_positie")
    ingehaald, nieuw = [], []
    for r in rijen:
        if r is eigen or not r.get("positie"):
            continue
        naam = r.get("naam") or _kaal(r.get("webshop_url"))
        if ik_was and r.get("vorige_positie") and r["vorige_positie"] > ik_was and r["positie"] < ik_nu:
            ingehaald.append({"naam": naam, "nu": r["positie"], "was": r["vorige_positie"]})
        elif ik_was and not r.get("vorige_positie") and r["positie"] <= 5:
            nieuw.append({"naam": naam, "nu": r["positie"], "was": None})
    ingehaald.sort(key=lambda x: x["nu"])
    nieuw.sort(key=lambda x: x["nu"])
    return {"ingehaald": ingehaald[:MAX_NAMEN], "nieuw_top5": nieuw[:MAX_NAMEN]}


def zinnen_week(alarm, taal="en"):
    """De regels voor de weekmail en het dashboard."""
    uit = []
    if alarm.get("ingenomen"):
        for i in alarm["ingenomen"]:
            door = ", ".join(i["door"])
            uit.append(f"{door} took your place in “{i['vraag']}”." if taal != "nl"
                       else f"{door} nam je plek in bij “{i['vraag']}”.")
    if alarm.get("nieuw"):
        namen = ", ".join(alarm["nieuw"])
        uit.append(f"New in your answers this week: {namen}." if taal != "nl"
                   else f"Nieuw in je antwoorden deze week: {namen}.")
    return uit


def zinnen_maand(alarm, taal="en"):
    uit = []
    for r in alarm.get("ingehaald") or []:
        uit.append(f"{r['naam']} passed you: now #{r['nu']}, was #{r['was']}." if taal != "nl"
                   else f"{r['naam']} haalde je in: nu #{r['nu']}, was #{r['was']}.")
    for r in alarm.get("nieuw_top5") or []:
        uit.append(f"New in the top 5: {r['naam']} (#{r['nu']})." if taal != "nl"
                   else f"Nieuw in de top 5: {r['naam']} (#{r['nu']}).")
    return uit
