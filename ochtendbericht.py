"""Het ochtendbericht: een mail per ochtend met wat de agents deden en wat jij moet doen.

WAAROM DIT BESTAAT (stap 132, 28 september). Er draaien nu zes agents: de
koude mail, de adresvinder, de verkoopagent, de antwoordagent, de opvolging
van de gratis check en de nachtcontrole. Elk heeft een eigen beheerpagina. Om
te weten of alles liep moest Nino zes pagina's openen, en wat hij zelf moest
doen (een antwoord goedkeuren, een concept versturen) stond verspreid. Nu komt
het elke ochtend in een mail, in deze volgorde:

1. WAT JIJ MOET DOEN, bovenaan, met een link per ding. Is er niets, dan staat
   er "niets", en dat is ook nieuws.
2. WAT DE AGENTS GISTEREN DEDEN: echte tellingen uit de database, de laatste
   24 uur. Een agent die nul doet, staat er ook in (dat is precies wat je moet
   zien).
3. De diagnose van de benadering, zoals het oude dagbericht die al gaf.

Elke telling apart: een telling die faalt, wordt "onbekend" en neemt de rest
niet mee. Dit bericht mag nooit de ronde laten omvallen.
"""
import json

import db


def _tel(sql, waarden=None):
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, waarden)
                rij = cur.fetchone()
                return int(rij[0] or 0) if rij else 0
    except Exception as e:
        print(f"Ochtendbericht, telling mislukt: {e}")
        return None
    finally:
        conn.close()


# (wat, sql). Alles over de laatste 24 uur.
GISTEREN = [
    ("Koude mails verstuurd",
     "SELECT count(*) FROM benadering WHERE gemaild_op > now() - interval '24 hours'"),
    ("Hun Krillo-pagina geopend (ook door mailbeveiliging)",
     "SELECT count(*) FROM benadering WHERE bekeken_op > now() - interval '24 hours'"),
    # 29 september: waarvan echt een mens (scrolde, tikte of bewoog de muis).
    ("Waarvan echt een mens",
     "SELECT count(*) FROM benadering WHERE mens_op > now() - interval '24 hours'"),
    ("Doorgeklikt naar de prijzen",
     "SELECT count(*) FROM benadering WHERE doorgeklikt_op > now() - interval '24 hours'"),
    ("Persoonlijke opvolgingen verstuurd (verkoopagent)",
     "SELECT count(*) FROM benadering WHERE opvolg_stand = 'verstuurd' "
     "AND opvolg_op > now() - interval '24 hours'"),
    ("Antwoorden van winkels binnen",
     "SELECT count(*) FROM antwoorden WHERE soort NOT IN ('test', 'automatisch') "
     "AND ontvangen_op > now() - interval '24 hours'"),
    ("Waarvan afgemeld",
     "SELECT count(*) FROM antwoorden WHERE soort = 'afmelden' "
     "AND ontvangen_op > now() - interval '24 hours'"),
    ("Bewegingsmails verstuurd (plek veranderd)",
     "SELECT count(*) FROM benadering WHERE beweging_op > now() - interval '24 hours'"),
    ("Felicitaties met badge verstuurd",
     "SELECT count(*) FROM benadering WHERE badge_op > now() - interval '24 hours'"),
    ("Badges bekeken op de site van een winkel",
     "SELECT count(*) FROM benadering WHERE badge_gezien_op > now() - interval '24 hours'"),
    ("Gratis tools gebruikt (bereik zonder mail)",
     "SELECT count(*) FROM tool_gebruik WHERE op > now() - interval '24 hours'"),
    ("Gratis checks gedaan",
     "SELECT count(*) FROM zichtbaarheidstests WHERE email <> 'voorproef@krilloai.com' "
     "AND aangevraagd_op > now() - interval '24 hours'"),
    ("Opvolgingen na de gratis check",
     "SELECT count(*) FROM zichtbaarheidstests WHERE opgevolgd_op > now() - interval '24 hours' "
     "OR maandbericht_op > now() - interval '24 hours'"),
    ("Categorieen gemeten",
     "SELECT count(*) FROM categorie_rondes WHERE afgerond_op > now() - interval '24 hours'"),
    ("Klantagenten: behoud, overstap en terugwin verstuurd",
     "SELECT count(*) FROM klanten WHERE behoud_op > now() - interval '24 hours' "
     "OR overstap_op > now() - interval '24 hours' OR terugwin_op > now() - interval '24 hours'"),
    ("Nieuw op de wachtlijst per land",
     "SELECT count(*) FROM wachtlijst_land WHERE op > now() - interval '24 hours'"),
    ("Winkels bekeken op een bureau onderaan",
     "SELECT count(*) FROM bureau_winkels WHERE gekeken_op > now() - interval '24 hours'"),
    ("Plek geclaimd op een winkelpagina (bevestigd, warme lead)",
     "SELECT count(*) FROM plekmeldingen WHERE bevestigd_op > now() - interval '24 hours'"),
    ("Nieuwe echte klanten",
     "SELECT count(*) FROM klanten WHERE NOT is_test AND aangemaakt_op > now() - interval '24 hours'"),
]


def te_doen(basis_url):
    """Wat Nino moet doen, met een link. Lijst van (tekst, link)."""
    uit = []
    n = _tel("SELECT count(*) FROM antwoorden WHERE stand = 'concept'")
    if n:
        uit.append((f"{n} antwoord(en) van winkels wachten op jouw goedkeuring", f"{basis_url}/admin/antwoorden"))
    n = _tel("SELECT count(*) FROM benadering WHERE opvolg_stand = 'concept'")
    if n:
        uit.append((f"{n} opvolging(en) van de verkoopagent staan klaar", f"{basis_url}/admin/verkoop"))
    n = _tel("SELECT count(*) FROM uitvoeringen WHERE stand IN ('wacht_op_toegang', 'bezig')")
    if n:
        uit.append((f"{n} Fix-opdracht(en) lopen nog", f"{basis_url}/admin/uitvoeringen"))
    n = _tel("""SELECT count(*) FROM benadering b WHERE b.formulier_url IS NOT NULL AND b.formulier_op IS NULL
                AND NOT b.afgemeld AND b.gemaild_op IS NULL AND EXISTS (
                    SELECT 1 FROM categorie_uitkomsten u JOIN categorie_rondes r ON r.id = u.ronde
                     WHERE u.webshop_url = b.webshop_url AND r.afgerond_op IS NOT NULL
                       AND coalesce(u.telbaar, 0) >= 3)""")
    if n:
        uit.append((f"{n} winkel(s) zonder info@ maar met een contactformulier: het bericht staat klaar "
                    f"(hoogstens 5 per dag)", f"{basis_url}/admin/formulieren"))
    # Stap 94 en 115: partners en bureaus. Een aanvraag wacht op jou, en een
    # bureau met een adres ook (de eerste tien mails verstuur je zelf).
    n = _tel("SELECT count(*) FROM doorverwijzers WHERE stand = 'aanvraag'")
    if n:
        uit.append((f"{n} partneraanvraag/aanvragen wachten op goedkeuring", f"{basis_url}/admin/doorverwijzen"))
    n = _tel("""SELECT count(*) FROM bureaus b WHERE b.stand = 'nieuw' AND b.email IS NOT NULL
                AND (SELECT count(*) FROM bureau_winkels w WHERE w.bureau_site = b.site) >= 3""")
    if n:
        uit.append((f"{n} bureau(s) met 3 of meer klanten in de index: open hun pagina en verstuur de mail",
                    f"{basis_url}/admin/bureaus"))
    # Stap 97 en 100: wat de nachtagenten vonden.
    try:
        na = json.loads(db.get_instelling("nachtagenten") or "{}")
    except Exception:
        na = {}
    # 1 oktober: wat de site zelf al afhandelt ("Niets voor jou te doen") hoort
    # niet bij "wat jij vandaag moet doen". Het staat wel op /admin/controle.
    # 2 oktober: verouderde bevindingen niet meer als taak. Liep de
    # indexcontrole vannacht niet, dan bleef de lijst van een eerdere nacht
    # staan (met fouten die allang opgelost waren), elke ochtend opnieuw.
    from datetime import date as _date, timedelta as _td
    if na.get("datum") and na["datum"] < (_date.today() - _td(days=1)).isoformat():
        uit.append((f"De indexcontrole liep sinds {na['datum']} niet. Geef dit aan Claude",
                    f"{basis_url}/admin/controle"))
        na = {}
    kwaliteit = [k for k in na.get("kwaliteit") or [] if "Niets voor jou te doen" not in k]
    if kwaliteit:
        uit.append((f"De kwaliteitsagent vond {len(kwaliteit)} ding(en) in de index: "
                    + "; ".join(kwaliteit[:3]), f"{basis_url}/admin/controle"))
    zeker = [c for c in na.get("concurrenten") or [] if not c.startswith("Niet zeker")]
    if zeker:
        uit.append(("De concurrentieagent: " + "; ".join(zeker[:2]), f"{basis_url}/compare"))
    # Stap 38: mails die de controleagent tegenhield (laatste 24 uur).
    try:
        from datetime import datetime as _dt
        afgekeurd = json.loads(db.get_instelling("tekstkeuring_afgekeurd") or "[]")
        vandaag = _dt.now().strftime("%d-%m")
        recent = [a for a in afgekeurd if a.get("op", "").startswith(vandaag)]
    except Exception:
        recent = []
    if recent:
        uit.append((f"De controleagent hield {len(recent)} mail(s) tegen, bijvoorbeeld '{recent[-1]['onderwerp']}': "
                    + "; ".join(recent[-1]["fouten"]), f"{basis_url}/admin/controle"))
    # Stap 96 en 153: of de leeragent mislukte. Wat hij VOORSTELT staat sinds
    # 1 oktober niet meer als losse zin hier, maar als voorstel met een
    # akkoordlink onder "Voorstellen" (voorstellen.py).
    try:
        import leeragent
        from datetime import datetime as _d, timedelta as _td, timezone as _tz
        for r in leeragent.laatste():
            if r.get("op") and r["op"] > _d.now(_tz.utc) - _td(days=1) and r.get("fout"):
                uit.append((f"Leeragent ({r['onderwerp']}) mislukte: {r['fout'][:120]}", f"{basis_url}/admin/leren"))
    except Exception:
        pass
    # 1 oktober: de klantblik (klantblik.py) liep vannacht alle pagina's na zoals
    # een klant ze ziet. Alleen echte fouten hier; twijfelgevallen op de pagina.
    try:
        kb = json.loads(db.get_instelling("klantblik") or "{}")
    except Exception:
        kb = {}
    # 1 oktober: de proefaankoop (een nepklant koopt Watch door de echte code).
    try:
        pa = json.loads(db.get_instelling("proefaankoop") or "{}")
    except Exception:
        pa = {}
    if pa.get("fout"):
        uit.append((f"De proefaankoop vond {len(pa['fout'])} fout(en) in de klantreis na betalen: "
                    + "; ".join(pa["fout"][:2]) + ". Geef het aan Claude", f"{basis_url}/admin/klantblik"))
    if kb.get("fout"):
        uit.append((f"De klantblik vond {len(kb['fout'])} fout(en) die een klant ziet, bijvoorbeeld: "
                    + "; ".join(f["tekst"] for f in kb["fout"][:2]) + ". Geef de lijst aan Claude",
                    f"{basis_url}/admin/klantblik"))
    # De LinkedIn-agent: staat er vandaag een post klaar, dan hoort Nino dat.
    n = _tel("SELECT count(*) FROM linkedin_posts WHERE dag = current_date AND stand = 'klaar'")
    if n:
        uit.append(("Vandaag staat er een LinkedIn-post klaar: kopieer, plak op de bedrijfspagina, plaatje erbij",
                    f"{basis_url}/admin/linkedin"))
    # Stap 165: de wachtlijst per land (welk land eerst).
    n = _tel("SELECT count(*) FROM wachtlijst_land WHERE gemeld_op IS NULL")
    if n:
        uit.append((f"{n} winkel(s) op de wachtlijst voor een land dat we nog niet meten", f"{basis_url}/admin/wachtlijst"))
    try:
        controle = json.loads(db.get_instelling("nachtcontrole") or "{}")
    except Exception:
        controle = {}
    if controle.get("fout"):
        uit.append((f"De nachtcontrole vond {len(controle['fout'])} probleem/problemen: "
                    + "; ".join(controle["fout"][:3]), f"{basis_url}/admin/controle"))
    return uit


def index_groei():
    """Regels over de groei van de index, voor het ochtendbericht."""
    import categorieen
    import markten
    regels = []
    ouders = {ouder for _, _, ouder in categorieen.CATEGORIEEN if ouder}
    meetbaar = [slug for slug, _, _ in categorieen.CATEGORIEEN
                if slug not in ouders and slug not in categorieen.NIET_MEETBAAR]
    for land in markten.index_landen():
        online = len(db.categorieen_per_land(land, categorieen.MINIMUM_VOOR_INDEX))
        regels.append((f"Ranglijsten openbaar in {land.upper()} (van {len(meetbaar)} categorieen)", online))
    per = db.winkels_per_categorie_in_land("nl") or {}
    gemeten = set(db.gemeten_categorieen())
    # 1 oktober: "wachten op genoeg winkels" noemde kleding-heren met 19 winkels.
    # Die wacht niet op winkels maar op de nachtmeting. Nu twee regels.
    nog_niet = sorted((per.get(s, 0), s) for s in meetbaar if s not in gemeten)
    klaar = [(n, s) for n, s in nog_niet if n >= categorieen.MINIMUM_VOOR_INDEX]
    wachten = [(n, s) for n, s in nog_niet if n < categorieen.MINIMUM_VOOR_INDEX]
    regels.append(("Klaar om te meten (10 of meer winkels, de nacht meet er een paar per keer)", len(klaar)))
    regels.append(("Categorieen die nog op genoeg winkels wachten (10 nodig)", len(wachten)))
    if wachten:
        regels.append(("Het dichtst bij (winkels nu)", ", ".join(f"{s} {n}" for n, s in wachten[::-1][:4])))
    regels.append(("Nieuwe winkels op de lijst gisteren",
                   _tel("SELECT count(*) FROM benadering WHERE toegevoegd_op > now() - interval '24 hours'")))
    return regels


def nachtregel(geheugen=None, nu=None):
    """Een zin bovenaan het ochtendbericht: liep de nacht af, hoe laat, hoe lang,
    welke stap mislukte, en wat de nacht kostte (2 oktober).

    Stond eerst onderaan, en op /admin/ochtendbericht helemaal niet. Nino vroeg
    om 10 uur: "nachtwerk staat er niet". Nu altijd als eerste regel."""
    import time
    from datetime import datetime
    try:
        gestart = float(db.get_instelling("nachtwerk_gestart") or 0)
        klaar = float(db.get_instelling("nachtwerk_klaar") or 0)
        verslag = json.loads(db.get_instelling("nachtwerk_verslag") or "{}")
    except Exception:
        gestart, klaar, verslag = 0, 0, {}
    nu = nu or time.time()

    def uur(t):
        return datetime.fromtimestamp(t).strftime("%H:%M")
    mb = f" Geheugen nu {geheugen} MB (Render herstart boven 512)." if geheugen else ""
    if not gestart or nu - gestart > 30 * 3600:
        return {"goed": False, "tekst": "LET OP: het nachtwerk is vannacht niet gestart. De site start het "
                                         "zelf tussen 2 en 5 uur; gebeurde dat niet, geef dit aan Claude." + mb}
    if klaar >= gestart:
        mislukt = [f"{k} ({v})" for k, v in verslag.items()
                   if k not in ("geheugen_na", "bezig") and isinstance(v, str) and v != "ok"]
        kosten = ""
        try:
            k = db.kosten_tussen(gestart, klaar)
            if k is not None:
                kosten = f", kostte {k:.2f} euro"
        except Exception:
            pass
        minuten = int((klaar - gestart) // 60)
        return {"goed": not mislukt,
                "tekst": (f"Nachtwerk klaar: van {uur(gestart)} tot {uur(klaar)} ({minuten} min){kosten}. "
                          + (f"Mislukt of overgeslagen: {', '.join(mislukt)}." if mislukt else "Alle stappen gelukt.")
                          + mb)}
    bezig = verslag.get("bezig")
    if bezig == "onderhoud":
        try:
            sub = db.get_instelling("onderhoud_stap")
            if sub and sub != "klaar":
                bezig = f"onderhoud ({sub})"
        except Exception:
            pass
    return {"goed": False,
            "tekst": (f"LET OP: het nachtwerk startte om {uur(gestart)} maar kwam niet af"
                      + (f", het bleef hangen bij: {bezig}" if bezig else "")
                      + ". Waarschijnlijk een herstart van Render. De site probeert het tot 7 uur opnieuw." + mb)}


def verzamel(basis_url):
    gisteren = [(wat, _tel(sql)) for wat, sql in GISTEREN]
    # Hoe de post landt (stap 117): zelfde telling als de automatische rem.
    try:
        import benadering
        g = benadering.verzendgezondheid()
        gisteren.append((f"Teruggekaatst, laatste 7 dagen (rem boven {benadering.REM_BOUNCE_PROCENT:g}%)",
                         g["bounces"]))
        gisteren.append(("Spammeldingen, laatste 7 dagen (rem bij 1)", g["klachten"]))
    except Exception:
        pass
    # Stap 143: kosten tegenover opbrengst.
    try:
        import nachtagenten
        k, o = nachtagenten.kosten_week()
        gisteren.append(("AI-kosten laatste 7 dagen (euro)", f"{k:.2f}"))
        gisteren.append(("Opbrengst per maand van betalende klanten (euro)", f"{o:.2f}"))
    except Exception:
        pass
    # 1 oktober: kleine Shopify-winkels en dropshippers (stap 156 en 217).
    gisteren.append(("Waarvan aan Shopify-winkels (7 dagen)",
                     _tel("SELECT count(*) FROM benadering WHERE gemaild_op > now() - interval '7 days' "
                          "AND mail_platform = 'shopify'")))
    gisteren.append(("Waarvan met de zin over gekopieerde leverancierstekst (7 dagen)",
                     _tel("SELECT count(*) FROM benadering WHERE gemaild_op > now() - interval '7 days' "
                          "AND coalesce(mail_leverancier, 0) > 0")))
    # 30 september (idee na de stille middag): de mails van gisteren tegenover
    # het doel. "12 van 50" zie je meteen; een los getal niet.
    try:
        import benadering
        doel = benadering.instellingen()["per_dag"]
        n = _tel("SELECT count(*) FROM benadering WHERE gemaild_op > now() - interval '24 hours'")
        gisteren.append(("Koude mails tegenover het doel", f"{n if n is not None else '?'} van {doel}"
                         + (" (te weinig: kijk op /admin/benadering bij de laatste rondes)"
                            if n is not None and doel and n < doel * 0.6 else "")))
    except Exception as e:
        print(f"Ochtendbericht, doel mislukt: {e}")
    # 30 september, Nino: "zijn nu alle categorieen gescand? hoe groeien we
    # dit?". Elke ochtend de stand van de index zelf: hoeveel ranglijsten
    # openbaar, hoeveel categorieen nog wachten op genoeg winkels, en wat er
    # gisteren bij kwam.
    try:
        gisteren += index_groei()
    except Exception as e:
        print(f"Ochtendbericht, indexgroei mislukt: {e}")
    # 30 september (idee na bel-air): de gecorrigeerd-teller. Stijgt het aantal
    # verplaatste of verwijderde winkels in een categorie, dan levert de
    # winkelvinder daar rommel aan en passen we de zoekwoorden aan.
    try:
        import categoriecheck
        import categorieen
        g = categoriecheck.gecorrigeerd()
        if g is not None:
            gisteren.append(("Categoriecheck: nagekeken / verplaatst / uit de index",
                             f"{g['bekeken']} / {g['verplaatst']} / {g['eruit']}"))
            # "overig" is de bak voor twijfelgevallen: daar uit gehaald worden is
            # juist goed (de winkel krijgt een echte categorie), dus geen fout.
            rommel = [r for r in g["rommel"] if r[0] not in categorieen.NIET_MEETBAAR]
            if rommel:
                gisteren.append(("Categorieen met veel fouten (7 dagen, fout van nagekeken)",
                                 ", ".join(f"{c} {f} van {n}" for c, f, n in rommel[:4])))
    except Exception as e:
        print(f"Ochtendbericht, gecorrigeerd mislukt: {e}")
    try:
        klaar_voor_post = len(db.te_mailen_met_positie(10000))
    except Exception:
        klaar_voor_post = None
    doen = te_doen(basis_url)
    gegevens = {"te_doen": doen, "gisteren": gisteren, "klaar_voor_post": klaar_voor_post}
    # 1 oktober: de dagtaken en de voorstellen ter akkoord (groeiagent.py,
    # voorstellen.py). Mislukt dit, dan blijft het oude bericht gewoon staan.
    try:
        import groeiagent
        import voorstellen
        gegevens["dagtaken"] = groeiagent.dagtaken(basis_url, te_doen=doen)
        gegevens["voorstellen"] = [dict(v, link=f"{basis_url}/v/{v['token']}")
                                   for v in voorstellen.open_voorstellen()]
        gegevens["bouwlijst"] = len(voorstellen.bouwlijst())
    except Exception as e:
        print(f"Ochtendbericht, dagtaken mislukt: {e}")
    try:
        gegevens["nacht"] = nachtregel()
    except Exception as e:
        print(f"Ochtendbericht, nachtregel mislukt: {e}")
    # Kosten per agent (1 oktober): de laatste 7 dagen, duurste vijf. Zo zie je
    # welke agent de dagpot opmaakt en of hij dat waard is.
    try:
        import kosten
        gegevens["kosten_agents"] = kosten.per_agent(7)[:5]
        gegevens["dagpot"] = kosten.GRENS_TOTAAL_DAG_EURO
    except Exception as e:
        print(f"Ochtendbericht, kosten per agent mislukt: {e}")
    # De vrijdagscore (1 oktober): op vrijdag wat elke agent die week opleverde.
    try:
        from datetime import datetime as _dt
        if _dt.now().weekday() == 4:
            import agentscore
            gegevens["vrijdagscore"] = agentscore.score()
    except Exception as e:
        print(f"Ochtendbericht, vrijdagscore mislukt: {e}")
    return gegevens


def tekst(gegevens, extra_regels=None):
    """(onderwerp, html). Gewone taal, geen opmaak die in een mailprogramma breekt."""
    from html import escape
    doen = gegevens["te_doen"]
    # De dagtaken (1 oktober). Zonder (oude aanroep): de te_doen-lijst zelf.
    taken = gegevens.get("dagtaken")
    if taken is None:
        taken = [{"tekst": t, "link": l} for t, l in doen]
    voorstel = gegevens.get("voorstellen") or []
    minuten = sum(int(t.get("minuten") or 0) for t in taken)
    telling = dict(gegevens["gisteren"])
    mails = telling.get("Koude mails verstuurd")
    klikken = telling.get("Hun Krillo-pagina geopend (ook door mailbeveiliging)")
    onderwerp = (f"Krillo ochtend: {len(taken) or 'niets'} voor jou"
                 + (f" (ongeveer {minuten} min)" if minuten else "")
                 + (f", {len(voorstel)} voorstel(len)" if voorstel else "")
                 + f", {mails if mails is not None else '?'} mails, "
                 f"{klikken if klikken is not None else '?'} bekeken")
    stuk = ["<div style='font-family:Arial,sans-serif;font-size:15px;line-height:1.55;max-width:600px'>"]
    if gegevens.get("nacht"):
        n = gegevens["nacht"]
        stuk.append(f"<p style='margin:0 0 14px;padding:8px 10px;background:{'#EAF5EC' if n['goed'] else '#FDECEA'}'>"
                    f"{escape(n['tekst'])}</p>")
    stuk += [
            "<h2 style='font-size:17px;margin:0 0 8px'>Wat jij vandaag moet doen"
            + (f" (ongeveer {minuten} minuten)" if minuten else "") + "</h2>"]
    if taken:
        regels = []
        for t in taken:
            r = f"<li style='margin-bottom:6px'>{escape(t['tekst'])}"
            if t.get("minuten"):
                r += f" <span style='color:#666'>({int(t['minuten'])} min)</span>"
            if t.get("link"):
                r += f": <a href='{escape(t['link'])}'>{'openen of op gedaan zetten' if t.get('gedaan') else 'openen'}</a>"
            regels.append(r + "</li>")
        stuk.append("<ol style='padding-left:20px;margin:0 0 18px'>" + "".join(regels) + "</ol>")
    else:
        stuk.append("<p style='margin:0 0 18px'>Niets. Alles loopt vanzelf.</p>")
    if voorstel:
        stuk.append("<h2 style='font-size:17px;margin:0 0 8px'>Voorstellen: zeg ja of nee</h2>"
                    "<p style='margin:0 0 8px;color:#666'>Een tik op de link opent een pagina met twee knoppen. "
                    "Bij een handeling gebeurt het meteen na akkoord; een nieuwe functie gaat op de bouwlijst "
                    "voor Claude.</p><ol style='padding-left:20px;margin:0 0 18px'>")
        soortnaam = {"actie": "handeling", "taak": "taak voor jou", "bouwen": "nieuwe functie"}
        for v in voorstel:
            stuk.append(f"<li style='margin-bottom:10px'><strong>{escape(v['titel'])}</strong> "
                        f"<span style='color:#666'>({soortnaam.get(v['soort'], v['soort'])}, "
                        f"{escape(v.get('bron') or '')})</span><br>{escape(v.get('waarom') or '')}<br>"
                        f"<a href='{escape(v['link'])}'>ja of nee</a></li>")
        stuk.append("</ol>")
    if gegevens.get("bouwlijst"):
        stuk.append(f"<p style='margin:0 0 18px'>Op de bouwlijst voor Claude: <strong>{gegevens['bouwlijst']}"
                    f"</strong>. De tekst om te plakken staat op /admin/voorstellen.</p>")
    if gegevens.get("vrijdagscore"):
        def _n(x):
            return "onbekend" if x is None else ("-" if x == "-" else str(x))
        stuk.append("<h2 style='font-size:17px;margin:0 0 8px'>Vrijdagscore: wat elke agent deze week opleverde</h2>"
                    "<table cellpadding='4' style='border-collapse:collapse;margin-bottom:18px'>"
                    "<tr><th style='text-align:left'>Agent</th><th>Verstuurd</th><th>Mensen keken</th>"
                    "<th>Doorgeklikt</th></tr>")
        for r in gegevens["vrijdagscore"]:
            stuk.append(f"<tr><td>{escape(r['naam'])}</td><td style='text-align:right'>{_n(r['verstuurd'])}</td>"
                        f"<td style='text-align:right'>{_n(r['mensen']) if r['mensen'] is not None else 'niet te tellen'}</td>"
                        f"<td style='text-align:right'>{_n(r['doorgeklikt']) if r['doorgeklikt'] is not None else 'niet te tellen'}</td></tr>")
        stuk.append("</table>")
    stuk.append("<h2 style='font-size:17px;margin:0 0 8px'>Wat de agents de laatste 24 uur deden</h2>"
                "<table cellpadding='4' style='border-collapse:collapse;margin-bottom:18px'>")
    for wat, n in gegevens["gisteren"]:
        stuk.append(f"<tr><td>{escape(wat)}</td><td style='text-align:right;font-weight:700'>"
                    f"{'onbekend' if n is None else n}</td></tr>")
    if gegevens.get("klaar_voor_post") is not None:
        stuk.append(f"<tr><td>Winkels klaar voor de koude mail</td><td style='text-align:right;"
                    f"font-weight:700'>{gegevens['klaar_voor_post']}</td></tr>")
    stuk.append("</table>")
    if gegevens.get("kosten_agents"):
        stuk.append("<h2 style='font-size:17px;margin:0 0 8px'>Waar het geld heen ging (laatste 7 dagen)</h2>"
                    f"<p style='margin:0 0 6px;color:#666'>Dagpot: {gegevens.get('dagpot', 0):.2f} euro. "
                    "Gemiddeld per dag:</p><table cellpadding='4' style='border-collapse:collapse;margin-bottom:18px'>")
        for r in gegevens["kosten_agents"]:
            stuk.append(f"<tr><td>{escape(r['naam'])}</td><td style='text-align:right;font-weight:700'>"
                        f"{r['kosten'] / 7:.2f} euro</td></tr>")
        stuk.append("</table>")
    if extra_regels:
        stuk.append("<h2 style='font-size:17px;margin:0 0 8px'>De benadering</h2>")
        stuk.extend(f"<p style='margin:0 0 8px'>{escape(r)}</p>" for r in extra_regels)
    stuk.append("</div>")
    return onderwerp, "".join(stuk)
