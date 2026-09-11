"""Het werkbriefje en de oplevering.

Wat hier fout kan gaan en niemand merkt: de oude tekst wordt niet bewaard, of
de opdracht springt op "opgeleverd" terwijl de klant niets gekregen heeft. Dat
eerste breekt onze belofte dat alles terug te draaien is, het tweede laat een
betalende klant tussen wal en schip vallen. Daar zit deze test op.
"""
import os
import sys
import types

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


nep = types.ModuleType("payments")
nep.AUDIT_PRICE = {"currency": "EUR", "value": "79.00"}
nep.MONITORING_PRICE = {"currency": "EUR", "value": "39.00"}
nep.UITVOERING_PRICE = {"currency": "EUR", "value": "149.00"}
for naam in ("create_audit_payment", "create_monitoring_signup", "create_uitvoering_payment"):
    setattr(nep, naam, lambda *a, **k: {"error": "niet in deze test"})
nep.get_payment_status = lambda pid: None
nep.create_subscription = lambda cid: {}
nep.list_active_monitoring_customers = lambda: []
nep.list_recent_orders = lambda limit=25: []
nep.zoek_abonnement = lambda u: None
nep.zeg_abonnement_op = lambda a, b: {"ok": True}
sys.modules["payments"] = nep

import db
import paginataal
import app as krillo

# Een vast actieplan, zodat de test niet afhangt van echte metingen.
PLAN = {"kop": "Je wordt genoemd bij 2 van de 20 koopvragen.",
        "acties": [
            {"id": "faq", "soort": "vermoeden", "titel": "Zet deze vragen en antwoorden op je site",
             "waarom": "x", "hoe": "Plak dit op je servicepagina.",
             "links": [], "oplossing": "Hoe lang duurt de levering?\nTwee werkdagen.",
             "waar": "Shopify: Winkelinstellingen, dan Pagina's."},
            {"id": "alt_tekst", "soort": "vermoeden", "titel": "Geef je afbeeldingen een beschrijving",
             "waarom": "x", "hoe": "Vul de alt-tekst in.", "links": [],
             "oplossing": "Blauwe emaille mok van 300 ml", "waar": "Bij elke productfoto."},
        ], "rest": 0}
krillo._klantgegevens = lambda url: {
    "actieplan": PLAN, "vermeldingen": None, "controle": None, "beweging": None,
    "bronnen": None}

verstuurd = []
krillo.emailing.send_email = lambda to, onderwerp, html: (
    verstuurd.append({"to": to, "onderwerp": onderwerp, "html": html}) or True)

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

client = krillo.app.test_client()
WINKEL = "https://voorbeeldwinkel.nl"
SLEUTEL = "?key=testsleutel&url=voorbeeldwinkel.nl"

print("\n== de pagina's zitten achter de sleutel ==")
# Sinds de beheerpagina's achter een inlogscherm zitten is 302 het goede
# antwoord, en geen 404. Voor de dichte kant hoort een VERSE bezoeker gebruikt
# te worden: een client die eerder met sleutel binnenkwam blijft ingelogd.
zo("werkbriefje zonder sleutel",
   krillo.app.test_client().get("/admin/werkbriefje").status_code, 302)
zo("werkbriefje verkeerde sleutel",
   krillo.app.test_client().get("/admin/werkbriefje?key=fout").status_code, 302)
zo("oplevering zonder sleutel",
   krillo.app.test_client().get("/admin/oplevering").status_code, 302)

print("\n== het werkbriefje toont de taken met de plakteksten ==")
r = client.get("/admin/werkbriefje" + SLEUTEL, follow_redirects=True)
zo("laadt", r.status_code, 200)
p = r.get_data(as_text=True)
zo("eerste taak staat erop", "Zet deze vragen en antwoorden op je site" in p, True)
zo("de plaktekst staat erop", "Twee werkdagen." in p, True)
zo("waar het heen moet staat erop", "Winkelinstellingen" in p, True)
zo("waarschuwing over de oude tekst staat erop", "voordat je hem vervangt" in p.lower()
   or "vóórdat je hem vervangt" in p, True)

print("\n== zonder winkel geen gegok ==")
p = client.get("/admin/werkbriefje?key=testsleutel").get_data(as_text=True)
zo("vraagt om een adres", "Vul een webshop-adres in" in p, True)

print("\n== een wijziging vastleggen ==")
r = client.post("/admin/werkbriefje" + SLEUTEL, data={
    "taak_id": "faq", "wat": "Zet deze vragen en antwoorden op je site",
    "waar": "Shopify: Winkelinstellingen, dan Pagina's.",
    "oude_waarde": "Bel ons voor vragen.", "nieuwe_waarde": "Hoe lang duurt de levering?"})
zo("opslaan geeft een pagina terug", r.status_code, 200)
w = db.get_wijzigingen(WINKEL)
zo("er staat een wijziging", len(w), 1)
zo("de oude tekst is bewaard", w[0]["oude_waarde"], "Bel ons voor vragen.")
zo("de nieuwe tekst is bewaard", w[0]["nieuwe_waarde"], "Hoe lang duurt de levering?")
zo("de winkel is genormaliseerd", w[0]["webshop_url"], WINKEL)

print("\n== dezelfde taak nog eens opslaan werkt bij, geen dubbele regel ==")
client.post("/admin/werkbriefje" + SLEUTEL, data={
    "taak_id": "faq", "wat": "Zet deze vragen en antwoorden op je site",
    "oude_waarde": "Bel ons voor vragen, ma t/m vr.", "nieuwe_waarde": "Nieuw."})
w = db.get_wijzigingen(WINKEL)
zo("nog steeds een regel", len(w), 1)
zo("en bijgewerkt", w[0]["oude_waarde"], "Bel ons voor vragen, ma t/m vr.")

print("\n== een lege oude waarde mag, dat betekent 'stond er nog niet' ==")
client.post("/admin/werkbriefje" + SLEUTEL, data={
    "taak_id": "alt_tekst", "wat": "Geef je afbeeldingen een beschrijving",
    "oude_waarde": "   ", "nieuwe_waarde": "Blauwe emaille mok"})
w = {x["taak_id"]: x for x in db.get_wijzigingen(WINKEL)}
zo("twee wijzigingen", len(w), 2)
zo("lege oude waarde wordt leeg en niet een spatie", w["alt_tekst"]["oude_waarde"], None)

print("\n== het formulier toont terug wat er al vastligt ==")
p = client.get("/admin/werkbriefje" + SLEUTEL).get_data(as_text=True)
zo("de eerder ingevulde oude tekst staat in het vak", "Bel ons voor vragen, ma t/m vr." in p, True)

print("\n== weghalen ==")
client.post("/admin/werkbriefje" + SLEUTEL, data={"taak_id": "alt_tekst", "actie": "verwijderen"})
zo("er is er een weg", len(db.get_wijzigingen(WINKEL)), 1)
client.post("/admin/werkbriefje" + SLEUTEL, data={
    "taak_id": "alt_tekst", "wat": "Geef je afbeeldingen een beschrijving",
    "oude_waarde": "", "nieuwe_waarde": "Blauwe emaille mok"})
zo("en weer terug", len(db.get_wijzigingen(WINKEL)), 2)

print("\n== de oplevering ==")
p = client.get("/admin/oplevering" + SLEUTEL).get_data(as_text=True)
zo("laadt met de wijzigingen", "Bel ons voor vragen, ma t/m vr." in p, True)
zo("meldt dat er geen opdracht is", "geen betaalde opdracht" in p, True)

r = client.post("/admin/oplevering" + SLEUTEL)
zo("versturen zonder opdracht doet niets", len(verstuurd), 0)
zo("en zegt waarom", "geen opdracht" in r.get_data(as_text=True), True)

print("\n== met een echte opdracht erbij ==")
db.start_uitvoering("tr_1", WINKEL, "eigenaar@voorbeeldwinkel.nl", "Shopify")
uid = db.get_uitvoeringen(WINKEL)[0]["id"]
db.zet_uitvoering_stand(uid, "bezig")
r = client.post("/admin/oplevering" + SLEUTEL)
zo("de mail is verstuurd", len(verstuurd), 1)
zo("naar de klant", verstuurd[0]["to"], "eigenaar@voorbeeldwinkel.nl")
zo("de oude tekst staat in de mail", "Bel ons voor vragen, ma t/m vr." in verstuurd[0]["html"], True)
zo("en de nieuwe ook", "Blauwe emaille mok" in verstuurd[0]["html"], True)
zo("bij een lege oude waarde staat er uitleg",
   "dit is nieuw toegevoegd" in verstuurd[0]["html"], True)
zo("de opdracht staat nu op opgeleverd", db.get_uitvoeringen(WINKEL)[0]["stand"], "opgeleverd")

print("\n== als de mail mislukt blijft de stand staan ==")
db.zet_uitvoering_stand(uid, "bezig")
krillo.emailing.send_email = lambda *a, **k: False
r = client.post("/admin/oplevering" + SLEUTEL)
zo("stand niet verzet", db.get_uitvoeringen(WINKEL)[0]["stand"], "bezig")
zo("en dat wordt gemeld", "NIET verstuurd" in r.get_data(as_text=True), True)

print("\n== HTML uit een webshop sloopt de mail niet ==")
import emailing
zo("punthaken worden onschadelijk", "<script>" in emailing._veilig("<script>x</script>"), False)
zo("de tekst blijft leesbaar", "script" in emailing._veilig("<script>x</script>"), True)
zo("regeleindes worden regels", "<br>" in emailing._veilig("een\ntwee"), True)
zo("leeg blijft leeg", emailing._veilig(None), "")
zo("heel lange tekst wordt ingekort", "[ingekort]" in emailing._veilig("a" * 5000), True)

print("\n== een oplevering zonder enige wijziging wordt niet verstuurd ==")
zo("weigert", emailing.send_oplevering("a@b.nl", "https://x.nl", []), False)

print("\n== de klant ziet het terug op zijn eigen pagina ==")
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader(
    TEMPLATES))
basis = dict(webshop_url=WINKEL, klant_token="abc", voorbeeld=False, actieplan=PLAN,
             laatste=None, verschil=None, verloop=[], nieuwe_problemen=[],
             checks_by_categorie={}, vermeldingen=None, controle=None, beweging=None,
             bronnen=None, verklaring=None, taakstand=None, sleutel="x", status_labels={},
             # De vaste teksten van de pagina komen sinds de tweetalige versie
             # uit paginataal.py en niet meer uit het sjabloon zelf.
             t=paginataal.TEKSTEN["nl"], paginataal="nl", shopify_beheer=None)
u = dict(db.get_uitvoeringen(WINKEL)[0])
u["stand"] = "opgeleverd"
h = env.get_template("monitoring.html").render(
    uitvoering=u, wijzigingen=[dict(x) for x in db.get_wijzigingen(WINKEL)], **basis)
zo("het overzicht staat er ingeklapt bij",
   f"{paginataal.TEKSTEN['nl']['wijzigingen_kop']} (2)" in h, True)
zo("met de oude tekst", "Bel ons voor vragen, ma t/m vr." in h, True)

h = env.get_template("monitoring.html").render(uitvoering=None, wijzigingen=[], **basis)
zo("zonder opdracht geen overzicht", "Wat we precies veranderd hebben" in h, False)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
