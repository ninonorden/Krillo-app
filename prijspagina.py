"""De inhoud van /pricing: de vergelijking per pakket en de vragen (15 oktober 2026).

WAAROM APART VAN HET SJABLOON. De vergelijking moet kloppen met wat de code
echt doet; hier staat per regel waar dat in de code zit, zodat een wijziging in
een pakket hier zichtbaar is (test_pricing_pagina_15okt kijkt mee). Waarden:
True = zit erin, False = niet, of een korte tekst ("5", "Weekly").

Kolommen: gratis check, Watch, Fix, Agencies (pakket "merken").
EERLIJK: alleen wat er is. Wat geen enkel pakket heeft, staat er niet (zoals
dagelijkse metingen of Perplexity): "If a line is not here, no plan has it yet."
"""
import contentmotor
import eigenvragen
import shopify_werk
import snelmeting

VERGELIJKING = [
    {"naam": "Measure", "rijen": [
        # 15 okt (Nino): assistenten en landen niet in de tabel. Dat worden er
        # meer, en het staat al overal op de site (homepage, index, vragen hieronder).
        {"wat": "Stores", "waarden": ["1", "1", "1", "Up to 25"]},
        {"wat": "Every buying question in your category", "uitleg": "The Krillo Index, nothing to set up",
         "waarden": ["Today's snapshot", "Monthly", "Monthly", "Monthly"]},
        # 16 okt: Fix meet 15 vragen per week (snelmeting.AANTAL_FIX).
        {"wat": "Your key questions", "uitleg": "Asked again every week, emailed to you",
         "waarden": [False, f"{snelmeting.AANTAL}, weekly", f"{snelmeting.AANTAL_FIX}, weekly",
                     f"{snelmeting.AANTAL}, weekly"]},
        # eigenvragen.MAX
        {"wat": "Questions of your own", "waarden": [False, str(eigenvragen.MAX["watch"]), str(eigenvragen.MAX["fix"]),
                                                    f"{eigenvragen.MAX['merken']} per store"]},
        {"wat": "Competitors you follow", "uitleg": "Marked in your ranking", "waarden": [False, True, True, True]},
    ]},
    {"naam": "Understand", "rijen": [
        {"wat": "Your rank and who beats you", "waarden": [True, True, True, True]},
        {"wat": "The buying questions you lose", "waarden": ["A few", "All", "All", "All"]},
        {"wat": "The real AI answer per question", "waarden": [False, True, True, True]},
        {"wat": "Why you lose, next to the winning page", "waarden": [False, True, True, True]},
        {"wat": "Which of your products AI names", "waarden": [False, True, True, True]},
        {"wat": "What AI names in your place, word for word", "waarden": [False, True, True, True]},
        {"wat": "The sites AI sends shoppers to", "waarden": [False, True, True, True]},
        {"wat": "Ready to buy versus still comparing", "uitleg": "Per question", "waarden": [False, True, True, True]},
        # 16 okt (stap 240): zoekmachine en AI naast elkaar.
        {"wat": "Your place in web search next to AI", "uitleg": "Per buying question, every month",
         "waarden": [False, True, True, True]},
        # 16 okt (stap 191): de zoekopdrachten van AI zelf, alleen Fix (kost per vraag).
        {"wat": "What AI searched for before answering", "uitleg": "With the page of yours that should answer it",
         "waarden": [False, False, True, True]},
    ]},
    {"naam": "Fix", "rijen": [
        {"wat": "Every fix written out, in order", "waarden": [False, True, True, True]},
        {"wat": "Ready-made titles, descriptions and texts per page", "waarden": [False, True, True, True]},
        {"wat": "Structured data blocks to paste", "uitleg": "Product, FAQ and store details", "waarden": [False, True, True, True]},
        {"wat": "robots.txt and llms.txt fixes", "waarden": [False, True, True, True]},
        {"wat": "We make the changes in your store", "uitleg": "With the Shopify app; on other platforms ready to paste",
         "waarden": [False, False, True, False]},
        {"wat": "Undo any change in one click", "waarden": [False, False, True, False]},
        # 16 okt (Fix waard maken): wat Fix nu extra doet.
        {"wat": "New buying-guide pages for questions you lose", "uitleg": "Written in your language, from your products",
         "waarden": [False, "Topics only", f"{contentmotor.PER_MAAND} written a month", "Topics only"]},
        {"wat": "Lost a question? A new page the same week", "uitleg": "On top of the monthly pages",
         "waarden": [False, "An email", True, "An email"]},
        {"wat": "Product pages fixed for you", "uitleg": "Image descriptions and product texts",
         "waarden": [False, False, f"Up to {shopify_werk.AUTOMATISCH_PER_WEEK} a week", False]},
        {"wat": "Ready-to-send messages to get listed", "uitleg": "Per review and comparison site AI cites",
         "waarden": [False, False, True, False]},
        {"wat": "Hours of work done for you, counted", "uitleg": "Every month in your dashboard and email",
         "waarden": [False, False, True, False]},
        {"wat": "Before and after per change", "uitleg": "Measured with your weekly questions",
         "waarden": [False, True, True, True]},
        {"wat": "What AI answered before and after each new page", "uitleg": "In your dashboard and monthly email",
         "waarden": [False, False, True, False]},
    ]},
    {"naam": "Pages", "rijen": [
        {"wat": "Website checks AI cares about", "waarden": ["13 checks", "Weekly", "Weekly", "Weekly"]},
        {"wat": "Homepage and key pages, per page", "waarden": [False, "Weekly", "Weekly", "Weekly"]},
        {"wat": "All product pages", "uitleg": "From your sitemap, 40 more every week", "waarden": [False, True, True, True]},
        {"wat": "Can each AI crawler read each page", "waarden": [False, True, True, True]},
    ]},
    {"naam": "Reports", "rijen": [
        {"wat": "Monthly report by email", "waarden": [False, True, True, True]},
        {"wat": "Report as PDF", "waarden": [False, True, True, True]},
        {"wat": "Export to Excel (CSV)", "waarden": [False, True, True, True]},
        # 16 okt (Nino akkoord): Slack alleen bij Fix en Agencies; Watch krijgt de melding per mail.
        {"wat": "Alerts in Slack", "waarden": [False, False, True, True]},
        {"wat": "Reports under your own name and logo", "waarden": [False, False, False, True]},
    ]},
    {"naam": "Results", "rijen": [
        {"wat": "Visits and revenue from AI assistants", "uitleg": "With the Krillo pixel or the Shopify app",
         "waarden": [False, True, True, True]},
        {"wat": "What Krillo costs next to what AI brings in", "waarden": [False, True, True, True]},
    ]},
    {"naam": "Plan", "rijen": [
        {"wat": "Try it", "waarden": ["Free", "14 days free", "14 days money back", "Check 10 stores free"]},
        {"wat": "Cancel any month", "waarden": [True, True, True, True]},
        {"wat": "Yearly billing, two months free", "waarden": [False, True, True, False]},
        {"wat": "Support", "uitleg": "By email, answer within one working day", "waarden": [False, True, True, True]},
    ]},
]

VRAGEN = [
    {"vraag": "Do I need a card for the free trial?",
     "antwoord": "Yes, for Watch we check your payment method with 1 cent, so the plan can continue after day 14. "
                 "Cancel before day 15 and you pay nothing. The free check needs no card and no account."},
    {"vraag": "Do I have to set anything up?",
     "antwoord": "No. Your category is already measured in the Krillo Index, so you see your rank, your competitors and "
                 "the questions you lose from the first minute. You can add questions of your own later."},
    {"vraag": "What is the difference between Watch and Fix?",
     "antwoord": "Watch shows everything and writes out every fix, so you can do it yourself. Fix does the work: we "
                 "make the changes in your store (undo any of them in one click), write two new buying-guide pages "
                 "a month for questions you lose, give you a ready message for every site AI cites, measure 15 "
                 "questions every week and show the hours of work we did for you."},
    {"vraag": "I am on Shopify. How do I pay?",
     "antwoord": "Install Krillo from the Shopify App Store. Your first changes are free and the plan is billed on your "
                 "Shopify invoice, so there is no separate payment."},
    {"vraag": "Can I cancel any time?",
     "antwoord": "Yes, every month, from the Plan page in your dashboard. On Fix, cancel within 14 days of your first "
                 "payment and you get it back. Yearly plans: full refund within 14 days of the first payment."},
    {"vraag": "Which assistants and countries do you measure?",
     "antwoord": "ChatGPT and Gemini, in the Netherlands and Belgium. Leave your email on the index page if you sell "
                 "somewhere else, and we tell you when your country goes live."},
    {"vraag": "Can a store pay for a better position?",
     "antwoord": "No. The index has no paid positions. The questions are published and every answer is kept."},
    {"vraag": "Do you guarantee a place in ChatGPT?",
     "antwoord": "No one can, and we do not promise it. We show what AI answers today, what to change, and whether "
                 "you were named more often after the change."},
]


def faq_ld():
    return {"@context": "https://schema.org", "@type": "FAQPage", "inLanguage": "en",
            "mainEntity": [{"@type": "Question", "name": v["vraag"],
                            "acceptedAnswer": {"@type": "Answer", "text": v["antwoord"]}} for v in VRAGEN]}
