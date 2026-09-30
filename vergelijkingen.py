"""De vergelijkingspagina's: Krillo naast de andere tools (stap 163, 28 september).

WAAROM DIT BESTAAT. Wie een tool zoekt, zoekt op "Otterly alternative" of "AI
visibility tool for Shopify". En wie het een AI-assistent vraagt, krijgt een
antwoord dat uit precies zulke pagina's komt. Een eerlijke vergelijking op
onze eigen site is dus bereik bij mensen die al zoeken.

REGELS DIE NOOIT LOSSEN
- Hun prijzen komen van HUN eigen prijspagina, met de datum waarop we keken en
  de link erbij. Staat een prijs daar niet (Peec toont prijzen pas na
  aanmelden), dan noemen we geen bedrag.
- Niets afkraken, niets verzinnen. Per tool staat er ook wanneer die tool de
  betere keuze is. Dat maakt de rest geloofwaardig.
- Bijwerken: pas GEKEKEN aan en loop de bedragen na. test_vergelijkingen
  waarschuwt als een pagina ouder is dan 120 dagen.
"""
GEKEKEN = "2026-09-28"

KRILLO = {
    "wat": "Measures every month whether ChatGPT and Gemini recommend your store, in a public ranking per "
           "category and country, and with Fix we make the changes in your store for you.",
    "prijs": "Free check. Watch EUR 49 a month (EUR 490 a year). Fix EUR 149 a month (EUR 1,490 a year).",
}

TOOLS = {
    "otterly": {
        "naam": "Otterly.AI",
        "bron": "https://otterly.ai/pricing",
        "wat": "Tracks how brands appear in ChatGPT, Google AI Overviews, Perplexity and Microsoft Copilot, "
               "with daily tracking of the prompts you choose.",
        "prijs": "Lite $29 a month (15 prompts), Standard $189 (100 prompts), Premium $489 (400 prompts). "
                 "15% off yearly. Free trial.",
        "voor_wie": "Marketing teams and agencies that want to track their own list of prompts across many AI "
                    "engines, every day.",
        "beter_als": "you want daily tracking of prompts you pick yourself, across four or more AI engines, "
                     "for any kind of business.",
        "krillo_anders": [
            "Built for webshops only: the buying questions come from your category, not from a list you have "
            "to write yourself.",
            "A public ranking per category and country, so you see exactly who AI names instead of you.",
            "With Fix we make the changes in your store; Otterly shows the data and you do the work.",
        ],
    },
    "peec-ai": {
        "naam": "Peec AI",
        "bron": "https://peec.ai/pricing",
        "wat": "An AI search analytics platform for brands and agencies: visibility, position and sentiment "
               "across ChatGPT, Google AI Mode and AI Overviews, Copilot, Gemini and more.",
        "prijs": "Starter (50 prompts), Pro (150) and Advanced (350), each with three AI models of your choice; "
                 "15% off yearly. Their pricing page does not show amounts before you sign up, so we do not "
                 "quote one here.",
        "voor_wie": "Brand and agency marketing teams, in many countries and languages.",
        "beter_als": "you run marketing for a brand or agency and want deep analytics across many models and "
                     "markets.",
        "krillo_anders": [
            "Made for webshops, with the buying questions shoppers in the countries we measure actually ask, in their own language.",
            "Prices on our site, and a free check without an account.",
            "With Fix we do the work in your store, not only the reporting.",
        ],
    },
    "profound": {
        "naam": "Profound",
        "bron": "https://www.tryprofound.com/pricing",
        "wat": "An enterprise platform for AI search visibility, tracking up to nine answer engines, with "
               "exports, API access and SSO.",
        "prijs": "A free 7-day trial (50 prompts, three engines); after that Enterprise at a custom price "
                 "through their sales team.",
        "voor_wie": "Large companies with a marketing team and an enterprise budget.",
        "beter_als": "you are a large brand that needs many engines, regions, SSO and a dedicated contact.",
        "krillo_anders": [
            "A fixed monthly price from EUR 49, cancel any month.",
            "No sales call: check your store for free and start the same day.",
            "Focused on webshops, with the fixes made for you on Fix.",
        ],
    },
    "athenahq": {
        "naam": "AthenaHQ",
        "bron": "https://www.athenahq.ai/pricing",
        "wat": "Tracks brand visibility across up to eleven AI models, with content recommendations and an "
               "AI agent, on a credit system.",
        "prijs": "Essential free ($25 in credits), Starter $295 a month (3,600 credits), Enterprise custom.",
        "voor_wie": "Marketing teams that want many models and content suggestions, and are fine with credits.",
        "beter_als": "you want to track many AI models and plan content with an AI agent.",
        "krillo_anders": [
            "One clear price, no credits to budget.",
            "A monthly rank in a public index for your category and country.",
            "With Fix we write the product texts and put them in your store.",
        ],
    },
    "shopify-apps": {
        "naam": "AI visibility apps on Shopify",
        # Voor zinnen als "When a Shopify app is the better choice" (enkelvoud).
        "naam_zin": "a Shopify app",
        "bron": "https://apps.shopify.com/search?q=ai%20visibility",
        "wat": "The Shopify App Store has a growing group of AI visibility apps (for example IndexGPT, "
               "ShopRank AI and Kwik GEO). Most generate files and texts for AI, many with a free plan.",
        "prijs": "Varies per app; many have a free plan and paid plans from about $10 to $50 a month. Check each "
                 "app's own listing.",
        "voor_wie": "Shopify stores that want a quick technical setup for AI, often with a free start.",
        "beter_als": "you mainly want an llms.txt file or technical tags added, and do not need to know where "
                     "you rank.",
        "krillo_anders": [
            "We measure the outcome: do ChatGPT and Gemini actually recommend you, and who do they name "
            "instead, every month.",
            "A public ranking per category and per country.",
            "With Fix we make the changes for you, on Shopify through our own app.",
        ],
    },
}
