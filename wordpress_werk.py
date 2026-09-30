"""Fix voor WordPress met WooCommerce: dezelfde drie wijzigingen als de Shopify-app (stap 87, 30 september).

WAAROM DIT BESTAAT. WooCommerce is het grootste platform onder Nederlandse en
Belgische webshops. Voor een Fix-klant op WooCommerce deed Nino alles met de
hand, via het werkbriefje. Dat schaalt niet: bij twintig klanten is het een
dagtaak. Nu kan Krillo hetzelfde als bij Shopify:
1. beschrijvingen bij productfoto's die er geen hebben (alt-tekst);
2. productteksten voor producten met (bijna) geen tekst;
3. een pagina met veelgestelde vragen, als die er nog niet is.

HOE DE WINKEL TOEGANG GEEFT. Geen beheerderswachtwoord, maar een
applicatiewachtwoord: WordPress, Gebruikers, Profiel, onderaan
Applicatiewachtwoorden, naam "Krillo", Toevoegen. Dat wachtwoord geldt alleen
voor de REST API, en de winkel trekt het in met een klik. Het gaat versleuteld
de database in (db.bewaar_koppeling, kluis.py), nooit leesbaar, nooit in een
logregel.

DE REGELS, precies als bij Shopify (shopify_werk.pas_toe):
- eerst kijken wat er NU staat, niet wat er stond toen het voorstel gemaakt
  werd: heeft de eigenaar intussen zelf iets ingevuld, dan blijven wij eraf;
- de oude waarde vastleggen VOOR het schrijven; lukt dat niet, dan schrijven
  wij niet, want een wijziging die niet terug kan mogen wij niet maken;
- alles kan terug met zet_terug;
- lukt het schrijven niet, dan de vastgelegde wijziging weer weghalen, zodat
  het overzicht nooit iets meldt dat niet gebeurd is.

WAT NOG MOET: dit is getest tegen een nagebootste WooCommerce (test_wordpress_werk),
niet tegen een echte winkel. Daarom staat WooCommerce in toepasmodule nog op
automatisch: False. Pas na een proef op een echte WooCommerce-testsite (Nino:
een gratis tijdelijke site bij TasteWP of InstaWP) gaat die vlag om.

De teksten zelf maakt shopify_werk (dezelfde opdrachten aan het model); hier
alleen het praten met WordPress.
"""
import re

import requests

import db
import shopify_werk as sw

TIJDSLIMIET = 20
PER_PAGINA = 100
MAX_PRODUCTEN = 1000
PLATFORM = "woocommerce"


class Fout(Exception):
    pass


def _http(methode, url, gebruiker, wachtwoord, json=None, params=None):
    """Een verzoek aan de REST API. Apart, zodat de test hem kan vervangen."""
    return requests.request(methode, url, auth=(gebruiker, wachtwoord), json=json, params=params,
                            timeout=TIJDSLIMIET, headers={"User-Agent": "Krillo/1.0 (+https://krilloai.com)"})


def schoon_site(adres):
    """Van "mijnwinkel.nl/" naar "https://mijnwinkel.nl". Alleen https: een
    wachtwoord over een onversleutelde lijn sturen doen wij niet."""
    adres = (adres or "").strip().rstrip("/")
    if not adres:
        return ""
    if adres.startswith("http://"):
        return ""
    if not adres.startswith("https://"):
        adres = "https://" + adres
    return adres


class Winkel:
    """Een WooCommerce-winkel met zijn toegang."""

    def __init__(self, site, gebruiker, wachtwoord):
        self.site = schoon_site(site)
        self.gebruiker = (gebruiker or "").strip()
        # WordPress toont het applicatiewachtwoord in blokjes met spaties; die
        # mogen mee, maar het werkt ook zonder.
        self.wachtwoord = (wachtwoord or "").strip()

    def _vraag(self, methode, pad, json=None, params=None):
        if not self.site:
            raise Fout("Het adres moet met https:// beginnen.")
        try:
            r = _http(methode, f"{self.site}/wp-json/{pad.lstrip('/')}", self.gebruiker, self.wachtwoord,
                      json=json, params=params)
        except requests.RequestException as e:
            raise Fout(f"De winkel is niet bereikbaar: {type(e).__name__}.")
        if r.status_code in (401, 403):
            raise Fout("WordPress weigert de toegang. Klopt de gebruikersnaam, en is het een "
                       "applicatiewachtwoord (niet het gewone wachtwoord)?")
        if r.status_code == 404:
            raise Fout("Dit onderdeel bestaat niet op deze site. Staat WooCommerce aan, en is de "
                       "REST API niet uitgezet door een beveiligingsplug-in?")
        if r.status_code >= 400:
            raise Fout(f"WordPress gaf fout {r.status_code}.")
        try:
            return r.json()
        except ValueError:
            raise Fout("WordPress gaf geen leesbaar antwoord.")

    # ------------------------------------------------------------ nakijken

    def controleer(self):
        """Werkt de toegang, en mag deze gebruiker producten en pagina's
        aanpassen? Geeft {"gelukt", "fout", "naam"}."""
        try:
            ik = self._vraag("GET", "wp/v2/users/me", params={"context": "edit"})
        except Fout as e:
            return {"gelukt": False, "fout": str(e)}
        rollen = set(ik.get("roles") or [])
        if not rollen & {"administrator", "shop_manager"}:
            return {"gelukt": False, "fout": "Deze gebruiker mag de winkel niet aanpassen. Maak het "
                                              "applicatiewachtwoord aan bij een beheerder of winkelmanager."}
        try:
            self._vraag("GET", "wc/v3/products", params={"per_page": 1})
        except Fout as e:
            return {"gelukt": False, "fout": f"WooCommerce: {e}"}
        return {"gelukt": True, "fout": None, "naam": ik.get("name") or self.gebruiker}

    # ------------------------------------------------------------ ophalen

    def producten(self, maximaal=MAX_PRODUCTEN):
        alles, pagina = [], 1
        while len(alles) < maximaal:
            stuk = self._vraag("GET", "wc/v3/products",
                               params={"per_page": PER_PAGINA, "page": pagina, "status": "publish"})
            if not stuk:
                break
            alles.extend(stuk)
            if len(stuk) < PER_PAGINA:
                break
            pagina += 1
        return alles[:maximaal]

    def paginas(self):
        return self._vraag("GET", "wp/v2/pages", params={"per_page": 100, "context": "edit"}) or []

    def zoek_gebreken(self):
        """Wat er ontbreekt, in dezelfde vorm als shopify_werk.zoek_gebreken,
        zodat de voorstellen en het scherm erna niets anders hoeven te weten."""
        producten = self.producten()
        paginas = self.paginas()
        zonder_alt, dunne_tekst = [], []
        for p in producten:
            soort = ", ".join(c.get("name") or "" for c in (p.get("categories") or []))
            merk = ""
            for kenmerk in p.get("attributes") or []:
                if (kenmerk.get("name") or "").lower() in ("merk", "brand"):
                    merk = ", ".join(kenmerk.get("options") or [])
            for afbeelding in p.get("images") or []:
                if not (afbeelding.get("alt") or "").strip():
                    zonder_alt.append({"product_id": p["id"], "afbeelding_id": afbeelding.get("id"),
                                       "titel": p.get("name") or "", "src": afbeelding.get("src") or "",
                                       "soort": soort, "merk": merk})
            if len(sw._kale_tekst(p.get("description"))) < sw.TEKST_ONDERGRENS:
                dunne_tekst.append({"product_id": p["id"], "titel": p.get("name") or "", "soort": soort,
                                    "merk": merk, "tags": ", ".join(t.get("name") or "" for t in p.get("tags") or []),
                                    "huidig": sw._kale_tekst(p.get("description")), "prijs": p.get("price")})
        heeft_faq = any(re.search(r"faq|veelgestelde|vragen|questions", (pg.get("slug") or "") + " "
                                  + ((pg.get("title") or {}).get("raw") or (pg.get("title") or {}).get("rendered") or ""),
                                  re.I) for pg in paginas)
        return {"producten_bekeken": len(producten), "zonder_alt": zonder_alt, "dunne_tekst": dunne_tekst,
                "heeft_faq": heeft_faq, "paginas": len(paginas),
                "voorbeeldproducten": [{"titel": p.get("name"),
                                        "soort": ", ".join(c.get("name") or "" for c in p.get("categories") or []),
                                        "tekst": sw._kale_tekst(p.get("description"))[:400]} for p in producten[:8]]}

    # ------------------------------------------------------------ voorstellen

    def maak_voorstellen(self, markt=None):
        """Zelfde voorstellen als bij Shopify, met WordPress-kenmerken en -links."""
        gebreken = self.zoek_gebreken()
        alles, fouten = [], []
        for stuk in (sw.maak_faq_voorstel(self.site, None, gebreken, markt),
                     sw.maak_tekst_voorstellen(self.site, None, gebreken, markt),
                     sw.maak_alt_voorstellen(self.site, None, gebreken, markt)):
            for v in stuk.get("voorstellen") or []:
                alles.append(self._naar_wordpress(v))
            if not stuk.get("gelukt") and stuk.get("fout"):
                fouten.append(stuk["fout"])
        return {"aantallen": {"zonder_alt": len(gebreken["zonder_alt"]), "dunne_tekst": len(gebreken["dunne_tekst"]),
                              "faq_ontbreekt": not gebreken["heeft_faq"],
                              "producten_bekeken": gebreken["producten_bekeken"]},
                "voorstellen": alles, "fouten": fouten}

    def _naar_wordpress(self, v):
        v = dict(v)
        v["id"] = "wp:" + v["id"].split(":", 1)[1]
        if v["soort"] in ("alt", "tekst"):
            v["link"] = f"{self.site}/wp-admin/post.php?post={v['product_id']}&action=edit"
        else:
            v["link"] = f"{self.site}/wp-admin/edit.php?post_type=page"
        return v

    # ------------------------------------------------------------ schrijven

    def _huidig(self, voorstel):
        soort = voorstel.get("soort")
        try:
            if soort == "alt":
                return (self._vraag("GET", f"wp/v2/media/{voorstel['afbeelding_id']}",
                                    params={"context": "edit"}).get("alt_text") or ""), None
            if soort == "tekst":
                return (self._vraag("GET", f"wc/v3/products/{voorstel['product_id']}").get("description") or ""), None
            if soort == "faq":
                return "", None
        except Fout as e:
            return None, str(e)
        return None, "Onbekend soort wijziging."

    def _faq_pagina(self):
        for pg in self.paginas():
            if (pg.get("slug") or "") == sw.FAQ_HANDLE:
                return pg
        return None

    def pas_toe(self, voorstel, klant_url):
        if not voorstel or not voorstel.get("id"):
            return {"gelukt": False, "fout": "Geen voorstel meegegeven."}
        huidig, fout = self._huidig(voorstel)
        if huidig is None:
            return {"gelukt": False, "fout": fout or "Kon de huidige waarde niet ophalen."}
        soort = voorstel["soort"]
        if soort in ("alt", "tekst"):
            grens = 1 if soort == "alt" else sw.TEKST_ONDERGRENS
            if len(sw._kale_tekst(huidig)) >= grens:
                return {"gelukt": False, "overgeslagen": True,
                        "fout": "Hier staat inmiddels al een tekst. Die laten wij staan."}
        if soort == "faq":
            try:
                if self._faq_pagina():
                    return {"gelukt": False, "overgeslagen": True, "fout": "Deze pagina bestaat al."}
            except Fout as e:
                return {"gelukt": False, "fout": str(e)}
        nieuw = voorstel.get("nieuw_html") or voorstel.get("nieuw")
        if not db.bewaar_wijziging(webshop_url=klant_url, taak_id=voorstel["id"], wat=voorstel.get("wat"),
                                   waar=voorstel.get("waar"), oude_waarde=huidig, nieuwe_waarde=nieuw):
            return {"gelukt": False, "fout": "Wij konden de oude tekst niet bewaren, dus wij hebben niets "
                                             "veranderd. Zo kan alles altijd terug."}
        try:
            if soort == "alt":
                self._vraag("POST", f"wp/v2/media/{voorstel['afbeelding_id']}", json={"alt_text": voorstel["nieuw"]})
            elif soort == "tekst":
                self._vraag("PUT", f"wc/v3/products/{voorstel['product_id']}", json={"description": nieuw})
            elif soort == "faq":
                titel = voorstel.get("titel") or sw.FAQ_TITELS["nl"]
                self._vraag("POST", "wp/v2/pages",
                            json={"title": titel, "slug": sw.FAQ_HANDLE, "content": nieuw, "status": "publish"})
            else:
                db.verwijder_wijziging(klant_url, voorstel["id"])
                return {"gelukt": False, "fout": "Onbekend soort wijziging."}
        except Fout as e:
            db.verwijder_wijziging(klant_url, voorstel["id"])
            return {"gelukt": False, "fout": str(e)}
        return {"gelukt": True, "id": voorstel["id"]}

    def zet_terug(self, wijziging, klant_url=None):
        taak_id = (wijziging or {}).get("taak_id") or ""
        oud = (wijziging or {}).get("oude_waarde")
        if not taak_id.startswith("wp:"):
            return {"gelukt": False, "fout": "Dit is geen wijziging in een WordPress-winkel."}
        delen = taak_id.split(":")
        try:
            if delen[1] == "alt" and len(delen) == 4:
                self._vraag("POST", f"wp/v2/media/{delen[3]}", json={"alt_text": oud or ""})
            elif delen[1] == "tekst" and len(delen) == 3:
                self._vraag("PUT", f"wc/v3/products/{delen[2]}", json={"description": oud or ""})
            elif delen[1] == "faq":
                pagina = self._faq_pagina()
                if pagina:
                    self._vraag("DELETE", f"wp/v2/pages/{pagina['id']}", params={"force": "true"})
            else:
                return {"gelukt": False, "fout": "Onbekend soort wijziging."}
        except Fout as e:
            return {"gelukt": False, "fout": str(e)}
        if klant_url:
            db.verwijder_wijziging(klant_url, taak_id)
        return {"gelukt": True, "id": taak_id}


def koppel(webshop_url, site, gebruiker, wachtwoord):
    """Toegang controleren en, als hij werkt, versleuteld bewaren.
    Geeft {"gelukt", "fout"}. Een toegang die niet werkt bewaren wij niet."""
    winkel = Winkel(site, gebruiker, wachtwoord)
    if not winkel.site:
        return {"gelukt": False, "fout": "Vul het adres van je winkel in, met https://."}
    if not winkel.gebruiker or not winkel.wachtwoord:
        return {"gelukt": False, "fout": "Vul je gebruikersnaam en het applicatiewachtwoord in."}
    uit = winkel.controleer()
    if not uit["gelukt"]:
        return uit
    if not db.bewaar_koppeling(webshop_url, PLATFORM, winkel.site,
                               {"gebruiker": winkel.gebruiker, "wachtwoord": winkel.wachtwoord}):
        return {"gelukt": False, "fout": "De toegang werkt, maar kon niet veilig bewaard worden. "
                                         "Probeer het later nog eens."}
    db.zet_koppeling_stand(webshop_url, "werkt")
    return {"gelukt": True, "fout": None}


def winkel_van(webshop_url):
    """De Winkel bij een klant, uit de versleutelde koppeling. None zonder koppeling."""
    k = db.get_koppeling(webshop_url, met_geheimen=True)
    if not k or k.get("platform") != PLATFORM or not k.get("wachtwoord"):
        return None
    return Winkel(k["basis_url"], k.get("gebruiker"), k.get("wachtwoord"))


def gekoppelde_winkels():
    """De winkels met een WooCommerce-koppeling, zonder sleutels."""
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT webshop_url, stand FROM koppelingen WHERE platform = %s ORDER BY webshop_url",
                            (PLATFORM,))
                return [{"webshop_url": r[0], "stand": r[1]} for r in cur.fetchall()]
    except Exception as e:
        print(f"Gekoppelde winkels ophalen mislukt: {e}")
        return []
    finally:
        conn.close()
