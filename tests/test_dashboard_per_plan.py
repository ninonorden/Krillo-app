"""Het dashboard per abonnement: wat een klant ziet klopt met wat hij kocht.

WAAROM DEZE TEST BESTAAT

27 september, een controle van het dashboard voor de eerste klant:
- Elke maand begon een nieuwe Fix-opdracht op "wacht op toegang", ook bij een
  Shopify-winkel en bij wie al lang toegang gaf.
- De wijzigingen (het bewijs van Fix) stonden alleen in beeld bij "opgeleverd".
- Een Fix-klant kreeg "Copy this exactly" en "Prefer to do it yourself?":
  huiswerk voor iemand die betaalde om het niet zelf te doen.
- Een Watch-klant kon nergens naar Fix; een opgezegde klant zag geen einddatum.
- "Lower is better": een betere plek was een korter staafje.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP

os.environ["DATABASE_URL"]="postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"]="testsleutel"; os.environ["BASE_URL"]="https://krilloai.com"
sys.path.insert(0, APP)
import db, app as k, klantbeeld

db.init_db()
U="https://fietsenwinkel-demo.nl"
nu=datetime.datetime.now(datetime.timezone.utc)
beeld={"webshop_url":U,"naam":"fietsenwinkel-demo.nl","categorie":"fietsen","land":"nl","ronde":1,
 "positie":7,"van":42,"vorige_positie":9,"verschil":2,"genoemd":6,"aanbevolen":2,"telbaar":30,
 "gemeten_op":nu,"verloop":[{"positie":9,"ronde":0,"afgerond_op":nu-datetime.timedelta(days=30)},{"positie":7,"ronde":1,"afgerond_op":nu}],
 "boven_mij":[{"positie":4,"webshop_url":"https://a.nl","naam":"Fietsplaats","genoemd":14},{"positie":5,"webshop_url":"https://b.nl","naam":"Bike Totaal","genoemd":12},{"positie":6,"webshop_url":"https://c.nl","naam":"Stadsfiets","genoemd":9}],
 "gemiste_vragen":[{"vraag":"Welke webshop verkoopt goede e-bikes?","concurrenten":["Fietsplaats","Stella"],"platforms":["bol.com"],"aanbevolen":[],"model":"gpt"},
                   {"vraag":"Waar koop ik een bakfiets online?","concurrenten":["Bakfiets.nl"],"platforms":[],"aanbevolen":[],"model":"gemini"}]}
klantbeeld.bouw=lambda url, land=None, **kw: dict(beeld)
k.klantbeeld.bouw=klantbeeld.bouw
plan={"acties":[{"titel":"Describe your e-bikes on the product pages","soort":"product text","merkje":"product text","oplossing":"Our e-bikes have a range of 80 to 120 km...","waar":"Product page of each e-bike, under the description","hoe":"","waarom":"ChatGPT names stores whose pages explain range and battery."},
                {"titel":"Add a questions page","soort":"page","merkje":"page","oplossing":"Which e-bike suits commuting? ...","waar":"A new page called Frequently asked questions","hoe":"","waarom":"Shoppers ask these questions to AI."}],"rest":0}
orig=k._klantgegevens
k._klantgegevens=lambda url: dict(orig(url), actieplan=plan)
def sql(q,v=None):
    c=db._get_connection()
    with c:
        with c.cursor() as cur: cur.execute(q,v)
    c.close()
def klant(pakket, stand=None, wijz=False, opgezegd=None):
    sql("DELETE FROM uitvoeringen WHERE webshop_url=%s",(U,)); sql("DELETE FROM klanten WHERE webshop_url=%s",(U,))
    sql("DELETE FROM wijzigingen WHERE webshop_url=%s",(U,))
    sql("INSERT INTO klanten (klant_token, webshop_url, email, aangemaakt_op, pakket, mollie_klant_id, opgezegd_op) VALUES ('dashtok',%s,'a@b.nl',now()-interval '20 days',%s,'cst_x',%s)",(U,pakket,opgezegd))
    if stand:
        sql("INSERT INTO uitvoeringen (payment_id, webshop_url, email, stand, opgeleverd_op) VALUES ('p1',%s,'a@b.nl',%s,%s)",(U,stand, nu if stand=='opgeleverd' else None))
    if wijz:
        db.bewaar_wijziging(U, "tekst", "Product text", "E-bike Urban 500", "Short text.", "Our Urban 500 e-bike has a range of 90 km and...") if hasattr(db,'bewaar_wijziging') else None
c=k.app.test_client()
fouten = []
def klopt(o, v):
    print(("  ok  " if v else "  FOUT ") + o)
    if not v: fouten.append(o)
pagina = {}
for naam,args in {"watch":("watch",None),"fix_wacht":("fix","wacht_op_toegang"),"fix_klaar":("fix","opgeleverd",True),"opgezegd":("watch",None,False,nu+datetime.timedelta(days=12)),"afgelopen":("watch",None,False,nu-datetime.timedelta(days=1))}.items():
    klant(*args)
    # Sinds 28 september staan de verbeteringen en het abonnement op eigen pagina's.
    pagina[naam]=(c.get("/mijn/dashtok/fixes?taal=en").get_data(as_text=True)
                  + c.get("/mijn/dashtok/plan?taal=en").get_data(as_text=True)
                  + c.get("/mijn/dashtok?taal=en").get_data(as_text=True))
w, fw, fk, og, af = (pagina[n] for n in ("watch","fix_wacht","fix_klaar","opgezegd","afgelopen"))
print("\n== WATCH ==")
klopt("kopieerknoppen", "Copy this exactly" in w and 'class="kopieer"' in w)
klopt("een weg naar Fix", "Switch to Fix" in w)
print("\n== FIX ==")
klopt("geen huiswerk: geen kopieerknop", 'class="kopieer"' not in fw and "What we put in your store" in fw)
klopt("geen 'Prefer to do it yourself'", "Prefer to do it yourself" not in fw + fk)
klopt("wachten op toegang staat in de titel, met een knop", "Waiting for access to your store" in fw and "Email us about access" in fw)
klopt("geen overstapknop voor wie Fix al heeft", "Switch to Fix" not in fw + fk)
klopt("de wijzigingen staan er", "Exactly what we changed" in fk)
print("\n== OPZEGGEN ==")
klopt("einddatum zichtbaar", "You keep full access until" in og)
klopt("geen verkoop aan wie net opzegde", "Switch to Fix" not in og)
klopt("afgelopen: geen betaalde inhoud meer", "Your plan has ended" in af and "Copy this exactly" not in af)
print("\n== GRAFIEK ==")
st = klantbeeld.balkhoogtes([{"positie":9,"van":42},{"positie":7,"van":42}])
klopt("betere plek is een hoger staafje", st[1]["hoogte"] > st[0]["hoogte"])
st = klantbeeld.balkhoogtes([{"positie":5,"van":42},{"positie":8,"van":42}])
klopt("gezakt wordt gemarkeerd", st[1]["gezakt"] and not st[0]["gezakt"])
klopt("de uitleg klopt: nummer 1 bovenaan", "Number 1 is at the top." in w)
sql("DELETE FROM uitvoeringen WHERE webshop_url=%s",(U,)); sql("DELETE FROM klanten WHERE webshop_url=%s",(U,))
sql("DELETE FROM wijzigingen WHERE webshop_url=%s",(U,))
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt"); sys.exit(1)
print("Alles goed: elk abonnement ziet wat het kocht.")
