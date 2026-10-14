"""Bestellingen uit AI-assistenten, uit de eigen Shopify-orders (14 oktober 2026, stap 375).

WAAROM. Nino: "kunnen we bewijzen dat de veranderingen van Krillo leiden naar
verkoop? Dit is het belangrijkste voor mensen." Eerlijk: dat EEN wijziging tot
EEN verkoop leidt, kan niemand bewijzen. Wel kunnen we per maand laten zien
hoeveel bestellingen en omzet er binnenkwamen van kopers die via ChatGPT,
Gemini, Perplexity, Copilot of Claude op de winkel kwamen, naast de plek en de
wijzigingen. Op de site doet de pixel dat al (aiverkeer.py); dit is hetzelfde
voor Shopify, uit de orders van de winkel zelf, zonder dat hij iets invult.

WAT ER NODIG IS. Het recht read_orders. Bestellingen zijn bij Shopify
"beschermde klantgegevens": dat recht vraag je aan in het Partner-dashboard en
Shopify keurt het. Tot dan doet dit niets (heeft_recht is False). Wij lezen
alleen de herkomst en het bedrag van een bestelling, nooit naam, adres of mail.

HOE. Een keer per dag (wachtklok) per winkel met het recht: de orders van de
laatste 90 dagen, met customerJourneySummary (de eerste en laatste bezoek van
de koper: verwijzer, bron, utm). Per maand opgeteld en als instelling bewaard,
zodat een paginaweergave nooit Shopify hoeft te vragen.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import db

AI_BRONNEN = re.compile(r"chatgpt\.com|chat\.openai\.com|openai|perplexity\.ai|gemini\.google|bard\.google|"
                        r"copilot\.microsoft|bing\.com/chat|claude\.ai|you\.com|phind\.com", re.I)
UTM_AI = re.compile(r"^(chatgpt(\.com)?|openai|perplexity|gemini|copilot|claude)$", re.I)

VRAAG = """
query($cursor: String, $zoek: String!) {
  orders(first: 100, after: $cursor, query: $zoek, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      createdAt
      currentTotalPriceSet { shopMoney { amount currencyCode } }
      customerJourneySummary {
        firstVisit { referrerUrl source utmParameters { source } }
        lastVisit { referrerUrl source utmParameters { source } }
      }
    }
  }
}"""


def _sleutel(webshop_url):
    return "shopify_ai:" + (webshop_url or "").strip().lower()[:200]


def heeft_recht(rechten):
    return "read_orders" in (rechten or "")


def is_ai(bezoek):
    """Kwam deze koper uit een AI-assistent? Op verwijzer, bron of utm_source."""
    if not bezoek:
        return False
    teksten = [bezoek.get("referrerUrl") or "", bezoek.get("source") or ""]
    utm = ((bezoek.get("utmParameters") or {}).get("source") or "").strip()
    return any(AI_BRONNEN.search(t) for t in teksten) or bool(UTM_AI.match(utm))


def tel(orders):
    """{maand: {"orders": n, "omzet": bedrag}} voor de orders uit AI."""
    uit = {}
    for o in orders or []:
        reis = o.get("customerJourneySummary") or {}
        if not (is_ai(reis.get("firstVisit")) or is_ai(reis.get("lastVisit"))):
            continue
        maand = (o.get("createdAt") or "")[:7]
        if not re.match(r"^20\d\d-\d\d$", maand):
            continue
        bedrag = float((((o.get("currentTotalPriceSet") or {}).get("shopMoney") or {}).get("amount")) or 0)
        vak = uit.setdefault(maand, {"orders": 0, "omzet": 0.0})
        vak["orders"] += 1
        vak["omzet"] = round(vak["omzet"] + bedrag, 2)
    return uit


def haal_op(winkel, sleutel, graphql, dagen=90, max_paginas=10):
    """Alle orders van de laatste `dagen`. graphql(winkel, sleutel, vraag, variabelen) -> {"gelukt", "gegevens"}."""
    sinds = (datetime.now(timezone.utc) - timedelta(days=dagen)).strftime("%Y-%m-%d")
    alles, cursor = [], None
    for _ in range(max_paginas):
        r = graphql(winkel, sleutel, VRAAG, {"cursor": cursor, "zoek": f"created_at:>={sinds}"})
        if not r.get("gelukt"):
            return None
        blok = ((r.get("gegevens") or {}).get("orders") or {})
        alles += blok.get("nodes") or []
        info = blok.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        cursor = info.get("endCursor")
    return alles


def ververs(webshop_url, winkel, sleutel, graphql):
    """Haalt op, telt en bewaart. Geeft de telling terug, of None bij een fout."""
    orders = haal_op(winkel, sleutel, graphql)
    if orders is None:
        return None
    telling = tel(orders)
    db.zet_instelling(_sleutel(webshop_url), json.dumps(telling))
    return telling


def per_maand(webshop_url):
    """Wat de laatste verversing vond: {maand: {"orders", "omzet"}}. Leeg als er niets is."""
    try:
        return json.loads(db.get_instelling(_sleutel(webshop_url)) or "{}")
    except (ValueError, TypeError):
        return {}
