"""
Krillo - betaalkoppeling met Mollie.

Regelt twee dingen:
1. De eenmalige audit (79 euro): een gewone eenmalige betaling.
2. Het maandelijkse abonnement (39 euro): eerst een klant aanmaken bij Mollie,
   daarna een eerste betaling die de machtiging vastlegt, en zodra die betaling
   lukt (via de webhook) wordt het echte doorlopende abonnement aangemaakt.

Vereist een omgevingsvariabele MOLLIE_API_KEY, veilig in te stellen in Render
onder Settings > Environment, nooit in de code zelf.
"""

import os
from mollie.api.client import Client
from mollie.api.error import Error as MollieError

AUDIT_PRICE = {"currency": "EUR", "value": "79.00"}

# ---------------------------------------------------------------------------
# DE PAKKETTEN, zoals ze sinds 17 september 2026 zijn
# ---------------------------------------------------------------------------
#
# Hiervoor was het "149 euro eenmalig" plus "39 euro per maand". Dat is
# veranderd in drie MAANDPAKKETTEN, om twee redenen.
#
# 1. Het product is maandelijks geworden. De index wordt elke maand opnieuw
#    gemeten, er komt elke maand een nameting en een waarschuwing als je zakt.
#    Daar past geen eenmalige betaling bij.
#
# 2. De markt. Otterly vraagt 189 dollar per maand, Scrunch 250 tot 500,
#    AthenaHQ 295, en die leveren allemaal ALLEEN een rapport. Krillo voert het
#    werk uit en vroeg 39. Dat leest niet als voordelig maar als goedkoop.
#    Onderbouwing staat in krillo-prijzen-en-concurrentie-17-09-2026.
#
# Alle drie lopen via hetzelfde abonnement bij Mollie. Alleen het bedrag en de
# omschrijving verschillen, zodat er maar EEN betaalstroom te onderhouden is.
PAKKETTEN = {
    "watch": {
        "prijs": {"currency": "EUR", "value": "49.00"},
        "naam": "Watch",
        "omschrijving": "Krillo Watch, your monthly rank and fixes to do yourself",
    },
    "fix": {
        "prijs": {"currency": "EUR", "value": "149.00"},
        "naam": "Fix",
        "omschrijving": "Krillo Fix, your monthly rank and we carry out the fixes",
    },
    "merken": {
        "prijs": {"currency": "EUR", "value": "490.00"},
        "naam": "Brands and agencies",
        "omschrijving": "Krillo for brands and agencies, up to 25 stores",
    },
}

# Welk pakket het wordt als er niets meegestuurd is. Fix, want dat is het
# pakket waar de site naartoe stuurt en waar het verschil met de rest van de
# markt in zit.
STANDAARD_PAKKET = "fix"


def pakket_van(naam):
    """Het pakket bij een naam, met terugval op het standaardpakket.

    Nooit omvallen op een onbekende naam: dan zou iemand die op betalen drukt
    een foutmelding krijgen op precies het moment dat hij besloten had."""
    return PAKKETTEN.get((naam or "").strip().lower(), PAKKETTEN[STANDAARD_PAKKET])


# Blijft bestaan voor code en oude links die deze namen nog gebruiken.
MONITORING_PRICE = PAKKETTEN["fix"]["prijs"]
UITVOERING_PRICE = {"currency": "EUR", "value": "149.00"}


def get_mollie_client():
    api_key = os.environ.get("MOLLIE_API_KEY")
    if not api_key:
        return None
    client = Client()
    client.set_api_key(api_key)
    # Nooit eindeloos wachten. Loopt de verbinding met Mollie vast, dan willen
    # we een foutmelding, geen pagina die blijft laden.
    try:
        client.set_timeout(15)
    except Exception:
        pass
    return client


def create_audit_payment(base_url, webshop_url, email, bedrijfsnaam=None, bron=None):
    """Maakt een eenmalige betaling aan voor de volledige audit.

    "bron" is het campagnelabel waarmee deze bezoeker binnenkwam. Dat gaat
    bewust mee in de metadata van Mollie en niet in de terugkeerlink: metadata
    krijgen we ongewijzigd terug in de webhook, ook als iemand een dag over een
    overboeking doet en zijn browser allang dicht is. Zonder dit weten we wel
    hoeveel omzet er was, maar niet welke klik die omzet werd."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Payments are not active yet. Please try again later."}

    try:
        payment = client.payments.create({
            "amount": AUDIT_PRICE,
            "description": f"Krillo volledige audit voor {webshop_url}",
            "redirectUrl": f"{base_url}/bedankt?type=audit",
            "webhookUrl": f"{base_url}/webhooks/mollie",
            "metadata": {"type": "audit", "webshop_url": webshop_url, "email": email,
                         "bedrijfsnaam": bedrijfsnaam, "bron": bron},
        })
        _zet_terugkeerlink_met_kenmerk(client, payment, base_url, "audit")
        return {"checkout_url": payment.checkout_url, "payment_id": payment.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


def create_uitvoering_payment(base_url, webshop_url, email, bedrijfsnaam=None, bron=None,
                              platform=None):
    """Eenmalige betaling voor "wij voeren het uit in je webshop".

    Het platform gaat mee in de metadata omdat de vervolgmail per platform
    anders is: bij Shopify vragen we om een samenwerkersverzoek goed te keuren,
    bij WooCommerce om een beheerdersaccount. Sturen we de verkeerde uitleg,
    dan blijft de klant steken op stap één en hebben we zijn geld al."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Payments are not active yet. Please try again later."}

    try:
        payment = client.payments.create({
            "amount": UITVOERING_PRICE,
            "description": f"Krillo voert de verbeteringen uit voor {webshop_url}",
            "redirectUrl": f"{base_url}/bedankt?type=uitvoering",
            "webhookUrl": f"{base_url}/webhooks/mollie",
            "metadata": {"type": "uitvoering", "webshop_url": webshop_url, "email": email,
                         "bedrijfsnaam": bedrijfsnaam, "bron": bron, "platform": platform},
        })
        _zet_terugkeerlink_met_kenmerk(client, payment, base_url, "uitvoering")
        return {"checkout_url": payment.checkout_url, "payment_id": payment.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


def create_monitoring_signup(base_url, email, webshop_url, bedrijfsnaam=None, bron=None,
                             pakket=STANDAARD_PAKKET):
    """Stap 1 van het abonnement: klant aanmaken en de eerste betaling starten.
    Zodra deze betaling lukt (zie webhook), maken we het echte, doorlopende
    abonnement aan via create_subscription hieronder."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Payments are not active yet. Please try again later."}

    try:
        customer = client.customers.create({
            "name": webshop_url,
            "email": email,
            "metadata": {"webshop_url": webshop_url},
        })
        gekozen = pakket_van(pakket)
        first_payment = customer.payments.create({
            "amount": gekozen["prijs"],
            "description": f"{gekozen['omschrijving']}, first month",
            "redirectUrl": f"{base_url}/bedankt?type=monitoring",
            "webhookUrl": f"{base_url}/webhooks/mollie",
            "sequenceType": "first",
            "metadata": {"type": "monitoring_first_payment", "webshop_url": webshop_url,
                         "customer_id": customer.id, "email": email,
                         "bedrijfsnaam": bedrijfsnaam, "bron": bron,
                         # Het pakket MOET mee in de metadata. De webhook maakt
                         # daarna het doorlopende abonnement aan, en die weet
                         # anders niet of het 49 of 149 per maand wordt.
                         "pakket": (pakket or STANDAARD_PAKKET)},
        })
        _zet_terugkeerlink_met_kenmerk(client, first_payment, base_url, "monitoring")
        return {"checkout_url": first_payment.checkout_url, "payment_id": first_payment.id, "customer_id": customer.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


def over_een_maand(vandaag=None):
    """Dezelfde dag volgende maand, of de laatste dag als die niet bestaat
    (31 januari wordt 28 of 29 februari)."""
    import calendar
    from datetime import date
    vandaag = vandaag or date.today()
    jaar = vandaag.year + (1 if vandaag.month == 12 else 0)
    maand = 1 if vandaag.month == 12 else vandaag.month + 1
    return date(jaar, maand, min(vandaag.day, calendar.monthrange(jaar, maand)[1]))


def alle_klanten(client):
    """ALLE klanten bij Mollie, pagina voor pagina.

    WAAROM (gevonden 23 september): client.customers.list() geeft maar EEN
    pagina terug, en in deze versie van de Mollie-bibliotheek zijn dat er tien.
    Elke kassa maakt een klant aan, ook als iemand niet afrekent. Na tien
    pogingen zag zoek_abonnement een betalende klant dus niet meer: geen
    bescherming tegen dubbel betalen, Fix-klanten niet op de werklijst, en
    geen wekelijkse scan. Nu volgen wij de volgende-pagina-link tot het eind."""
    pagina = client.customers.list(limit=250)
    rondes = 0
    while pagina is not None and rondes < 200:
        for klant in pagina:
            yield klant
        rondes += 1
        pagina = pagina.get_next()


def create_subscription(customer_id, pakket=STANDAARD_PAKKET, webhook_url=None, startdatum=None):
    """Stap 2, wordt aangeroepen vanuit de webhook zodra de eerste betaling is gelukt.
    Zet het echte, maandelijks terugkerende abonnement op.

    STARTDATUM OVER EEN MAAND (23 september). Zonder startDate begint Mollie
    het abonnement VANDAAG, en dan wordt er op de dag van de eerste betaling
    meteen nog een keer afgeschreven: twee keer betalen voor de eerste maand.
    De eerste maand is al betaald, dus de eerste incasso hoort een maand later.

    MET WEBHOOK. Zonder webhookUrl horen wij niets van de maandbetalingen: geen
    factuur vanaf maand twee, en een mislukte incasso valt niemand op."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Mollie niet geconfigureerd."}

    try:
        customer = client.customers.get(customer_id)
        gekozen = pakket_van(pakket)
        gegevens = {
            "amount": gekozen["prijs"],
            "interval": "1 month",
            "startDate": (startdatum or over_een_maand()).isoformat(),
            "description": f"{gekozen['omschrijving']} (monthly)",
        }
        if webhook_url:
            gegevens["webhookUrl"] = webhook_url
        subscription = customer.subscriptions.create(gegevens)
        return {"subscription_id": subscription.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


def pakket_bij_bedrag(waarde):
    """Welk pakket hoort bij dit maandbedrag, of None als we het niet weten.

    Waarom op bedrag: bij Mollie staat het abonnement als bedrag plus
    omschrijving, niet als pakketnaam. Het bedrag is het enige dat zeker
    klopt, want dat is wat er echt afgeschreven wordt."""
    if not waarde:
        return None
    for sleutel, pakket in PAKKETTEN.items():
        if str(waarde) == pakket["prijs"]["value"]:
            return sleutel
    return None


def _klant_id_uit_database(webshop_url):
    """De Mollie-klant die wij bij de eerste betaling bij deze winkel bewaarden.
    Scheelt het doorlopen van alle klanten bij Mollie."""
    try:
        import db
        return db.mollie_klant_van(webshop_url)
    except Exception:
        return None


def zoek_abonnement(webshop_url):
    """Zoekt het actieve abonnement bij een webshop-URL. Geeft de klant-id en
    het abonnement-id terug, zodat we het kunnen opzeggen.

    Eerst de klant die wij zelf bewaarden, dan pas alle klanten bij Mollie,
    pagina voor pagina (zie alle_klanten)."""
    client = get_mollie_client()
    if client is None:
        return None
    try:
        kandidaten = []
        eigen_id = _klant_id_uit_database(webshop_url)
        if eigen_id:
            try:
                kandidaten.append(client.customers.get(eigen_id))
            except Exception as e:
                print(f"Bewaarde Mollie-klant {eigen_id} ophalen mislukt: {e}")
        import itertools
        for customer in itertools.chain(kandidaten, alle_klanten(client)):
            metadata = customer.metadata or {}
            if metadata.get("webshop_url") != webshop_url:
                continue
            for sub in customer.subscriptions.list():
                if sub.get("status") == "active":
                    # Het BEDRAG en de omschrijving gaan mee. Daaraan is te
                    # zien welk pakket iemand heeft, en dat bepaalt of wij het
                    # werk in zijn winkel doen (Fix) of dat hij het zelf doet
                    # (Watch). Mollie kent geen pakketveld; het bedrag is wat
                    # er elke maand echt afgeschreven wordt.
                    bedrag = (sub.get("amount") or {})
                    return {"customer_id": customer.id, "subscription_id": sub.id,
                            "next_payment_date": sub.get("nextPaymentDate"),
                            "bedrag": bedrag.get("value"),
                            "omschrijving": sub.get("description"),
                            "pakket": pakket_bij_bedrag(bedrag.get("value"))}
    except (MollieError, Exception) as e:
        print(f"Abonnement zoeken mislukt: {e}")
    return None


def zeg_abonnement_op(customer_id, subscription_id):
    """Zegt het abonnement op bij Mollie. De klant houdt toegang tot het einde
    van de al betaalde periode, er wordt alleen niet opnieuw geincasseerd."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Cancelling is not possible right now. Please try again later."}
    try:
        customer = client.customers.get(customer_id)
        customer.subscriptions.delete(subscription_id)
        return {"ok": True}
    except (MollieError, Exception) as e:
        print(f"Abonnement opzeggen mislukt: {e}")
        return {"error": "Cancelling did not work. Email hello@krilloai.com and we will sort it out by hand."}


def _zet_terugkeerlink_met_kenmerk(client, payment, base_url, soort):
    """Zet het betaalkenmerk alsnog in de terugkeerlink.

    Waarom in twee stappen: bij het AANMAKEN weten wij het kenmerk nog niet, dus
    de link kan er niet in. Daardoor kon de bedanktpagina nooit weten of er echt
    betaald was, en stond er een groen vinkje boven, ook voor iemand die bij zijn
    bank op annuleren had gedrukt. Die zat te wachten op een mail die nooit kwam.

    Mislukt dit, dan blijft de oude link staan en gedraagt de bedanktpagina zich
    zoals eerst. Een bijwerking die niet lukt mag nooit een betaling tegenhouden."""
    try:
        client.payments.update(
            payment.id,
            {"redirectUrl": f"{base_url}/bedankt?type={soort}&ref={payment.id}"})
    except Exception as e:
        print(f"Terugkeerlink met kenmerk zetten mislukt voor {payment.id}: {e}")


def get_payment_status(payment_id):
    client = get_mollie_client()
    if client is None:
        return None
    try:
        payment = client.payments.get(payment_id)
        bedrag = None
        try:
            bedrag = float(payment.amount.get("value")) if payment.amount else None
        except (TypeError, ValueError):
            bedrag = None
        return {
            "status": payment.status,
            "is_paid": payment.is_paid(),
            # Voor de maandbetalingen van een abonnement: die hebben geen
            # metadata van ons, alleen een abonnement en een klant.
            "subscription_id": getattr(payment, "subscription_id", None),
            "customer_id": getattr(payment, "customer_id", None),
            "metadata": payment.metadata,
            "created_at": payment.created_at,
            "bedrag": bedrag,
        }
    except (MollieError, Exception):
        return None


def list_active_monitoring_customers():
    """Haalt alle klanten met een actief monitoring-abonnement op, voor de
    wekelijkse cron-taak die opnieuw scant en een update stuurt."""
    client = get_mollie_client()
    if client is None:
        return []

    result = []
    try:
        for customer in alle_klanten(client):
            try:
                subs = list(customer.subscriptions.list())
            except (MollieError, Exception):
                continue
            if any(s.get("status") == "active" for s in subs):
                metadata = customer.metadata or {}
                webshop_url = metadata.get("webshop_url")
                email = customer.get("email")
                if webshop_url and email:
                    result.append({"email": email, "webshop_url": webshop_url})
    except (MollieError, Exception):
        return []
    return result


def list_recent_orders(limit=25):
    """Haalt de meest recente betaalde bestellingen op, voor het bestel-overzicht."""
    client = get_mollie_client()
    if client is None:
        return []

    orders = []
    try:
        # Bewust een kleine limiet: dit overzicht moet snel laden. Bij veel
        # bestellingen bouwen we later een pagina-indeling.
        for i, payment in enumerate(client.payments.list()):
            if i >= limit:
                break
            if not payment.is_paid():
                continue
            metadata = payment.metadata or {}
            orders.append({
                "id": payment.id,
                "type": metadata.get("type", "onbekend"),
                "webshop_url": metadata.get("webshop_url", "-"),
                "email": metadata.get("email", "-"),
                "bron": metadata.get("bron") or "rechtstreeks",
                "amount": payment.amount.get("value") if payment.amount else "-",
                "paid_at": payment.paid_at,
                "description": payment.description,
            })
    except (MollieError, Exception):
        return []

    orders.sort(key=lambda o: o["paid_at"] or "", reverse=True)
    return orders


def klant_bij_id(customer_id):
    """Webadres, e-mailadres en pakket van een Mollie-klant. Voor de
    maandbetalingen, die zelf geen metadata van ons meedragen."""
    client = get_mollie_client()
    if client is None or not customer_id:
        return None
    try:
        klant = client.customers.get(customer_id)
        metadata = klant.metadata or {}
        return {"webshop_url": metadata.get("webshop_url"), "email": klant.get("email")}
    except (MollieError, Exception) as e:
        print(f"Mollie-klant {customer_id} ophalen mislukt: {e}")
        return None
