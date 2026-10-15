"""Het vermeldingenplan (stap 243, 9 oktober 2026).

Goedgekeurd door Nino op 8 oktober: "op welke review- en vergelijkingssites AI
kijkt en jij ontbreekt". De bronnenkaart (stap 178) wist al welke sites
ChatGPT en Gemini in een categorie noemen en hoe vaak. Wat ontbrak: staat de
klant er zelf, en wat moet hij precies doen om erop te komen.

Eerlijk over wat we kunnen nakijken:
- Trustpilot heeft een vast adres per winkel (trustpilot.com/review/<domein>).
  Dat kijken we echt na: bestaat de pagina, dan sta je erop.
- Bij de andere sites kan dat niet betrouwbaar zonder in te loggen of te
  zoeken. Daar zeggen we "check" met een zoeklink die precies dat laat zien,
  in plaats van te gokken.

Kost niets aan AI. Een controle wordt 7 dagen onthouden.
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

import db

DOMEIN = {
    "Trustpilot": "trustpilot.com", "Kiyoh": "kiyoh.com", "Feedback Company": "feedbackcompany.com",
    "WebwinkelKeur": "webwinkelkeur.nl", "Thuiswinkel Waarborg": "thuiswinkel.org",
    "Kieskeurig": "kieskeurig.nl", "Tweakers": "tweakers.net", "Beslist": "beslist.nl",
    "Consumentenbond": "consumentenbond.nl", "Test Aankoop": "test-aankoop.be", "Reddit": "reddit.com",
    "YouTube": "youtube.com", "Instagram": "instagram.com", "TikTok": "tiktok.com", "Facebook": "facebook.com",
    "Pinterest": "pinterest.com", "Bol": "bol.com", "Amazon": "amazon.nl", "Marktplaats": "marktplaats.nl",
    "Etsy": "etsy.com", "Zalando": "zalando.nl", "Vinted": "vinted.nl",
}

# De concrete stap per site: wat de winkelier vandaag kan doen.
STAP = {
    "Trustpilot": "Claim your free company page on business.trustpilot.com and invite your last 20 buyers to leave a review.",
    "Kiyoh": "Open a Kiyoh account and send a review invite automatically after every order.",
    "Feedback Company": "Open a Feedback Company account and send a review invite after every order.",
    "WebwinkelKeur": "Apply for the WebwinkelKeur label and show its reviews on your product pages.",
    "Thuiswinkel Waarborg": "Apply for the Thuiswinkel Waarborg (a check by Thuiswinkel.org), then show the seal on your site.",
    "Google reviews": "Claim your Google Business Profile and ask every buyer for a Google review.",
    "Kieskeurig": "Register as a shop with Kieskeurig and connect your product feed, so your products and prices show.",
    "Tweakers": "Register your shop in Tweakers Pricewatch and connect your product feed.",
    "Beslist": "Register your shop with Beslist.nl and connect your product feed.",
    "Google Shopping": "Upload your product feed to Google Merchant Center: free listings in Google Shopping.",
    "Consumentenbond": "Make sure the brands and models you sell are named on your product pages exactly as tested.",
    "Test Aankoop": "Make sure the brands and models you sell are named on your product pages exactly as tested.",
    "Bol": "Sell your best products on bol.com with a seller account, or make your own pages clearly better.",
    "Amazon": "Sell your best products on Amazon.nl, or make your own pages clearly better.",
    "Reddit": "Answer questions in relevant subreddits as yourself, without selling. AI repeats what people say there.",
    "YouTube": "Post short product videos and reviews; AI cites YouTube for 'which one should I buy'.",
}

ONTHOUD = timedelta(days=7)


def _domein(url):
    return (url or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/").split("/")[0].lower()


def _trustpilot(winkel, get=requests.get, alleen_onthouden=False):
    """'aan', 'mist' of None (niet na te kijken). Onthouden voor 7 dagen.

    alleen_onthouden: niet zelf op internet kijken (het dashboard wacht nooit
    op Trustpilot; nakijken gebeurt op de achtergrond, zie nakijken())."""
    sleutel = f"vermelding:trustpilot:{winkel}"
    try:
        eerder = json.loads(db.get_instelling(sleutel) or "null")
        if eerder and datetime.fromisoformat(eerder["op"]) > datetime.now(timezone.utc) - ONTHOUD:
            return eerder["status"]
    except (TypeError, ValueError, KeyError):
        pass
    if alleen_onthouden:
        return None
    status = None
    try:
        r = get(f"https://www.trustpilot.com/review/{winkel}", timeout=5,
                headers={"User-Agent": "Mozilla/5.0 (compatible; KrilloBot/1.0; +https://krilloai.com)"})
        if r.status_code == 200 and winkel in (getattr(r, "url", "") or "").lower():
            status = "aan"
        elif r.status_code == 404:
            status = "mist"
    except Exception as e:
        print(f"Trustpilot nakijken mislukt voor {winkel}: {e}")
    if status:
        db.zet_instelling(sleutel, json.dumps({"status": status, "op": datetime.now(timezone.utc).isoformat()}))
    return status


def nakijken(bronnen, webshop_url, get=requests.get):
    """Op de achtergrond: de sites die we echt kunnen nakijken, nakijken."""
    winkel = _domein(webshop_url)
    if winkel and any((b.get("naam") == "Trustpilot") for b in bronnen or []):
        _trustpilot(winkel, get=get)


# 16 oktober (Fix waard maken): bij Fix per site een kant-en-klaar bericht.
# Reviewsites: een bericht aan je eigen klanten (AI haalt reviews aan als bewijs).
# Vergelijkers: een aanvraag aan de site om je winkel op te nemen. Geen bericht
# waar dat niets oplevert (testorganisaties, communities, marktplaatsen).
# In de taal van je klanten: Nederlands voor NL en BE, anders Engels.
REVIEW_SITES = {"Trustpilot", "Kiyoh", "Feedback Company", "WebwinkelKeur", "Google reviews"}
VERGELIJKERS = {"Kieskeurig", "Tweakers", "Beslist"}


def bericht(naam, winkelnaam, categorie, land):
    """{"aan", "onderwerp", "tekst"} of None. [REVIEW LINK] is een plek om zelf in te vullen."""
    nl = (land or "").lower() in ("nl", "be")
    if naam in REVIEW_SITES:
        if nl:
            return {"aan": "Je klanten (een week na levering)", "onderwerp": f"Hoe bevalt je bestelling bij {winkelnaam}?",
                    "tekst": f"Hoi,\n\nBedankt voor je bestelling bij {winkelnaam}. Wil je in een minuut laten weten hoe "
                             f"het bevalt? Je review helpt andere kopers kiezen.\n\n[REVIEW LINK {naam}]\n\n"
                             f"Groet,\n{winkelnaam}"}
        return {"aan": "Your customers (a week after delivery)", "onderwerp": f"How is your order from {winkelnaam}?",
                "tekst": f"Hi,\n\nThank you for your order at {winkelnaam}. Could you take a minute to share how it is "
                         f"going? Your review helps other shoppers choose.\n\n[REVIEW LINK {naam}]\n\n"
                         f"Best,\n{winkelnaam}"}
    if naam in VERGELIJKERS:
        if nl:
            return {"aan": f"{naam} (winkeliers of partners)", "onderwerp": f"Aanmelding winkel: {winkelnaam}",
                    "tekst": f"Hallo,\n\nWij zijn {winkelnaam}, een webwinkel in {categorie.lower()}. Graag staan wij "
                             f"met onze producten op {naam}. Wij kunnen een productfeed aanleveren met namen, prijzen en "
                             f"voorraad. Wat is de volgende stap?\n\nMet vriendelijke groet,\n{winkelnaam}"}
        return {"aan": f"{naam} (shop or partner team)", "onderwerp": f"Shop listing request: {winkelnaam}",
                "tekst": f"Hello,\n\nWe are {winkelnaam}, an online store in {categorie.lower()}. We would like our "
                         f"products listed on {naam}. We can provide a product feed with names, prices and stock. "
                         f"What is the next step?\n\nKind regards,\n{winkelnaam}"}
    return None


def plan(bronnen, webshop_url, maximaal=6, get=requests.get, alleen_onthouden=True, fix=None):
    """fix: {"winkelnaam", "categorie", "land"} bij een Fix-klant: dan per site ook het bericht."""
    """[{"naam", "soort_en", "aantal", "van", "status", "check", "stap"}], vaakst genoemd eerst.

    status: "aan" (nagekeken, je staat erop), "mist" (nagekeken, je staat er niet),
    of "check" (niet betrouwbaar na te kijken; "check" is dan een zoeklink)."""
    winkel = _domein(webshop_url)
    uit = []
    for b in (bronnen or [])[:maximaal]:
        naam = b.get("naam") or ""
        status, check = "check", None
        if naam == "Trustpilot" and winkel:
            status = _trustpilot(winkel, get=get, alleen_onthouden=alleen_onthouden) or "check"
        if status == "check":
            site = DOMEIN.get(naam)
            if site and winkel:
                check = "https://www.google.com/search?q=" + quote(f'site:{site} "{winkel}"')
        uit.append({"naam": naam, "soort_en": b.get("soort_en") or "", "aantal": b.get("aantal") or 0,
                    "van": b.get("van") or 0, "status": status, "check": check,
                    "stap": STAP.get(naam) or b.get("advies") or "",
                    "bericht": bericht(naam, fix["winkelnaam"], fix["categorie"], fix["land"]) if fix else None})
    return uit
