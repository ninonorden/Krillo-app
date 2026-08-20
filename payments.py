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

AUDIT_PRICE = {"currency": "EUR", "value": "0.50"}  # TIJDELIJK OM TE TESTEN, terugzetten naar 79.00
MONITORING_PRICE = {"currency": "EUR", "value": "39.00"}


def get_mollie_client():
    api_key = os.environ.get("MOLLIE_API_KEY")
    if not api_key:
        return None
    client = Client()
    client.set_api_key(api_key)
    return client


def create_audit_payment(base_url, webshop_url, email, bedrijfsnaam=None):
    """Maakt een eenmalige betaling aan voor de volledige audit."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Betalen is nog niet actief, probeer het later opnieuw."}

    try:
        payment = client.payments.create({
            "amount": AUDIT_PRICE,
            "description": f"Krillo volledige audit voor {webshop_url}",
            "redirectUrl": f"{base_url}/bedankt?type=audit",
            "webhookUrl": f"{base_url}/webhooks/mollie",
            "metadata": {"type": "audit", "webshop_url": webshop_url, "email": email, "bedrijfsnaam": bedrijfsnaam},
        })
        return {"checkout_url": payment.checkout_url, "payment_id": payment.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


def create_monitoring_signup(base_url, email, webshop_url, bedrijfsnaam=None):
    """Stap 1 van het abonnement: klant aanmaken en de eerste betaling starten.
    Zodra deze betaling lukt (zie webhook), maken we het echte, doorlopende
    abonnement aan via create_subscription hieronder."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Betalen is nog niet actief, probeer het later opnieuw."}

    try:
        customer = client.customers.create({
            "name": webshop_url,
            "email": email,
            "metadata": {"webshop_url": webshop_url},
        })
        first_payment = customer.payments.create({
            "amount": MONITORING_PRICE,
            "description": "Krillo monitoring, eerste maand",
            "redirectUrl": f"{base_url}/bedankt?type=monitoring",
            "webhookUrl": f"{base_url}/webhooks/mollie",
            "sequenceType": "first",
            "metadata": {"type": "monitoring_first_payment", "webshop_url": webshop_url, "customer_id": customer.id, "email": email, "bedrijfsnaam": bedrijfsnaam},
        })
        return {"checkout_url": first_payment.checkout_url, "payment_id": first_payment.id, "customer_id": customer.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


def create_subscription(customer_id):
    """Stap 2, wordt aangeroepen vanuit de webhook zodra de eerste betaling is gelukt.
    Zet het echte, maandelijks terugkerende abonnement op."""
    client = get_mollie_client()
    if client is None:
        return {"error": "Mollie niet geconfigureerd."}

    try:
        customer = client.customers.get(customer_id)
        subscription = customer.subscriptions.create({
            "amount": MONITORING_PRICE,
            "interval": "1 month",
            "description": "Krillo monitoring-abonnement",
        })
        return {"subscription_id": subscription.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


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
        for customer in client.customers.list():
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


def list_recent_orders(limit=50):
    """Haalt de meest recente betaalde bestellingen op, voor het bestel-overzicht."""
    client = get_mollie_client()
    if client is None:
        return []

    orders = []
    try:
        for payment in client.payments.list(limit=limit):
            if not payment.is_paid():
                continue
            metadata = payment.metadata or {}
            orders.append({
                "id": payment.id,
                "type": metadata.get("type", "onbekend"),
                "webshop_url": metadata.get("webshop_url", "-"),
                "email": metadata.get("email", "-"),
                "amount": payment.amount.get("value") if payment.amount else "-",
                "paid_at": payment.paid_at,
                "description": payment.description,
            })
    except (MollieError, Exception):
        return []

    orders.sort(key=lambda o: o["paid_at"] or "", reverse=True)
    return orders
