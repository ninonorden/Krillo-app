"""De SEO-agent: leest Search Console, test betere titels en leert wat werkt (15 oktober 2026).

WAAROM. Nino: "een SEO-agent die automatisch leert wat werkt en het toepast,
zodat het verkeer elke dag groeit." Search Console liet duizenden vertoningen
zien met bijna geen klikken: Google laat onze ranglijsten wel zien, maar mensen
klikken er niet op. De titel is wat ze zien. Dit is het deel van SEO dat veilig
helemaal vanzelf kan, op onze eigen pagina's:

1. Elke dag de cijfers per pagina en per zoekvraag uit Search Console.
2. Een pagina met veel vertoningen maar een lage klikratio voor haar plek krijgt
   een nieuwe titel, geschreven op de zoekvragen waarop hij echt verschijnt.
   Hoogstens MAX_PROEVEN tegelijk.
3. Na PROEF_DAGEN wordt gemeten: meer klikken per vertoning dan ervoor, dan
   blijft de nieuwe titel; anders gaat de oude terug.
4. Elke uitkomst wordt bewaard en gaat mee in de opdracht voor de volgende
   titel ("dit werkte, dit niet"). Zo wordt hij met elke proef beter.
5. Zoekvragen waarop we verschijnen maar ver weg staan (plek 15 of lager)
   komen als onderwerp voor een nieuwe gids in het ochtendbericht.

Wat hij bewust NIET doet: zelf honderden pagina's schrijven (Google straft dat
als massacontent) of iets buiten onze site plaatsen. Alleen titels van onze
eigen ranglijsten en gidsen, met een weg terug.
"""
import json
import os
import re
from datetime import date, timedelta

import db

PROEF_DAGEN = int(os.environ.get("SEO_PROEF_DAGEN", "14"))
MAX_PROEVEN = int(os.environ.get("SEO_MAX_PROEVEN", "3"))
MIN_VERTONINGEN = int(os.environ.get("SEO_MIN_VERTONINGEN", "50"))
MODEL = os.environ.get("SEO_MODEL", "claude-sonnet-4-6")
SLEUTEL_TITEL = "seo_titel:"
SLEUTEL_PROEVEN = "seo_proeven"
SLEUTEL_GELEERD = "seo_geleerd"
SLEUTEL_ONDERWERPEN = "seo_onderwerpen"

# Wat een pagina op een plek ongeveer aan klikken per vertoning haalt.
VERWACHT = [(1, .28), (2, .15), (3, .10), (4, .07), (5, .05), (10, .03), (20, .012)]
_EIGEN = re.compile(r"^/(index/[a-z]{2}/[a-z0-9-]+|guides/[a-z0-9-]+)$")


def verwachte_ctr(plek):
    for grens, ctr in VERWACHT:
        if plek <= grens:
            return ctr
    return .005


def pad_van(url):
    pad = re.sub(r"^https?://[^/]+", "", url or "").split("?")[0].split("#")[0].rstrip("/")
    return pad if _EIGEN.match(pad or "") else None


def _json(sleutel, standaard):
    try:
        return json.loads(db.get_instelling(sleutel) or "null") or standaard
    except (TypeError, ValueError):
        return standaard


def titel_voor(pad):
    """De titel van een lopende of gewonnen proef voor deze pagina, of None."""
    if not pad:
        return None
    return db.get_instelling(SLEUTEL_TITEL + pad) or None


def proeven():
    return _json(SLEUTEL_PROEVEN, [])


def geleerd():
    return _json(SLEUTEL_GELEERD, [])


def onderwerpen():
    return _json(SLEUTEL_ONDERWERPEN, [])


def geldige_titel(titel, zoekvragen):
    """Kort genoeg voor Google, geen lange streepjes, en hij noemt de zoekvraag."""
    t = (titel or "").strip().strip('"')
    if not 25 <= len(t) <= 65 or "—" in t or "–" in t:
        return None
    woorden = {w for v in zoekvragen[:3] for w in re.findall(r"[a-zà-ÿ]{4,}", v.lower())}
    if woorden and not any(w in t.lower() for w in woorden):
        return None
    return t


def prompt(pad, zoekvragen, lessen):
    les = "\n".join(f"- {'WORKED' if l['gehouden'] else 'DID NOT WORK'}: \"{l['nieuw']}\" "
                    f"(click rate {l['ctr_voor']:.1%} -> {l['ctr_na']:.1%})" for l in lessen[-10:]) or "- none yet"
    return ("Write one page title for Google search results.\n"
            f"Page: {pad} (a monthly ranking of which online stores ChatGPT and Gemini recommend, "
            "or a guide for store owners).\n"
            "The searches it appears for most: " + "; ".join(zoekvragen[:5]) + "\n"
            "Earlier title tests on this site:\n" + les + "\n"
            "Rules: English, but keep the shopper's own words from the searches (also when Dutch); "
            "25 to 60 characters; end with \" | Krillo\" only if it fits; no long dashes; no clickbait, "
            "no promises, nothing that is not on the page. Return only the title.")


def _vraag_model(tekst):
    import time
    import kosten
    from lui_anthropic import anthropic
    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        raise RuntimeError(rem["reden"])
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    gestart = time.monotonic()
    antwoord = client.messages.create(model=MODEL, max_tokens=100,
                                      messages=[{"role": "user", "content": tekst}])
    try:
        kosten.registreer_aanroep("anthropic", MODEL, antwoord.usage.input_tokens,
                                  antwoord.usage.output_tokens, soort="seoagent",
                                  duur_ms=int((time.monotonic() - gestart) * 1000))
    except Exception:
        pass
    return antwoord.content[0].text


def ronde(per_pagina, per_vraag, vandaag=None, vraag_model=None):
    """per_pagina: [{page, clicks, impressions, ctr, position}] (laatste 14 dagen).
    per_vraag: [{page, query, clicks, impressions, position}]. Geeft een verslag."""
    vandaag = vandaag or date.today()
    vraag_model = vraag_model or _vraag_model
    cijfers = {}
    for r in per_pagina or []:
        pad = pad_van(r.get("page"))
        if pad:
            cijfers[pad] = r
    vragen_van = {}
    for r in sorted(per_vraag or [], key=lambda r: -(r.get("impressions") or 0)):
        pad = pad_van(r.get("page"))
        if pad and r.get("query"):
            vragen_van.setdefault(pad, []).append(r["query"])
    verslag = {"gehouden": [], "teruggezet": [], "gestart": [], "onderwerpen": 0,
               "paginas": len(cijfers),
               "genoeg_vertoningen": sum(1 for r in cijfers.values() if (r.get("impressions") or 0) >= MIN_VERTONINGEN)}
    lijst, lessen = proeven(), geleerd()

    # 1. Lopende proeven afronden.
    for p in [p for p in lijst if p.get("stand") == "loopt"]:
        if (vandaag - date.fromisoformat(p["start"])).days < PROEF_DAGEN:
            continue
        nu = cijfers.get(p["pad"])
        if not nu or (nu.get("impressions") or 0) < MIN_VERTONINGEN:
            continue   # nog te weinig vertoningen om iets te zeggen; langer laten lopen
        ctr_na = float(nu.get("ctr") or 0)
        gewonnen = ctr_na > p["ctr_voor"]
        p.update(stand="gehouden" if gewonnen else "teruggezet", ctr_na=ctr_na, eind=vandaag.isoformat())
        if not gewonnen:
            db.zet_instelling(SLEUTEL_TITEL + p["pad"], "")
        (verslag["gehouden"] if gewonnen else verslag["teruggezet"]).append(p["pad"])
        lessen.append({"nieuw": p["titel"], "ctr_voor": p["ctr_voor"], "ctr_na": ctr_na, "gehouden": gewonnen})

    # 2. Nieuwe proeven op pagina's die te weinig klikken voor hun plek.
    bezig = {p["pad"] for p in lijst if p.get("stand") == "loopt"}
    getest = {p["pad"] for p in lijst}
    kandidaten = sorted(
        [(pad, r) for pad, r in cijfers.items()
         if pad not in getest and (r.get("impressions") or 0) >= MIN_VERTONINGEN
         and (r.get("position") or 99) <= 20
         and float(r.get("ctr") or 0) < 0.8 * verwachte_ctr(r.get("position") or 99)],
        key=lambda kv: -(kv[1].get("impressions") or 0))
    for pad, r in kandidaten:
        if len(bezig) >= MAX_PROEVEN:
            break
        zoekvragen = vragen_van.get(pad) or []
        if not zoekvragen:
            continue
        try:
            titel = geldige_titel(vraag_model(prompt(pad, zoekvragen, lessen)), zoekvragen)
        except Exception as e:
            print(f"SEO-agent, titel schrijven mislukt: {e}")
            break
        if not titel:
            continue
        db.zet_instelling(SLEUTEL_TITEL + pad, titel)
        lijst.append({"pad": pad, "titel": titel, "start": vandaag.isoformat(), "stand": "loopt",
                      "ctr_voor": float(r.get("ctr") or 0), "plek_voor": float(r.get("position") or 0),
                      "vragen": zoekvragen[:5]})
        bezig.add(pad)
        verslag["gestart"].append(pad)

    # 3. Zoekvragen waar we ver weg staan: onderwerpen voor een nieuwe gids.
    nieuw = {}
    for r in per_vraag or []:
        q = (r.get("query") or "").lower()
        if (r.get("impressions") or 0) >= 20 and (r.get("position") or 0) > 15 and "krillo" not in q:
            nieuw[q] = max(nieuw.get(q, 0), int(r.get("impressions") or 0))
    top = sorted(nieuw.items(), key=lambda kv: -kv[1])[:10]
    db.zet_instelling(SLEUTEL_ONDERWERPEN, json.dumps([{"vraag": q, "vertoningen": n} for q, n in top]))
    verslag["onderwerpen"] = len(top)

    verslag["kandidaten"] = len(kandidaten)
    db.zet_instelling(SLEUTEL_PROEVEN, json.dumps(lijst[-100:]))
    db.zet_instelling(SLEUTEL_GELEERD, json.dumps(lessen[-100:]))
    noteer_laatste({"op": vandaag.isoformat(), "paginas": verslag["paginas"],
                    "genoeg_vertoningen": verslag["genoeg_vertoningen"], "kandidaten": len(kandidaten)})
    return verslag


# 16 oktober (Nino: "0 proeven, klopt dit na een dag?"): de regel zei niet of
# de agent wel gedraaid had. Nu staat erbij wanneer hij Search Console las,
# hoeveel van onze pagina's hij zag en waarom er geen proef startte, of de fout.
SLEUTEL_LAATSTE = "seo_laatste"


def noteer_laatste(stand):
    try:
        db.zet_instelling(SLEUTEL_LAATSTE, json.dumps(stand))
    except Exception:
        pass


def laatste():
    return _json(SLEUTEL_LAATSTE, None)


def ochtendregel():
    lijst, lessen, ond = proeven(), geleerd(), onderwerpen()
    lopend = sum(1 for p in lijst if p.get("stand") == "loopt")
    gewonnen = sum(1 for l in lessen if l["gehouden"])
    regel = (f"SEO-agent: {lopend} titelproef/proeven lopen, {gewonnen} van {len(lessen)} afgeronde proeven "
             f"gaven meer klikken (een proef duurt {PROEF_DAGEN} dagen).")
    st = laatste()
    if not st:
        regel += " Search Console is nog niet gelezen (dat gebeurt elke ochtend tussen 7 en 10 uur)."
    elif st.get("fout"):
        regel += f" Search Console lezen mislukte op {st.get('op')}: {st['fout']}."
    else:
        regel += (f" Gelezen op {st.get('op')}: {st.get('paginas', 0)} eigen pagina's in Google, "
                  f"{st.get('genoeg_vertoningen', 0)} met minstens {MIN_VERTONINGEN} vertoningen in 14 dagen, "
                  f"{st.get('kandidaten', 0)} die te weinig klikken voor hun plek.")
        if not st.get("kandidaten") and not lopend:
            regel += " Nog geen proef: er is (nog) geen pagina met genoeg vertoningen en te weinig klikken."
    if ond:
        regel += " Zoekvragen zonder goede pagina: " + ", ".join(f"\"{o['vraag']}\"" for o in ond[:3]) + "."
    return regel


def haal_op(dagen=14, eind=None):
    """De cijfers uit Search Console, of (None, None) als er geen toegang is.
    Nodig in Render: GSC_SERVICE_ACCOUNT_JSON (de sleutel van een serviceaccount
    met leesrecht op de property) en GSC_SITE (standaard sc-domain:krilloai.com)."""
    info = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not info:
        return None, None
    import requests
    from urllib.parse import quote
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    cred = service_account.Credentials.from_service_account_info(
        json.loads(info), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    cred.refresh(Request())
    site = os.environ.get("GSC_SITE", "sc-domain:krilloai.com")
    eind = eind or (date.today() - timedelta(days=2))   # Search Console loopt twee dagen achter
    basis = {"startDate": (eind - timedelta(days=dagen - 1)).isoformat(), "endDate": eind.isoformat(),
             "rowLimit": 5000}

    def vraag(dimensies):
        r = requests.post(f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query",
                          headers={"Authorization": f"Bearer {cred.token}"},
                          json=dict(basis, dimensions=dimensies), timeout=60)
        r.raise_for_status()
        return [dict(zip(dimensies, rij.get("keys") or []), clicks=rij.get("clicks"), impressions=rij.get("impressions"),
                     ctr=rij.get("ctr"), position=rij.get("position")) for rij in r.json().get("rows") or []]
    return vraag(["page"]), vraag(["page", "query"])
