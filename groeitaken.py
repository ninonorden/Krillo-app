"""Groeitaken voor Nino: bezoek en klanten, elke werkdag een uur (14 oktober 2026).

WAAROM DIT BESTAAT. Nino: "de dingen van het ochtendbericht zorgen niet perse
voor meer klanten en ik heb dat altijd binnen 5 minuten gedaan. Ik moet meer
taken om de dag te vullen. We moeten naar 300 bezoekers per dag." De agents
doen de koude mail; wat zij NIET kunnen is een mens die zich ergens aanmeldt,
een bericht in een groep plaatst of een redactie mailt. Dat levert links van
buiten (wat Google nodig heeft om krilloai.com te vertrouwen) en bezoekers die
zelf komen kijken.

Elke taak heeft de tekst al klaar, in de taal van de plek. Het ochtendbericht
laat elke werkdag de volgende DAG_MAX open taken zien; op /admin/groei staan ze
allemaal met een knop "Gedaan". Volgorde = wat het snelst bezoek of links
oplevert eerst.

Regels die in elke tekst gelden: geen verzonnen klanten of cijfers, de index
en de gratis check als reden om te kijken (niet "koop"), geen lange streepjes,
en in groepen alleen waar het mag (de regels van de groep eerst lezen).
"""
import db

DAG_MAX = 3
SLEUTEL = "groeitaak_gedaan:"

SITE = "https://krilloai.com"
KORT_EN = ("Krillo shows online stores which shops ChatGPT and Gemini recommend in their category, "
           "why they lose, and writes the fixes. Free check, no account.")
LANG_EN = ("Shoppers now ask ChatGPT and Gemini where to buy. Krillo asks the same buying questions "
           "every month for every store in a category and publishes the ranking: who gets named, who "
           "gets recommended, and who is missing. Store owners see their own rank, the questions they "
           "lose and who AI named instead, and get the text to fix it. Live for the Netherlands and "
           "Belgium; Shopify app available. Free check at krilloai.com, no account needed.")

TAKEN = [
    {"id": "ph-profiel", "titel": "Product Hunt: maak het profiel van Krillo aan", "minuten": 20,
     "link": "https://www.producthunt.com/posts/new",
     "stappen": "Log in met Google. Vul in: naam Krillo, tagline (hieronder), link krilloai.com, "
                "categorie Marketing en E-commerce. Plaatjes: gebruik 0_feature.png en de vijf schermen "
                "uit krillo-listing.zip. Zet de lancering op een dinsdag over minstens een week (stap 139).",
     "tekst": "Tagline: See which stores ChatGPT recommends in your category\n\n" + LANG_EN},
    {"id": "taaft", "titel": "There's An AI For That: meld Krillo aan", "minuten": 10,
     "link": "https://theresanaiforthat.com/submit/",
     "stappen": "Gratis aanmelding. Kies de taak 'AI search visibility' of 'SEO'.",
     "tekst": KORT_EN},
    {"id": "alternativeto", "titel": "AlternativeTo: Krillo als alternatief voor Peec AI en Profound", "minuten": 15,
     "link": "https://alternativeto.net/",
     "stappen": "Maak een account, klik 'Suggest new application', vul Krillo in, en voeg het daarna "
                "toe als alternatief bij Peec AI en bij Profound. Wie daar een alternatief zoekt, is "
                "precies onze klant.",
     "tekst": KORT_EN + "\n\nUnlike global AI-SEO tools, Krillo is built for online stores: a public "
                        "ranking per category and fixes written for your products."},
    {"id": "saashub", "titel": "SaaSHub: meld Krillo aan", "minuten": 10,
     "link": "https://www.saashub.com/submit", "stappen": "Gratis. Categorie: SEO Tools.", "tekst": KORT_EN},
    {"id": "futurepedia", "titel": "Futurepedia: meld Krillo aan", "minuten": 10,
     "link": "https://www.futurepedia.io/submit-tool",
     "stappen": "Kies de gratis aanmelding als die er is; betaal niet.", "tekst": KORT_EN},
    {"id": "g2", "titel": "G2: gratis profiel claimen", "minuten": 15,
     "link": "https://www.g2.com/products/new",
     "stappen": "Gratis profiel. Categorie: AI Search Visibility of SEO Software. Later vragen we "
                "klanten om een review daar.", "tekst": LANG_EN},
    {"id": "fb-groepen", "titel": "Facebook: word lid van 3 groepen voor Nederlandse webshophouders", "minuten": 15,
     "link": "https://www.facebook.com/search/groups/?q=webshop%20ondernemers",
     "stappen": "Zoek op 'webshop ondernemers', 'Shopify Nederland' en 'e-commerce Nederland'. Kies "
                "groepen met veel leden en recente berichten. Lees de regels: veel groepen staan "
                "promotie alleen op een vaste dag toe. Nog niets plaatsen; dat is de volgende taak.",
     "tekst": ""},
    {"id": "fb-post", "titel": "Facebook: plaats de ranglijst-post in een groep (waar het mag)", "minuten": 15,
     "link": SITE + "/index/nl",
     "stappen": "Kies uit /index/nl een categorie die bij de groep past. Plaats de tekst, met de "
                "link naar die ranglijst. Reageer op elke vraag dezelfde dag.",
     "tekst": "Ik heb ChatGPT en Gemini dertig vragen gesteld die kopers stellen, per categorie, en "
              "bijgehouden welke webshops ze noemen. Bij veel categorieen noemt AI maar een handvol "
              "winkels en de rest nooit. De ranglijsten staan openbaar, je kunt je eigen winkel "
              "opzoeken: [link]\n\nBenieuwd of jullie dit herkennen: merken jullie al bezoekers of "
              "bestellingen via ChatGPT?"},
    {"id": "reddit-shopify", "titel": "Reddit: help in r/shopify en r/ecommerce (zonder reclame)", "minuten": 20,
     "link": "https://www.reddit.com/r/shopify/search/?q=chatgpt",
     "stappen": "Zoek naar recente vragen over ChatGPT, AI search of 'AI visibility'. Geef een echt "
                "antwoord (wat AI leest: duidelijke producttekst, FAQ, reviews op andere sites). "
                "Alleen een link als iemand vraagt hoe je het meet. Drie antwoorden.",
     "tekst": "What we see measuring this every month: AI mostly names stores that other sites "
              "already mention (comparison articles, review sites, forums) and stores whose product "
              "pages answer the question directly. Short supplier descriptions copied by ten other "
              "shops almost never get named."},
    {"id": "ih-post", "titel": "Indie Hackers: post over wat we leerden van 2000 winkels", "minuten": 25,
     "link": "https://www.indiehackers.com/new-post",
     "stappen": "Een eerlijk verhaal, geen reclame. Link naar de index onderaan.",
     "tekst": "Title: I asked ChatGPT and Gemini 30 buying questions per category for 2,000 online stores\n\n"
              "What surprised me: in most categories AI names only a handful of stores, and being "
              "named is not the same as being recommended. We publish the rankings openly (Netherlands "
              "and Belgium for now): " + SITE + "/index\n\nHappy to answer questions about how we "
                                                "measure it."},
    {"id": "linkedin-groepen", "titel": "LinkedIn: word lid van 3 groepen over e-commerce in NL", "minuten": 10,
     "link": "https://www.linkedin.com/search/results/groups/?keywords=e-commerce%20nederland",
     "stappen": "Met de bedrijfspagina kun je niet in groepen; doe het met je eigen profiel. Kies "
                "groepen met recente berichten.", "tekst": ""},
    {"id": "emerce-gastblog", "titel": "Frankwatching of Emerce: stuur een gastblog-voorstel", "minuten": 20,
     "link": "https://www.frankwatching.com/schrijven-voor-frankwatching/",
     "stappen": "Stuur het voorstel naar de redactie. Een gastblog op zo'n site is een link die Google "
                "zwaar laat wegen, plus lezers die precies onze doelgroep zijn.",
     "tekst": "Onderwerp: Voorstel gastblog: welke webshops raadt ChatGPT aan, en waarom die?\n\n"
              "Hallo redactie,\n\nWij meten elke maand per productcategorie welke webshops ChatGPT en "
              "Gemini noemen als een koper vraagt waar hij iets moet kopen. In veel categorieen noemt AI "
              "maar een paar winkels. Ik wil daar een stuk over schrijven met de echte cijfers uit onze "
              "meting: welke soort winkels AI noemt, wat ze gemeen hebben, en wat een webshop vandaag "
              "kan doen. Geen verkooppraatje.\n\nDe ranglijsten staan openbaar: " + SITE + "/index/nl\n\n"
              "Mag ik een opzet sturen?\n\nGroet,\nKrillo"},
    {"id": "twinkle", "titel": "Twinkle en Ecommerce News: stuur de cijfers als nieuws", "minuten": 15,
     "link": "https://www.twinklemagazine.nl/contact/",
     "stappen": "Zelfde verhaal, korter, als nieuws. Ecommerce News heeft een tipadres op de site.",
     "tekst": "Onderwerp: Cijfers: welke webshops ChatGPT aanraadt, per categorie\n\nKrillo meet elke "
              "maand voor Nederland en Belgie welke webshops ChatGPT en Gemini noemen op koopvragen. De "
              "ranglijsten per categorie staan openbaar op " + SITE + "/index/nl. Interessant voor een "
              "bericht? Ik stuur graag de opvallendste uitkomsten."},
    {"id": "shopify-naam", "titel": "Shopify: zet de app-naam op 'Krillo: AI Search Visibility'", "minuten": 5,
     "link": "https://partners.shopify.com",
     "stappen": "Partner-dashboard, Apps, Krillo, Manage listing, App name. De naam weegt het zwaarst "
                "in de zoekfunctie van de App Store; nu staat er alleen 'Krillo' en daar zoekt niemand op. "
                "Maximaal 30 tekens.", "tekst": "Krillo: AI Search Visibility"},
    {"id": "shopify-zoekwoorden", "titel": "Shopify: zoektermen bijwerken", "minuten": 5,
     "link": "https://partners.shopify.com",
     "stappen": "Manage listing, Search terms. Vijf termen.",
     "tekst": "AI visibility\nChatGPT SEO\nAI search\nGEO\nLLM SEO"},
    {"id": "badge-mail", "titel": "Mail 5 winkels uit de top 3 van een ranglijst met hun badge", "minuten": 20,
     "link": SITE + "/admin/benadering",
     "stappen": "Winkels die bovenaan staan zijn trots en plaatsen de badge: een link naar de index. "
                "De badgeagent doet dit al voor een deel; kijk wie nog niets kreeg.",
     "tekst": ""},
    {"id": "bureaus-mail", "titel": "Partners: mail 3 webshopbouwers (bureaus) uit /admin/bureaus", "minuten": 20,
     "link": SITE + "/admin/bureaus",
     "stappen": "Bureaus hebben tien tot honderd webshops als klant. De mail staat per bureau klaar.",
     "tekst": ""},
]


def gedaan(taak_id):
    return (db.get_instelling(SLEUTEL + taak_id) or "") == "ja"


def zet_gedaan(taak_id, aan=True):
    if any(t["id"] == taak_id for t in TAKEN):
        db.zet_instelling(SLEUTEL + taak_id, "ja" if aan else "")
        return True
    return False


def open_taken():
    return [t for t in TAKEN if not gedaan(t["id"])]


def voor_vandaag(basis_url, maximaal=DAG_MAX):
    """Voor groeiagent.dagtaken: de volgende open taken, met een link naar de uitleg."""
    return [{"tekst": t["titel"], "minuten": t["minuten"],
             "link": f"{basis_url.rstrip('/')}/admin/groei#{t['id']}"} for t in open_taken()[:maximaal]]
