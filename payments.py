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
MONITORING_PRICE = {"currency": "EUR", "value": "39.00"}


def get_mollie_client():
    api_key = os.environ.get("MOLLIE_API_KEY")
    if not api_key:
        return None
    client = Client()
    client.set_api_key(api_key)
    return client


def create_audit_payment(base_url, webshop_url):
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
            "metadata": {"type": "audit", "webshop_url": webshop_url},
        })
        return {"checkout_url": payment.checkout_url, "payment_id": payment.id}
    except (MollieError, Exception) as e:
        return {"error": str(e)}


def create_monitoring_signup(base_url, email, webshop_url):
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
            "metadata": {"type": "monitoring_first_payment", "webshop_url": webshop_url, "customer_id": customer.id},
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
        return {
            "status": payment.status,
            "is_paid": payment.is_paid(),
            "metadata": payment.metadata,
        }
    except (MollieError, Exception):
        return None
