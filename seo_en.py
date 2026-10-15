"""Engelse gidsen voor winkeliers, onder /guides/ (15 oktober 2026).

WAAROM. Nino: "we hebben bijna geen traffic, de Shopify App Store heeft
miljoenen apps." Een winkelier die "how to get my Shopify store recommended by
ChatGPT" zoekt, vindt nu geen pagina van ons. Deze gidsen beantwoorden precies
die zoekvragen, met wat wij elke maand meten, en sturen door naar de gratis
check, de ranglijsten en (voor Shopify) de App Store. Engels, zoals de hele
site (de Nederlandse pagina's van 14 oktober zijn op 15 oktober weggehaald).

Regels: geen verzonnen cijfers of klanten, geen beloftes over een plek in AI,
geen lange streepjes. Het enige cijfer komt live uit de index.
"""

PAGINAS = [
    {
        "slug": "shopify-store-in-chatgpt",
        "shopify": True,
        "titel": "How to get your Shopify store recommended by ChatGPT | Krillo",
        "omschrijving": "Why ChatGPT and Gemini name some Shopify stores and not others, what you can change "
                        "in your store, and how to check where you stand for free.",
        "kop": "How to get your Shopify store recommended by ChatGPT",
        "intro": "More shoppers ask ChatGPT or Gemini where to buy instead of searching. The answer names a "
                 "few stores. This is what decides whether your Shopify store is one of them.",
        "blokken": [
            {"kop": "What happens when a shopper asks AI",
             "tekst": ["A shopper types something like \"where can I buy a good wooden play kitchen online\". "
                       "The assistant searches, reads a handful of pages and writes an answer with a few "
                       "stores in it. There is no second page of results.",
                       "We ask those questions every month for every category in the "
                       "<a href=\"/index\">Krillo Index</a> and record which stores are named."]},
            {"kop": "Five things to check in your Shopify store",
             "tekst": ["<strong>1. Can AI read your product pages?</strong> Open a product page with "
                       "JavaScript off. If the title, price and description are gone, an AI crawler sees "
                       "the same empty page. Most Shopify themes are fine; heavy page builders sometimes are not.",
                       "<strong>2. Are AI crawlers allowed?</strong> Shopify's default robots.txt allows them, "
                       "but apps and edits can change it. Check that GPTBot, OAI-SearchBot and Google-Extended "
                       "are not blocked.",
                       "<strong>3. Do your product texts answer the question?</strong> Supplier descriptions "
                       "are on dozens of other stores. Write your own: material, size, who it is for, and "
                       "why yours and not another.",
                       "<strong>4. Product facts as structured data.</strong> Price, availability, brand and "
                       "reviews in the product schema help AI read the page correctly.",
                       "<strong>5. Being named elsewhere.</strong> AI mostly names stores that comparison "
                       "articles, review sites and forums already mention. Find out which sites AI cites in "
                       "your category and get on them."]},
            {"kop": "Doing it inside Shopify",
             "tekst": ["The Krillo app shows your rank in your category, the buying questions you lose and "
                       "who AI names instead, right in your Shopify admin. It writes the missing product "
                       "facts and FAQ answers, you see every change first, and one click undoes it. The first "
                       "changes are free."]},
        ],
        "vragen": [
            {"vraag": "Does Shopify block ChatGPT?",
             "antwoord": "Not by default. Shopify's standard robots.txt allows the main AI crawlers. Apps or "
                         "custom edits can change that, so it is worth checking once."},
            {"vraag": "Do I need a separate app for this?",
             "antwoord": "No. Everything on this page can be done by hand. An app saves time and measures "
                         "whether it worked."},
            {"vraag": "How fast does it change?",
             "antwoord": "AI answers move when the sources they read change. Expect weeks, not days, and "
                         "measure monthly with the same questions."},
        ],
    },
    {
        "slug": "ai-visibility-for-online-stores",
        "titel": "AI visibility for online stores: what it is and how to measure it | Krillo",
        "omschrijving": "What AI visibility means for a webshop, how ChatGPT and Gemini pick stores, and how "
                        "to measure your own visibility with real buying questions.",
        "kop": "AI visibility for online stores",
        "intro": "AI visibility is how often an assistant like ChatGPT or Gemini names your store when "
                 "shoppers ask where to buy. It is measured with real buying questions, not keywords.",
        "blokken": [
            {"kop": "Why it is different from SEO",
             "tekst": ["In Google you can be number 7 and still get clicks. In an AI answer there are three "
                       "to five stores, and the rest do not exist for that shopper.",
                       "AI also reads differently: it leans on what other sites say about you, and on product "
                       "pages it can read and quote."]},
            {"kop": "How to measure it",
             "tekst": ["Take the questions a buyer in your category really asks. Ask them in ChatGPT and "
                       "Gemini, several times, and count in how many answers your store is named, and whether "
                       "it is recommended or only mentioned.",
                       "That is what the <a href=\"/index\">Krillo Index</a> does every month per category, "
                       "for every store in the category, so you see your rank and who is above you."]},
            {"kop": "What moves it",
             "tekst": ["Being named on the comparison and review sites AI cites, product texts that answer "
                       "the question, FAQ answers in the shopper's words, and a site AI can read."]},
        ],
        "vragen": [
            {"vraag": "Is AI visibility the same as GEO?",
             "antwoord": "Mostly. GEO (generative engine optimization) is the work; AI visibility is the "
                         "result you measure."},
            {"vraag": "Which assistants matter for shoppers?",
             "antwoord": "ChatGPT has the most users; Gemini grows through Google. We measure both."},
        ],
    },
    {
        "slug": "how-chatgpt-picks-stores",
        "titel": "How ChatGPT picks which stores to recommend | Krillo",
        "omschrijving": "What we see every month when we ask ChatGPT and Gemini where to buy: which sources "
                        "they read, why some stores are named and others are not.",
        "kop": "How ChatGPT picks which stores to recommend",
        "intro": "Every month we ask ChatGPT and Gemini hundreds of real buying questions and record which "
                 "stores they name and which sources they cite. This is what we see.",
        "blokken": [
            {"kop": "It searches, then summarises",
             "tekst": ["For a buying question the assistant usually searches the web first, reads a few "
                       "pages (often comparison articles, review sites and large retailers) and names the "
                       "stores those pages mention."]},
            {"kop": "Named is not the same as recommended",
             "tekst": ["Some stores appear in many answers but are never the tip. Others are named less "
                       "often but recommended every time. The difference is usually what the sources say "
                       "about them: a clear reason to choose that store."]},
            {"kop": "The same question, a different answer",
             "tekst": ["Answers vary between runs. That is why one check proves little and we count over "
                       "many questions and runs, per category, per month."]},
        ],
        "vragen": [
            {"vraag": "Can I pay to be recommended by ChatGPT?",
             "antwoord": "Not in the organic answer. Being named comes from what the assistant reads about you."},
            {"vraag": "Does a bigger store always win?",
             "antwoord": "No. In many categories a specialist store is named before a large marketplace, "
                         "because the sources say it is the specialist."},
        ],
    },
]

PER_SLUG = {p["slug"]: p for p in PAGINAS}


def faq_ld(pagina):
    return {
        "@context": "https://schema.org", "@type": "FAQPage", "inLanguage": "en",
        "mainEntity": [{"@type": "Question", "name": v["vraag"],
                        "acceptedAnswer": {"@type": "Answer", "text": v["antwoord"]}} for v in pagina["vragen"]],
    }
