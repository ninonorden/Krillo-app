"""
Krillo - articles.

The content of the articles section. This is deliberately not a complicated
system: the articles simply live in a list here. That is enough until there are
so many articles that you no longer want to manage them in code.

Why this section exists: search engines and AI assistants need content to be
able to find and cite a website. A site with only sales copy is rarely
recommended. This is exactly what Krillo advises its customers, so we apply it
to ourselves as well.
"""

ARTIKELEN = [
    {
        "slug": "wat-is-ai-zichtbaarheid",
        "titel": "What is AI visibility, and why does it matter for your online store?",
        "samenvatting": "More and more shoppers ask ChatGPT for a recommendation instead of searching Google. This is what that means for your store, and how to find out whether yours gets named.",
        "datum": "2026-08-20",
        "leestijd": "5 minutes",
        "inhoud": [
            ("", "Over the past two years something has changed in how people buy things, and most store owners have not noticed yet. Someone who used to search Google for 'best hiking boots' now asks ChatGPT: which hiking boots do you recommend for a multi-day trek? And they do not get a list of ten links. They get an answer with two or three names in it."),
            ("How it differs from normal search", "In a search engine you compete for a spot in a list. If you are in position eight, people still click on you now and then. With an AI assistant that list does not exist. There is one answer, and you are either in it or you are not. There is no position eight."),
            ("", "That makes the game harder, but also fairer. An AI does not look at how much you spend on ads. It looks at whether it can read your website, whether it understands what you sell, and whether it comes across you anywhere else."),
            ("Why many stores are invisible", "Most online stores are built for people, not for machines. That sounds obvious, but it has consequences. A modern store often builds its content only after the page has loaded. A visitor does not notice, but most AI crawlers do not wait for that. They see an empty page and move on."),
            ("", "On top of that, many stores accidentally lock out the crawlers that ChatGPT and Gemini use. Not on purpose, but because someone once put a line in a settings file that blocks all unknown visitors. The result is the same: to that assistant, you do not exist."),
            ("What you can do yourself", "Start with three things. Check whether your site lets AI crawlers in. Make sure your most important text is in the page itself and does not appear only later. And add machine-readable information to your products, so an assistant knows for certain what something is and what it costs."),
            ("", "Want to know where you stand right now? On krilloai.com you can run a free check of 13 technical points on your store. You see your score and every finding straight away, without an account and without payment details."),
        ],
    },
    {
        "slug": "chatgpt-blokkeert-je-webshop",
        "titel": "Is your online store blocking ChatGPT by accident?",
        "samenvatting": "Many stores lock out AI crawlers without knowing it, because of one line in a file nobody ever looks at. Here is how to check it in two minutes.",
        "datum": "2026-08-20",
        "leestijd": "4 minutes",
        "inhoud": [
            ("", "Almost every website has a small file called robots.txt. It is a short text file that tells visiting crawlers what they may and may not look at. It has usually been there since the day your site was built, and most owners have never opened it."),
            ("The problem in one line", "That file can contain a line that says: all crawlers, stay out of everything. Sometimes that was set on purpose, for example while the site was still being built, and then forgotten. But it also hits the crawlers of ChatGPT, Gemini and Perplexity. They are told at the door that they are not allowed in, and they leave without ever seeing your products."),
            ("How to check it yourself", "Type your own web address in the browser and add /robots.txt at the end. For example yourstore.nl/robots.txt. You will see a plain text screen."),
            ("", "Look for lines with the name of an AI crawler, such as GPTBot, ClaudeBot, PerplexityBot or Google-Extended. If one of them has a line with Disallow followed by a forward slash, that crawler is blocked completely. If there is no robots.txt at all, there is usually nothing wrong, because then everyone is simply allowed in."),
            ("What to do about it", "If you want to let AI assistants in, the file needs to say for each crawler that it is welcome. It looks like this, with a separate block per crawler: the name of the crawler, and below it Allow followed by a forward slash."),
            ("", "If you are not sure about this, ask whoever built your website to do it. It is a change of a few minutes, and it is exactly the kind of thing you regret later if it has been wrong for months."),
            ("A choice, not an obligation", "To be fair: some businesses do not want AI to use their content, and block these crawlers on purpose. That is a legitimate choice. The point is that it should be a choice, not something that happens by accident while you miss out on customers."),
        ],
    },
    {
        "slug": "productinformatie-leesbaar-voor-ai",
        "titel": "How to make your product information readable for AI",
        "samenvatting": "An AI assistant needs to know for certain what you sell and what it costs before it will recommend you. This is how you give it that certainty.",
        "datum": "2026-08-20",
        "leestijd": "6 minutes",
        "inhoud": [
            ("", "Imagine someone asks ChatGPT where to buy cheap garden chairs. The assistant then has to be able to read from your page that this is a garden chair, what it costs, and whether it is in stock. A person sees that at a glance. A machine does not, unless you spell it out."),
            ("What machine-readable information is", "There is an agreed format, used by almost all the big tech companies, for sending information along with a page. It is a small piece of code that visitors never see, but that is crystal clear to a machine: this is a product, this is the name, this is the price, this is the stock."),
            ("", "Without that information an assistant has to guess from the text on your page. Sometimes that works. Often it goes wrong, and then it would rather not mention you, because it is not sure it will say something wrong."),
            ("What it gets you", "Stores with good machine-readable product information get named more often and with more confidence. Not because an AI likes them better, but because with those stores it knows for sure what it is saying. An assistant that has doubts picks the source it does not need to doubt."),
            ("Where it usually goes wrong", "We see two things most often. First: the information is on the product pages, but not on the homepage or the category pages. Second: there is nothing at all, usually because the store platform does not add it automatically and nobody ever added it by hand."),
            ("", "If you use Shopify or WooCommerce, part of this is often built in already. If you have a custom-built store, it is more likely to be missing, because someone had to build it in on purpose."),
            ("How to find out", "You do not have to work this out yourself. The free check on krilloai.com looks at 13 technical points, and this is one of them. You see right away whether it is there or missing."),
        ],
    },
    {
        "slug": "veelgestelde-vragen-ai",
        "titel": "Why frequently asked questions raise your visibility in AI",
        "samenvatting": "AI assistants prefer to quote text that answers a question directly. A good FAQ section is therefore one of the quickest ways to get named.",
        "datum": "2026-08-20",
        "leestijd": "4 minutes",
        "inhoud": [
            ("", "When someone asks an AI assistant something, the assistant looks for text that answers exactly that question. The closer your text is to the question, the more likely it is to use your words. That is why a section with frequently asked questions has so much effect."),
            ("Question and answer, literally", "It works best if you write the question as an actual question, in the words a customer would use. So not 'Delivery times', but 'How quickly will my order be delivered?'. And below it a short, direct answer of two or three sentences."),
            ("", "Avoid the urge to turn it into a story. An assistant prefers an answer that stands on its own and is right straight away, without having to summarise three paragraphs."),
            ("Mark it as an official question too", "There is an extra step many stores skip. Besides the visible text, you can also send those questions and answers in a form that machines directly recognise as question and answer. Then an assistant does not have to guess whether this is an FAQ section. It knows for sure."),
            ("Which questions to include", "Start with the questions your customers really ask you. Look through your inbox or your customer service messages from the past month. Those are exactly the questions other people also ask an AI. Think of delivery times, returns, warranty, shipping costs, and how to choose or look after your product."),
            ("", "Ten good questions are worth more than thirty shallow ones. Write them the way you would answer them on the phone."),
        ],
    },
    {
        "slug": "google-verkeer-daalt-waar-gaat-het-heen",
        "titel": "Your Google traffic is falling. Where is it going?",
        "samenvatting": "Many online stores see their visitor numbers drop while their rankings stayed the same. This is what is probably happening, and how to spot it in your own numbers.",
        "datum": "2026-08-22",
        "leestijd": "5 minutes",
        "inhoud": [
            ("", "There is a pattern showing up at a lot of online stores lately. Your positions in Google have not dropped. You have not changed anything on your site. And yet fewer people come in than a year ago, and you cannot point to why."),
            ("What is probably happening", "Search has changed over the past few years. Some of the questions that used to lead to a click are now answered at the top of the results page. And some are no longer put to a search engine at all, but to an AI assistant."),
            ("", "Both have the same effect: someone gets an answer without visiting a website. You are still in position four, but position four gets clicked less often. To you, that looks like a loss you cannot explain."),
            ("How to see it in your own numbers", "In Google Search Console, look at your impressions and your clicks over the last two years. If impressions stay the same or go up while clicks go down, that is the pattern. People still see you, but they no longer need to click through."),
            ("", "Also check your visitor statistics for traffic coming from chatgpt.com, perplexity.ai or gemini.google.com. If it is there, you are already being named in AI answers. If it is not, that alone does not mean you are named nowhere: many people read a recommendation and then simply type your name in."),
            ("What you can and cannot do about it", "The honest answer is that you will not get that click back. What you can do is make sure you are in the answer. If you are named, people remember your name and come later anyway, just not through the route you were used to measuring."),
            ("", "That starts with three things you can check yourself. Does your site let AI crawlers in? Is your most important text in the page itself, or does it only appear later? And can a machine see what a product is, what it costs and whether it is in stock?"),
            ("", "Want to know whether you get named now? On krilloai.com you can run a free check of 13 technical points. And the Krillo index shows it directly: every month, per category and country, we put 30 buying questions to ChatGPT and Gemini, the way a shopper would ask them, and rank stores by how often AI names and recommends them. You see where you stand and which stores are ahead of you."),
        ],
    },
    {
        "slug": "weten-of-chatgpt-je-webshop-noemt",
        "titel": "How to find out whether ChatGPT names your online store",
        "samenvatting": "Quickly asking ChatGPT yourself gives a misleading answer. This is why, and how to measure it reliably.",
        "datum": "2026-08-22",
        "leestijd": "4 minutes",
        "inhoud": [
            ("", "Almost everyone reacts the same way at first: open ChatGPT and ask 'which online store sells X'. That is a logical first step, but the result is worth less than it seems."),
            ("Why your own test misleads you", "Three things get in the way. First, an assistant remembers what you discussed before, so if you ever talked about your own store, it is quite likely to name it to please you. Second, answers differ from day to day and from user to user. And third, without realising it you ask the question you hope to score on."),
            ("", "The result is that your own test almost always comes out too positive. You ask once, you are in the answer, and you conclude that all is well."),
            ("How to do it properly", "Three rules make the difference. Ask several different questions, not one. Ask them without earlier conversations, in a fresh window or through the API. And write the questions the way a buyer would ask them, not the way you would."),
            ("", "A buyer does not ask 'is store X any good'. They ask something like 'waar koop ik een goede regenjas voor op de fiets' (where do I buy a good rain jacket for cycling) and do not mention your name at all. That is exactly where you want to know whether you are in the answer."),
            ("Count per question, not per answer", "Here is another way to fool yourself. If you ask the same question to two assistants and you are in both answers, that is one question where you are named, not two. If you count per answer, your result looks twice as good as it is."),
            ("Named is not recommended", "Finally, watch the difference between appearing and being recommended. 'You could also take a look at X' is not the same as 'the rain jackets from X are the best choice'. Only the second one brings in customers."),
            ("", "Do not want to do this by hand? That is what the Krillo index does. Every month, per category and country, we put 30 buying questions to ChatGPT and Gemini, with no chat history, and rank stores by how often AI names and recommends them. You see your rank, the questions you lose and who was named instead. On krilloai.com you can also run a free check of 13 technical points."),
        ],
    },
    {
        "slug": "genoemd-versus-aanbevolen",
        "titel": "Being named is not the same as being recommended",
        "samenvatting": "Appearing in an AI answer is nice, but the difference between being listed and being recommended decides whether anyone buys.",
        "datum": "2026-08-22",
        "leestijd": "4 minutes",
        "inhoud": [
            ("", "Say someone asks an AI assistant where to buy good kitchenware. The answer names five stores. You are one of them. Good news, you would think."),
            ("", "But read how you are mentioned. 'There are also smaller sellers such as yourstore.nl' is very different from 'for pans that last, yourstore.nl is the best choice'. In the first case you are a footnote. In the second case you are the advice."),
            ("Four levels", "It goes up roughly like this. You do not appear at all. You are named as one of several options. You are named with a reason. Or a specific product of yours is recommended."),
            ("", "That last one is worth by far the most. Someone who is told that a specific product at your store is good does not need to look any further. Someone who sees your name in a list of five usually clicks on the first one."),
            ("Why stores get stuck here", "Being named often happens by itself once an assistant can read your site and understands what you sell. Being recommended takes more: somewhere there has to be something that shows why you are a good choice. A clear reason, a specialism, a product description that goes further than size and colour."),
            ("", "Assistants do not rely only on your own site for this. They also pick up what has been written about you elsewhere: comparisons, blogs, forums, reviews. If you appear nowhere outside your own site, there is little for a recommendation to rest on."),
            ("What to do with this", "Do not just check whether you appear, but how. Find the sentence in the answer where you are named and read it word for word. Is there a reason given? No? Then you know what to work on, and that is something other than producing more content."),
            ("", "The Krillo index on krilloai.com counts this difference separately. For each store you see how often it was named and how often it was actually recommended, based on 30 buying questions per category, put to ChatGPT and Gemini every month."),
        ],
    },
    {
        "slug": "llms-txt-nodig-of-niet",
        "titel": "Does your online store need llms.txt?",
        "samenvatting": "A lot is written about it, but the honest answer is more nuanced than yes or no. What it is, what it does, and what matters more.",
        "datum": "2026-08-22",
        "leestijd": "4 minutes",
        "inhoud": [
            ("", "If you look into AI visibility you soon come across llms.txt, usually with the message that you really must have it. The honest answer is less certain, and we think it is more useful to just say so."),
            ("What it is", "llms.txt is a text file you put on your website, just like robots.txt. In plain language it says what your site is, which pages matter most and where an AI assistant should start reading. The idea is that an assistant then does not have to guess what is important."),
            ("What it does", "It takes you half an hour and it does no harm. It also forces you to write down in two paragraphs what you sell and to whom, and that is a useful exercise in itself. Many stores are surprisingly bad at answering that question."),
            ("What it does not do", "It is not an official standard that all assistants follow, and there is no guarantee it gets read. Anyone who promises that llms.txt will get you into AI answers is promising something they cannot deliver."),
            ("", "The foundation underneath matters more. Does your site let AI crawlers in? Is your text in the page itself, or is it only built up later? Can a machine see what a product is and what it costs? If something goes wrong there, an llms.txt does not change that."),
            ("The order we would follow", "First check whether crawlers are allowed in. Then check whether your most important text can be read directly. Then make your product information machine-readable. Then a good FAQ section. And only then, as a bonus, llms.txt."),
            ("", "On krilloai.com we check all 13 points for free, and llms.txt is one of them. You see straight away which of them will do the most for you, instead of starting with whichever point happens to get written about the most."),
        ],
    },
]


def get_artikel(slug):
    for artikel in ARTIKELEN:
        if artikel["slug"] == slug:
            return artikel
    return None
