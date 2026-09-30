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
    if na.get("kwaliteit"):
        uit.append((f"De kwaliteitsagent vond {len(na['kwaliteit'])} ding(en) in de index: "
                    + "; ".join(na["kwaliteit"][:3]), f"{basis_url}/admin/controle"))
    if na.get("concurrenten"):
        uit.append(("De concurrentieagent: " + "; ".join(na["concurrenten"][:2]), f"{basis_url}/compare"))
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
    # Stap 96 en 153: wat de leeragent de laatste dag onderzocht en voorstelt.
    try:
        import leeragent
        from datetime import datetime as _d, timedelta as _td, timezone as _tz
        for r in leeragent.laatste():
            if r.get("op") and r["op"] > _d.now(_tz.utc) - _td(days=1):
                if r.get("fout"):
                    uit.append((f"Leeragent ({r['onderwerp']}) mislukte: {r['fout'][:120]}", f"{basis_url}/admin/leren"))
                elif r.get("voorstellen"):
                    uit.append((f"Leeragent ({leeragent.ONDERWERPEN.get(r['onderwerp'], {}).get('naam', r['onderwerp'])}) "
                                f"stelt voor: {r['voorstellen'][0]}", f"{basis_url}/admin/leren"))
    except Exception:
        pass
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
    meetbaar = [slug for slug, _, _ in categorieen.CATEGORIEEN if slug not in ouders]
    for land in markten.index_landen():
        online = len(db.categorieen_per_land(land, categorieen.MINIMUM_VOOR_INDEX))
        regels.append((f"Ranglijsten openbaar in {land.upper()} (van {len(meetbaar)} categorieen)", online))
    per = db.winkels_per_categorie_in_land("nl") or {}
    gemeten = set(db.gemeten_categorieen())
    wachten = sorted((per.get(s, 0), s) for s in meetbaar if s not in gemeten)
    regels.append(("Categorieen die nog op genoeg winkels wachten (10 nodig)", len(wachten)))
    if wachten:
        regels.append(("Het dichtst bij (winkels nu)", ", ".join(f"{s} {n}" for n, s in wachten[::-1][:4])))
    regels.append(("Nieuwe winkels op de lijst gisteren",
                   _tel("SELECT count(*) FROM benadering WHERE toegevoegd_op > now() - interval '24 hours'")))
    return regels


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
    # 30 september, Nino: "zijn nu alle categorieen gescand? hoe groeien we
    # dit?". Elke ochtend de stand van de index zelf: hoeveel ranglijsten
    # openbaar, hoeveel categorieen nog wachten op genoeg winkels, en wat er
    # gisteren bij kwam.
    try:
        gisteren += index_groei()
    except Exception as e:
        print(f"Ochtendbericht, indexgroei mislukt: {e}")
    try:
        klaar_voor_post = len(db.te_mailen_met_positie(10000))
    except Exception:
        klaar_voor_post = None
    return {"te_doen": te_doen(basis_url), "gisteren": gisteren, "klaar_voor_post": klaar_voor_post}


def tekst(gegevens, extra_regels=None):
    """(onderwerp, html). Gewone taal, geen opmaak die in een mailprogramma breekt."""
    from html import escape
    doen = gegevens["te_doen"]
    telling = dict(gegevens["gisteren"])
    mails = telling.get("Koude mails verstuurd")
    klikken = telling.get("Mensen die hun Krillo-pagina openden")
    onderwerp = (f"Krillo ochtend: {len(doen) or 'niets'} voor jou, "
                 f"{mails if mails is not None else '?'} mails, "
                 f"{klikken if klikken is not None else '?'} bekeken")
    stuk = ["<div style='font-family:Arial,sans-serif;font-size:15px;line-height:1.55;max-width:600px'>",
            "<h2 style='font-size:17px;margin:0 0 8px'>Wat jij vandaag moet doen</h2>"]
    if doen:
        stuk.append("<ul style='padding-left:18px;margin:0 0 18px'>" + "".join(
            f"<li style='margin-bottom:6px'>{escape(t)}: <a href='{escape(l)}'>openen</a></li>" for t, l in doen)
            + "</ul>")
    else:
        stuk.append("<p style='margin:0 0 18px'>Niets. Alles loopt vanzelf.</p>")
    stuk.append("<h2 style='font-size:17px;margin:0 0 8px'>Wat de agents de laatste 24 uur deden</h2>"
                "<table cellpadding='4' style='border-collapse:collapse;margin-bottom:18px'>")
    for wat, n in gegevens["gisteren"]:
        stuk.append(f"<tr><td>{escape(wat)}</td><td style='text-align:right;font-weight:700'>"
                    f"{'onbekend' if n is None else n}</td></tr>")
    if gegevens.get("klaar_voor_post") is not None:
        stuk.append(f"<tr><td>Winkels klaar voor de koude mail</td><td style='text-align:right;"
                    f"font-weight:700'>{gegevens['klaar_voor_post']}</td></tr>")
    stuk.append("</table>")
    if extra_regels:
        stuk.append("<h2 style='font-size:17px;margin:0 0 8px'>De benadering</h2>")
        stuk.extend(f"<p style='margin:0 0 8px'>{escape(r)}</p>" for r in extra_regels)
    stuk.append("</div>")
    return onderwerp, "".join(stuk)
