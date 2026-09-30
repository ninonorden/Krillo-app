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
    # "Fix for WooCommerce and WordPress" komt erbij zodra Nino de proefwinkel
    # op TasteWP heeft nagelopen (1 oktober). Niet eerder: alleen wat echt werkt.
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
