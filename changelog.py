"""Stap 182: de changelog op /changelog (30 september 2026).

WAAROM. Een changelog laat zien dat het product leeft, en geeft elke week iets
concreets om op de LinkedIn-pagina van Krillo te delen. Alleen wat een klant
of bezoeker merkt, in gewone taal, in het Engels (de site is Engels).

REGEL: alleen wat echt live staat. Een nieuwe regel komt bovenaan en krijgt de
datum waarop hij online ging, niet de datum waarop hij bedacht werd.
Deze lijst wordt ook getest (test_changelog.py): elke link erin moet laden.
"""

# (datum, titel, tekst, link of None). Nieuwste eerst.
REGELS = [
    ("2026-10-02", "Your own questions",
     "Add the questions you care about yourself: five with Watch, fifteen with Fix. We ask them to ChatGPT and "
     "Gemini every week, only for you. Your rank in the index still comes from the same questions for every store.",
     None),
    # 2 oktober: vier goedgekeurde voorstellen uit de leeragent.
    ("2026-10-02", "Which AI robots can read each page",
     "Your Fixes page now shows, per page, whether ChatGPT search, Perplexity, Google and OpenAI's training "
     "robot may read it and actually get it. Blocked by robots.txt, a firewall or a noindex: you see which.", None),
    ("2026-10-02", "Your products in AI answers",
     "The weekly check now also looks for your products. Your overview shows which ones ChatGPT and Gemini named "
     "by name, and for which question.", None),
    ("2026-10-02", "llms.txt for Shopify and WordPress",
     "Fix now writes an llms.txt for your store: a short file that tells AI what you sell, with your main pages "
     "and products. We keep it up to date when your products change.", None),
    ("2026-10-02", "A short weekly email",
     "Paying stores get one short email a week: how often AI named you, what changed since last week, and which "
     "products were named. One click turns it off.", None),
    # 1 oktober, laat: wat er voor klanten veranderde. Kort; de details staan in het dashboard.
    ("2026-10-01", "Every week: your five key questions checked again",
     "Besides the monthly ranking, we now ask your five most important buying questions again every week. Your "
     "overview shows the result next to last week, so you see within a week whether a change works.", None),
    ("2026-10-01", "Your rank within the hour after you start",
     "New customers are added to this month's ranking of their category right away. Is your category new to us, "
     "we measure it for you first. Either way you get an email when your rank is in.", None),
    ("2026-10-01", "Per page: can AI read it?",
     "Every week we also check your product and category pages, not only your homepage. Your Fixes page lists "
     "at most three things to do per page, with ready-made text where it helps.", None),
    ("2026-10-01", "Open spots and a PDF for your web designer",
     "The Questions page now shows where AI names few stores: the quickest questions to win. And the thirteen "
     "technical checks come as a one page PDF, in the order to fix them.", None),
    # Nino liep op 1 oktober de proefwinkel op TasteWP na: alle wijzigingen stonden erin.
    ("2026-10-01", "Fix for WooCommerce and WordPress",
     "Fix now works for WooCommerce and WordPress stores as well: you connect your store with an application "
     "password you can revoke any time, we write the missing product texts, image descriptions and a questions "
     "page, and put them live. Every change can be undone.", "/#pricing"),
    ("2026-10-01", "Switch from Watch to Fix with one click",
     "On the Plan page of your dashboard: Switch to Fix. Your existing plan is changed, so there is no second "
     "payment. Fix starts the same day, and the new price applies from your next payment.", None),
    ("2026-10-01", "Your monthly report as a PDF",
     "Download a one page report from your dashboard: your rank, the change since last month, the questions you "
     "lose and who AI named instead, and what AI says about you. Easy to forward to a partner or your agency.",
     None),
    ("2026-10-01", "The category map and AI quotes in your dashboard",
     "The Ranking page of your dashboard now shows where you sit on the map of named against recommended, and "
     "what ChatGPT and Gemini say about your store, word for word.", "/demo/ranking"),
    ("2026-09-30", "A map of every category: named is not recommended",
     "Every ranking now has a map with each store as a dot: how often AI names it against how often AI recommends "
     "it. Stores low on the right are known to AI but rarely the tip. You can download the map as an image.",
     "/index"),
    ("2026-09-30", "What AI says about your store",
     "Each store page in the index now shows what ChatGPT and Gemini say about the store, word for word, and "
     "which qualities they mention: price, range, delivery, service.", "/index"),
    ("2026-09-30", "A weekly robot check for customers",
     "Every week we check whether the AI robots that find stores for shoppers may still read your store. A new "
     "theme or security plugin can shut them out without you noticing. If that happens, you get an email with "
     "the fix the same week.", None),
    ("2026-09-30", "Your change overview arrives by itself",
     "When Krillo puts approved changes into your store, you now get an email with every "
     "change, what is there now and what was there before, a couple of hours after the last one. No waiting for "
     "us to send it, and you can always put the old text back.", None),
    ("2026-09-30", "We read every store's own site before we contact it",
     "Before a store hears from us, we now read its own homepage to check that it is a store and that it sits in "
     "the right category. Stores already in a ranking are checked the same way, and a site that is not a store "
     "leaves the rankings. A limousine service ended up in a clothing ranking; that should not happen, so a site "
     "is now judged on its own words, not on its name.", "/how-we-measure"),
    ("2026-09-30", "Free supplier text check",
     "Many small stores and dropshippers use the product text of their supplier. If a dozen stores have the same "
     "words, AI has no reason to pick yours. The new free check searches a sentence from each of your first "
     "products and shows where else it appears word for word.", "/tools/supplier-text-check"),
    ("2026-09-30", "English addresses for every page",
     "How we measure, About, Terms, Withdrawal and Articles now have English web addresses. The old addresses "
     "keep working and forward to the new ones.", "/how-we-measure"),
    ("2026-09-29", "Log in with a link, no password",
     "Log in at the top right of every page. Fill in your email address and we send you the link to your "
     "dashboard. There is no password to forget.", "/login"),
    ("2026-09-29", "An example dashboard",
     "See what a store owner sees every month, with a real store from the index, before you sign up.", "/demo"),
    ("2026-09-28", "Free tools",
     "Check for free whether AI can read your store (robots.txt), whether your product data is complete, and "
     "whether your store is in the Krillo Index. No account needed.", "/tools"),
    ("2026-09-28", "Compare AI visibility tools",
     "An honest comparison with Otterly, Peec AI, Profound, AthenaHQ and the Shopify apps: their prices with a "
     "source and date, and for each tool when it is the better choice.", "/compare"),
    ("2026-09-28", "This month in the index",
     "Every month the biggest movers and the categories where AI names almost no one, for the Netherlands and "
     "Belgium.", "/news/nl"),
    ("2026-09-28", "Partner programme",
     "Agencies, freelancers and Shopify partners can sign up and earn 20 percent for twelve months on every store "
     "they bring.", "/partners"),
]


# De grootste veranderingen: alleen die gaan in het maandelijkse klantnieuws
# (klantnieuws.py). Nino, 1 oktober: "alleen de grootste veranderingen".
GROOT = {
    "Your own questions",
    "Which AI robots can read each page", "Your products in AI answers", "llms.txt for Shopify and WordPress",
    "Every week: your five key questions checked again",
    "Your rank within the hour after you start",
    "Fix for WooCommerce and WordPress",
}


def regels():
    """De regels, gegroepeerd per maand: [(maandnaam, [regel, ...])]."""
    from datetime import date
    maanden = {}
    for d, titel, tekst, link in REGELS:
        j, m, dag = (int(x) for x in d.split("-"))
        sleutel = date(j, m, 1).strftime("%B %Y")
        maanden.setdefault(sleutel, []).append(
            {"datum": d, "dag": date(j, m, dag).strftime("%-d %B"), "titel": titel, "tekst": tekst, "link": link})
    return list(maanden.items())


def laatste():
    return REGELS[0][0] if REGELS else None
