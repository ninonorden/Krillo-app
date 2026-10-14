"""Drie Nederlandse pagina's voor webshophouders (14 oktober 2026, stap 379).

WAAROM. Search Console liet zien dat krilloai.com bijna alleen gevonden wordt
op de naam "krillo". Webshophouders in Nederland en Belgie zoeken in het
Nederlands ("webshop vindbaar in ChatGPT"), en daar is veel minder concurrentie
dan op de Engelse woorden. Elke pagina beantwoordt een zoekvraag echt, met wat
wij elke maand meten, en verwijst naar de gratis check en de ranglijsten.

Regels: geen verzonnen cijfers of klanten (de enige cijfers komen live uit de
index), geen beloftes over een plek in AI, geen lange streepjes.
"""
import json

PAGINAS = [
    {
        "slug": "webshop-vindbaar-in-chatgpt",
        "titel": "Webshop vindbaar in ChatGPT: zo zorg je dat AI je noemt | Krillo",
        "omschrijving": "Hoe word je als webshop vindbaar in ChatGPT en Gemini? Wat AI leest, waarom de ene "
                        "winkel genoemd wordt en de andere niet, en hoe je dat gratis nakijkt.",
        "kop": "Je webshop vindbaar maken in ChatGPT",
        "intro": "Steeds meer kopers vragen ChatGPT of Gemini waar ze iets moeten kopen, in plaats van zelf "
                 "te zoeken. Het antwoord noemt een paar winkels. Hier lees je wat bepaalt of de jouwe "
                 "erbij staat.",
        "blokken": [
            {"kop": "Wat er gebeurt als een koper het aan AI vraagt",
             "tekst": ["Een koper typt bijvoorbeeld \"waar koop ik een goede houten speelkeuken online\". "
                       "ChatGPT zoekt, leest een handvol pagina's en schrijft een antwoord met een paar "
                       "winkels erin. Wie daar niet staat, bestaat voor die koper niet. Er is geen tweede "
                       "pagina met resultaten.",
                       "Wij stellen die vragen elke maand voor elke categorie in de "
                       "<a href=\"/index\">Krillo Index</a> en houden bij welke webshops genoemd worden. "
                       "In de meeste categorieen noemt AI maar een klein deel van de winkels."]},
            {"kop": "Waar AI op let",
             "tekst": ["<strong>Andere sites die over je schrijven.</strong> Vergelijkingsartikelen, "
                       "reviewsites, fora en lijstjes. AI noemt vooral winkels die al op andere plekken "
                       "genoemd worden.",
                       "<strong>Productteksten die de vraag beantwoorden.</strong> Een tekst die de "
                       "leverancier ook aan tien andere winkels gaf, maakt jouw winkel niet anders. Een "
                       "eigen tekst met materiaal, maat, voor wie en waarom wel.",
                       "<strong>Een site die AI kan lezen.</strong> Laat je robots.txt de robots van "
                       "OpenAI, Google en Perplexity toe? Staat de tekst in de pagina zelf, of pas na het "
                       "laden van een script? Heb je een pagina met veelgestelde vragen?"]},
            {"kop": "Genoemd is nog niet aanbevolen",
             "tekst": ["Er is een verschil tussen \"je kunt ook kijken bij X\" en \"koop het bij X\". "
                       "Alleen het tweede levert een klant op. Daarom tellen wij allebei apart: hoe vaak "
                       "AI je noemt, en hoe vaak AI je echt aanraadt."]},
            {"kop": "Zo kijk je het na",
             "tekst": ["Vul je webshop in bij de <a href=\"/#scan\">gratis check</a>. Je ziet je plek in je "
                       "categorie, welke winkels AI in jouw plaats noemt, en dertien punten op je eigen "
                       "site die AI helpen of tegenhouden. Geen account nodig."]},
        ],
        "vragen": [
            {"vraag": "Kan ik betalen om in ChatGPT genoemd te worden?",
             "antwoord": "Nee. Er zijn geen advertenties in de antwoorden van ChatGPT en Gemini waar je een "
                         "plek kunt kopen. Wat je wel kunt doen: je eigen site goed leesbaar maken en "
                         "zorgen dat andere sites over je schrijven."},
            {"vraag": "Hoe snel zie ik verschil?",
             "antwoord": "Dat verschilt per categorie en niemand kan het beloven. Wij meten elke maand "
                         "opnieuw, en met Watch elke week je vijf belangrijkste vragen, zodat je ziet of "
                         "een wijziging opgepikt wordt."},
        ],
    },
    {
        "slug": "ai-seo-voor-webshops",
        "titel": "AI SEO voor webshops: wat het is en wat je vandaag kunt doen | Krillo",
        "omschrijving": "AI SEO (ook GEO genoemd) voor webshops in gewone taal: het verschil met gewone "
                        "SEO, wat ChatGPT en Gemini lezen, en een lijst met wat je vandaag kunt doen.",
        "kop": "AI SEO voor webshops, in gewone taal",
        "intro": "AI SEO, of GEO, is ervoor zorgen dat AI-assistenten zoals ChatGPT en Gemini je winkel "
                 "noemen als een koper om advies vraagt. Het lijkt op gewone SEO, maar de uitkomst is anders.",
        "blokken": [
            {"kop": "Het verschil met gewone SEO",
             "tekst": ["Bij Google wil je hoog in een lijst van tien resultaten. Bij AI is er geen lijst: "
                       "er is een antwoord met een paar namen. Je staat erin of niet.",
                       "Veel van het werk overlapt: een snelle site, duidelijke teksten, goede "
                       "productinformatie. Maar AI let meer op wat andere sites over je zeggen en op "
                       "teksten die een vraag direct beantwoorden."]},
            {"kop": "Wat je vandaag kunt doen",
             "tekst": ["1. Kijk in je robots.txt of GPTBot, OAI-SearchBot, Google-Extended en "
                       "PerplexityBot niet geblokkeerd worden.",
                       "2. Vervang de leverancierstekst bij je belangrijkste producten door een eigen "
                       "tekst: voor wie, waarom, materiaal, maat.",
                       "3. Maak een pagina met veelgestelde vragen over levering, retour en advies.",
                       "4. Geef afbeeldingen een beschrijving (alt-tekst).",
                       "5. Zoek de vergelijkingsartikelen in je categorie en vraag of je erbij mag."]},
            {"kop": "Meten in plaats van gokken",
             "tekst": ["Zonder meting weet je niet of het werkt. De <a href=\"/index\">Krillo Index</a> "
                       "laat per categorie zien welke webshops AI noemt, met de echte koopvragen erbij. "
                       "Zo zie je wie het in jouw categorie goed doet, en kun je kijken wat zij anders doen."]},
        ],
        "vragen": [
            {"vraag": "Is AI SEO hetzelfde als GEO?",
             "antwoord": "Ja, dat zijn twee namen voor hetzelfde: generative engine optimisation, "
                         "optimaliseren voor antwoorden van AI in plaats van zoekresultaten."},
            {"vraag": "Moet ik een llms.txt hebben?",
             "antwoord": "Het kan geen kwaad en het is snel gedaan, maar het is geen wondermiddel. "
                         "Belangrijker zijn leesbare productpagina's en vermeldingen op andere sites."},
        ],
    },
    {
        "slug": "raadt-chatgpt-mijn-webshop-aan",
        "titel": "Raadt ChatGPT mijn webshop aan? Zo zie je het | Krillo",
        "omschrijving": "Wil je weten of ChatGPT en Gemini jouw webshop aanraden? Zo kijk je het na, wat "
                        "de uitkomst betekent, en wat je doet als je niet genoemd wordt.",
        "kop": "Raadt ChatGPT mijn webshop aan?",
        "intro": "Je kunt het zelf proberen: vraag ChatGPT waar je iets uit jouw assortiment moet kopen. "
                 "Maar een vraag zegt weinig. Het antwoord verschilt per vraag, per dag en per assistent.",
        "blokken": [
            {"kop": "Waarom een vraag niet genoeg is",
             "tekst": ["Vraag je het een keer, dan zie je een momentopname. Kopers stellen tientallen "
                       "varianten: goedkoop, snel geleverd, duurzaam, voor beginners. Bij de ene vraag sta "
                       "je erin, bij de andere niet."]},
            {"kop": "Hoe wij het meten",
             "tekst": ["Wij stellen elke maand per categorie dezelfde set koopvragen aan ChatGPT en "
                       "Gemini, in de taal van het land, en tellen per webshop bij hoeveel vragen hij "
                       "genoemd wordt en bij hoeveel hij echt aangeraden wordt. Iedereen in de categorie "
                       "krijgt dezelfde vragen, dus de ranglijst is eerlijk en na te kijken.",
                       "De ranglijsten staan openbaar in de <a href=\"/index\">Krillo Index</a>. Zoek je "
                       "categorie en kijk of je erin staat."]},
            {"kop": "Je wordt niet genoemd. Wat nu?",
             "tekst": ["Kijk eerst wie wel genoemd wordt en wat die winkels anders doen: worden ze op "
                       "andere sites genoemd, hebben ze eigen productteksten, een vragenpagina? De "
                       "<a href=\"/#scan\">gratis check</a> laat zien bij welke vragen je verliest en aan wie."]},
        ],
        "vragen": [
            {"vraag": "Is de check echt gratis?",
             "antwoord": "Ja. Geen account en geen betaalgegevens. Je betaalt pas als je elke maand wilt "
                         "meten (Watch) of wilt dat wij de wijzigingen maken (Fix)."},
            {"vraag": "Mijn categorie staat er niet tussen.",
             "antwoord": "Doe de check toch: we zetten je winkel in de index en meten je categorie zodra "
                         "er genoeg winkels in zitten."},
        ],
    },
]

PER_SLUG = {p["slug"]: p for p in PAGINAS}


def faq_ld(pagina):
    """De vragen als gestructureerde gegevens voor Google (FAQPage). Een dict:
    het sjabloon zet hem met tojson in de pagina (veilig, test_gestructureerde_gegevens)."""
    return ({
        "@context": "https://schema.org", "@type": "FAQPage", "inLanguage": "nl",
        "mainEntity": [{"@type": "Question", "name": v["vraag"],
                        "acceptedAnswer": {"@type": "Answer", "text": v["antwoord"]}} for v in pagina["vragen"]],
    })
