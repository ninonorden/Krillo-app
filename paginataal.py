"""De vaste teksten van de klantpagina, in het Nederlands en in het Engels.

Waarom dit bestaat: de klantpagina had zijn kopjes hard in het sjabloon staan,
in het Nederlands. De inhoud van die pagina komt uit de meting en die is allang
tweetalig, dus een Engelse winkel kreeg een pagina met Nederlandse kopjes en
Engelse taken door elkaar. Dat is niet alleen slordig, het is de reden dat een
beoordelaar bij Shopify een app afwijst.

Waarom een eigen bestand en niet twee sjablonen: twee sjablonen lopen na drie
wijzigingen uit elkaar en dan verandert er iets aan de Nederlandse pagina wat
de Engelse niet krijgt. Eén sjabloon met een tekstenlijst ernaast kan dat niet.

Een test bewaakt dat elke sleutel in beide talen bestaat en dat het sjabloon
geen sleutel gebruikt die hier niet staat.
"""

TEKSTEN = {
    "nl": {
        # kopregels
        "titel_bezig": "Wij zijn met je webshop bezig",
        "titel_gedaan": "Wat wij voor je gedaan hebben",
        "titel_taken": "Wat je deze week doet",
        "laatste_meting": "Laatste meting",

        # wij doen het
        "wacht_kop": "We wachten nog op toegang tot je webshop",
        "wacht_tekst": ("We kunnen pas beginnen als we in je winkel kunnen. In de mail "
                        "die je na je betaling kreeg staat precies hoe je dat regelt, "
                        "het kost je twee minuten. Kwijtgeraakt of loopt het vast? Mail "
                        "hallo@krillo.nl, dan helpen we je erdoorheen."),
        "bezig_kop": "We zijn bezig in je webshop",
        "bezig_tekst": ("Je hoeft nu even niets te doen. Zodra we klaar zijn krijg je een "
                        "overzicht van alles wat er veranderd is, met de oude tekst erbij, "
                        "zodat je alles kunt terugzetten."),
        "klaar_kop": "Wij hebben je webshop opgeknapt",
        "klaar_afgerond": "Afgerond op",
        "klaar_standaard": "Je hebt per mail een overzicht gekregen van wat er veranderd is.",
        "klaar_vervolg": ("Hieronder zie je wat er daarna nog open staat, en of je vaker "
                          "genoemd wordt."),
        "wijzigingen_kop": "Wat we precies veranderd hebben",
        "wijziging_waar": "Waar",
        "wijziging_nu": "Wat er nu staat",
        "wijziging_stond": "Wat er stond",
        "wijziging_leeg": "Hier stond nog niets, dit is nieuw toegevoegd.",
        "wijziging_terug": ("Wil je iets terug zoals het was, dan kan dat. Zet het zelf "
                            "terug met de tekst hierboven, of mail ons en wij doen het."),

        # taken
        "niets_kop": "Niets te doen deze week",
        "niets_tekst": ("Je site is in orde en op de plekken die we nakeken sta je erbij. "
                        "We blijven elke week meten en zodra er iets verandert staat het hier."),
        "letterlijk": "Neem dit letterlijk over",
        "kopieer": "Kopieer",
        "paginas": "Deze pagina's gaat het om",
        "waar_neerzetten": "Waar zet je dit neer",
        "wat_je_doet": "Wat je doet",
        "waarom": "Waarom deze taak, en hoe weten we dat",

        # niets gemeten
        "niets_gemeten_kop": "Deze week konden we niets meten",
        "niets_gemeten_tekst": ("Er is deze ronde geen bruikbare meting uit de AI-modellen "
                                "gekomen, dus we laten liever niets zien dan een cijfer waar "
                                "je niets aan hebt. We proberen het bij de volgende ronde "
                                "opnieuw. Je vorige metingen staan er nog gewoon bij."),
        "eerste_kop": "De eerste meting loopt nog",
        "eerste_tekst": ("We stellen deze week koopvragen aan ChatGPT en Gemini om te zien "
                         "of jouw winkel genoemd wordt. Zodra dat klaar is staat hier wat "
                         "je kan doen. Reken op ongeveer een kwartier."),
        "nognietgemeten_kop": "Er is nog niet gemeten",
        "nognietgemeten_tekst": ("Bij een eenmalige opdracht meten we niet doorlopend. Wil "
                                 "je elke week weten of AI je winkel noemt, dan kan dat met "
                                 "monitoring."),

        # onderaan
        "details_kop": "Alle metingen en cijfers bekijken",
        "details_tekst": ("Bij welke vragen je genoemd wordt, wat AI letterlijk over je zei, "
                          "wie je concurrenten zijn en alle dertien controlepunten van je site."),
        "abo_kop": "Je abonnement",
        "abo_tekst": ("Je betaalt 39 euro per maand, maandelijks opzegbaar. Zeg je op, dan "
                      "houd je toegang tot het einde van de periode die je al betaald hebt "
                      "en wordt er daarna niets meer afgeschreven."),
        "abo_knop": "Mijn abonnement opzeggen",
        "abo_bezig": "Bezig met opzeggen...",
        "abo_gelukt": ("Je abonnement is opgezegd. Je krijgt een bevestiging per e-mail. "
                       "Er wordt niets meer afgeschreven."),
        "eenmalig_kop": "Je hebt eenmalig betaald",
        "eenmalig_tekst": ("Er loopt geen abonnement en er wordt niets van je afgeschreven. "
                           "Wil je wel blijven meten, dan kan dat met monitoring."),
        "eenmalig_knop": "Bekijk monitoring",

        # Shopify
        "shopify_kop": "Je abonnement loopt via Shopify",
        "shopify_tekst": ("Je betaalt via je Shopify-factuur, niet rechtstreeks aan ons. "
                          "Opzeggen doe je in Shopify zelf, bij de app. Daar zie je ook "
                          "precies wat er in rekening gebracht wordt."),
        "shopify_knop": "Open Krillo in Shopify",

        # De detailpagina. Eigen voorvoegsel d_ zodat deze sleutels niet botsen
        # met die van de klantpagina hierboven, ook niet als er ooit een kopje
        # bijkomt dat toevallig hetzelfde heet.
        # De labels bij de dertien controlepunten.
        "stand_ok": "goed",
        "stand_deels": "kan beter",
        "stand_probleem": "verbeterpunt",

        "d_titel": "Alle metingen",
        "d_nav_actief": "Monitoring actief",
        "d_eyebrow": "Monitoring",
        "d_sub": "Deze pagina blijft altijd op hetzelfde adres staan en wordt elke week bijgewerkt.",
        "d_bewaar": ("Bewaar deze link, bijvoorbeeld als bladwijzer. Je hoeft niet in te "
                     "loggen, en je vindt hier altijd je nieuwste scan terug."),
        "d_terug": "Terug naar wat je deze week doet",

        # de score bovenaan
        "d_huidig_label": "Huidige AI-leesbaarheid",
        "d_huidig_uitleg": ("Hoe goed AI je site kan lezen en begrijpen. Dit is geen kans "
                            "dat je aanbevolen wordt."),
        "d_laatste_scan": "Laatste scan",
        "d_gestegen_met": "Gestegen met",
        "d_gedaald_met": "Gedaald met",
        "d_punten_sinds": "punten sinds de vorige scan",
        "d_gelijk_gebleven": "Gelijk gebleven sinds de vorige scan",
        "d_verloop_kop": "Je scoreverloop",

        # bevindingen
        "d_nieuw_kop": "Nieuw sinds de vorige scan",
        "d_nieuw_badge": "nieuw",
        "d_alle_bevindingen": "Alle bevindingen",
        "d_leeg": ("Er is nog geen scan uitgevoerd. Je eerste scan verschijnt hier zodra "
                   "die klaar is."),

        # word je genoemd
        "d_vermeld_kop": "Word je genoemd als iemand het aan AI vraagt?",
        "d_vermeld_uitleg_a": "We stellen elke week",
        "d_vermeld_uitleg_b": ("koopvragen die kopers in jouw categorie echt stellen. Deze "
                               "meting liep via"),
        "d_en": "en",
        "d_vermeld_sterkste": ("Zeggen de modellen niet hetzelfde over een vraag, dan tellen "
                               "we de sterkste uitkomst mee."),
        "d_bew_gestegen": "Gestegen",
        "d_bew_gedaald": "Gedaald",
        "d_bew_vaker": "Vaker aanbevolen",
        "d_bew_minder": "Minder vaak aanbevolen",
        "d_bew_veranderd": "Veranderd",
        "d_bew_sinds": "sinds de vorige meting: van",
        "d_bew_naar": "naar",
        "d_teller_genoemd": "Genoemd",
        "d_van": "van",
        "d_genoemd_uitleg": "Je winkel komt in het antwoord voor.",
        "d_teller_aanbevolen": "Aanbevolen",
        "d_aanbevolen_uitleg": "Je wordt ook echt aangeraden, niet alleen genoemd.",
        "d_teller_product": "Met een product erbij",
        "d_product_uitleg": ("Er wordt niet alleen naar je winkel verwezen, maar een concreet "
                             "product van je aangeraden."),
        "d_noemer_a": "We tellen",
        "d_noemer_b": "van je",
        "d_noemer_c": "vragen mee. Bij",
        "d_noemer_d": ("vragen werd er naar een merk of een product gevraagd en niet naar een "
                       "winkel. In zulke antwoorden komt geen enkele webshop voor, ook de "
                       "beste niet. Die meetellen zou je cijfer alleen maar mooier of lelijker "
                       "maken dan het is."),
        "d_concurrenten_kop": "Wie er nog meer genoemd worden",
        "d_concurrenten_uitleg": ("Bij dezelfde vragen. Dit zijn de winkels waar je het tegen "
                                  "opneemt."),
        "d_kol_winkel": "Winkel",
        "d_jij": "(jij)",
        "d_per_vraag": "Per vraag",
        "d_per_vraag_uitleg": "Het citaat eronder komt letterlijk uit het antwoord van de AI.",
        "d_vlag_aanbevolen": "aanbevolen",
        "d_vlag_genoemd": "genoemd",
        "d_vlag_niet": "niet genoemd",
        "d_plek": "plek",
        "d_product_genoemd": "product genoemd",
        "d_meet_kop1": "Hoe we dit meten.",
        "d_meet_a": "We stellen de vragen via de programmeerkoppeling van",
        "d_meet_b": ("zonder er iets omheen te zetten. Dat is een benadering van wat iemand in "
                     "de app zou zien: daar tellen ook de zoekresultaten van dat moment, de "
                     "locatie en de geschiedenis van die persoon mee. We tonen daarom aantallen "
                     "en geen percentages, want die zouden een precisie suggereren die er niet "
                     "is."),
        "d_meet_kop2": "Winkel tegenover product.",
        "d_meet_c": ('"Kijk eens bij deze winkel" is iets anders dan "de emaille mokken van '
                     'deze winkel zijn mooi". Dat tweede levert veel eerder een aankoop op, '
                     'want de koper weet dan al wat hij zoekt. Daarom tellen we die twee '
                     'apart.'),
        "d_meet_kop3": "Let op.",
        "d_meet_d": ("Of je genoemd wordt heb je niet helemaal zelf in de hand. Komt een "
                     "concurrent groot in het nieuws of wordt een AI-model bijgewerkt, dan kan "
                     "je cijfer veranderen zonder dat je iets fout deed. Daarom laten we zien "
                     "wie er nog meer genoemd worden, zodat je een daling kan plaatsen."),

        # wat betekent dit voor je site
        "d_verklaring_kop": "Wat betekent dit voor je site?",
        "d_verklaring_uitleg": ("We zetten je scan naast je vermeldingen. Wat we op je site "
                                "kunnen meten noemen we een feit. Wat we vermoeden noemen we "
                                "een vermoeden. Dat verschil houden we streng, want iets een "
                                "oorzaak noemen terwijl we het niet gemeten hebben helpt je "
                                "niet."),
        "d_blokkades_kop": "Dit houdt AI aantoonbaar tegen",
        "d_feit": "feit",
        "d_belemmeringen_kop": "Dit maakt je slechter leesbaar",
        "d_belemmeringen_uitleg": ("Deze punten helpen AI je site te begrijpen. Of ze bepalen "
                                   "of je genoemd wordt, weten we niet, dus dat beweren we ook "
                                   "niet."),
        "d_vermoeden": "vermoeden",
        "d_conclusie_kop": "Wat dit bij elkaar betekent",

        # waar staan de winkels die wel genoemd worden
        "d_bronnen_kop": "Waar staan de winkels die wel genoemd worden?",
        "d_bronnen_uitleg": ("Het grootste deel van wat AI over een winkel zegt komt niet van "
                             "die winkel zelf, maar van wat er elders over geschreven wordt. "
                             "Daarom hebben we jouw koopvragen ook in een gewone zoekmachine "
                             "gezet en de pagina's die daaruit kwamen nagelopen. Hieronder "
                             "staat wie er op die pagina's voorkomt en wie niet."),
        "d_bron_teller_plekken": "Plekken bekeken",
        "d_bron_plekken_uitleg": ("Websites waar winkels in jouw categorie naast elkaar gezet "
                                  "worden. Je eigen site telt niet mee."),
        "d_bron_teller_erop": "Jij staat erop",
        "d_bron_erop_uitleg": ("Je winkelnaam of een link naar je site komt op de pagina "
                               "voor."),
        "d_bron_teller_gemist": "Concurrent wel, jij niet",
        "d_bron_gemist_uitleg": ("Hier zit het verschil. Deze pagina's bestaan al, je hoeft ze "
                                 "niet te maken."),
        "d_bron_tabel_kop": "Op hoeveel van die websites staat wie",
        "d_kol_websites": "Websites",
        "d_gemiste_kop": "De pagina's waar je nog niet op staat",
        "d_gemiste_uitleg": ("Op deze pagina's staat wel een winkel die AI noemt, en jij niet. "
                             "Ze bestaan al en gaan over precies waar jij in handelt."),
        "d_hier_genoemd": "hier genoemd:",
        "d_bron_conclusie_kop": "Wat dit betekent",
        "d_bron_meet_kop1": "Wat dit wel en niet zegt.",
        "d_bron_meet_a": ("Dit is een feit: op deze pagina's staat die winkel wel en jij niet, "
                          "en je kan het zelf nakijken door op de link te klikken. Wat we er "
                          "niet bij beweren is dat je genoemd wordt zodra je er wel op staat. "
                          "Dat weten we niet en dat meten we niet. We laten zien waar het "
                          "verschil zit, niet wat het verschil veroorzaakt."),
        "d_bron_meet_kop2": "Waarom we het zo doen.",
        "d_bron_meet_b": ("We vragen bewust nooit aan een AI-model waarom het een winkel "
                          "aanraadt. Een model weet dat niet en verzint dan een verklaring die "
                          "overtuigend klinkt. Daar heb je niets aan. Dit zijn echte pagina's "
                          "die je zelf kan openen."),

        # klopt wat AI over je zegt
        "d_controle_kop": "Klopt wat AI over je zegt?",
        "d_controle_a": "We hebben",
        "d_controle_b": ("uitspraken over jouw winkel naast de tekst op je eigen site gelegd. "
                         "Wordt er iets beweerd dat niet klopt, dan komt een koper met een "
                         "verkeerde verwachting bij je aan."),
        "d_controle_klopt": "Klopt",
        "d_controle_kloptniet": "Klopt niet",
        "d_controle_onbekend": "Niet te controleren",
        "d_fout_bij": "Bij",
        "d_fout_zei": "zei AI:",
        "d_fout_site": "Op je site staat:",
        "d_controle_geen_fouten": "Er is niets gevonden dat aantoonbaar niet klopt.",
        "d_controle_meet_kop": 'Waarom staat er zoveel op "niet te controleren"?',
        "d_controle_meet": ("We lezen een paar pagina's van je site, niet je hele webshop. Een "
                            "uitspraak die we daar niet terugvinden noemen we onbekend en geen "
                            'fout. Smaakoordelen als "sfeervol" zijn sowieso niet te '
                            "controleren."),

        # onderaan de detailpagina
        "d_eenmalig_tekst": ("Er loopt geen abonnement en er wordt niets van je afgeschreven. "
                             "Wil je wel blijven meten, dan kan dat voor 39 euro per maand, "
                             "maandelijks opzegbaar."),
        "d_voorbeeld_kop": "Voorbeeldweergave",
        "d_voorbeeld_tekst": ("Dit is hoe een abonnee zijn eigen pagina ziet. Alleen zichtbaar "
                              "met de beheersleutel."),
        "d_opzeg_bevestig": ("Weet je zeker dat je je monitoring wil opzeggen? Je houdt toegang "
                             "tot het einde van de al betaalde periode."),
        "d_opzeg_mislukt": ("Het opzeggen is niet gelukt. Mail hallo@krillo.nl, dan regelen we "
                            "het."),
        "d_opgezegd": "Opgezegd",
        "d_opzeg_fout": "Er ging iets mis. Mail hallo@krillo.nl, dan regelen we het.",
    },
    "en": {
        "titel_bezig": "We are working on your store",
        "titel_gedaan": "What we did for you",
        "titel_taken": "What to do this week",
        "laatste_meting": "Last measurement",

        "wacht_kop": "We are still waiting for access to your store",
        "wacht_tekst": ("We can only start once we can get into your store. The email you "
                        "received after your payment explains exactly how to arrange that, "
                        "it takes two minutes. Lost it, or stuck? Email hallo@krillo.nl and "
                        "we will walk you through it."),
        "bezig_kop": "We are working in your store",
        "bezig_tekst": ("There is nothing for you to do right now. As soon as we are done "
                        "you will get an overview of everything that changed, with the old "
                        "text alongside it, so you can put anything back."),
        "klaar_kop": "We have tidied up your store",
        "klaar_afgerond": "Completed on",
        "klaar_standaard": "You received an overview of the changes by email.",
        "klaar_vervolg": ("Below you can see what is still open after that, and whether you "
                          "are being mentioned more often."),
        "wijzigingen_kop": "Exactly what we changed",
        "wijziging_waar": "Where",
        "wijziging_nu": "What it says now",
        "wijziging_stond": "What it said before",
        "wijziging_leeg": "There was nothing here, this is newly added.",
        "wijziging_terug": ("If you want something back the way it was, you can. Put it back "
                            "yourself using the text above, or email us and we will do it."),

        "niets_kop": "Nothing to do this week",
        "niets_tekst": ("Your site is in order and you show up in the places we checked. We "
                        "keep measuring every week and the moment something changes it "
                        "appears here."),
        "letterlijk": "Copy this exactly",
        "kopieer": "Copy",
        "paginas": "These are the pages",
        "waar_neerzetten": "Where to put this",
        "wat_je_doet": "What to do",
        "waarom": "Why this task, and how we know",

        "niets_gemeten_kop": "We could not measure anything this week",
        "niets_gemeten_tekst": ("This round produced no usable measurement from the AI "
                                "models, so we would rather show you nothing than a number "
                                "that means nothing. We will try again next round. Your "
                                "earlier measurements are still there."),
        "eerste_kop": "The first measurement is still running",
        "eerste_tekst": ("This week we are asking ChatGPT and Gemini buying questions to see "
                         "whether your store gets mentioned. As soon as that is done you "
                         "will see what you can do here. Expect about fifteen minutes."),
        "nognietgemeten_kop": "Nothing measured yet",
        "nognietgemeten_tekst": ("With a one-off job we do not keep measuring. If you want "
                                 "to know every week whether AI mentions your store, "
                                 "monitoring does that."),

        "details_kop": "See all measurements and figures",
        "details_tekst": ("Which questions you are mentioned in, what AI said about you word "
                          "for word, who your competitors are, and all thirteen checks on "
                          "your site."),
        "abo_kop": "Your subscription",
        "abo_tekst": ("You pay 39 euro per month, cancellable monthly. If you cancel you "
                      "keep access until the end of the period you already paid for, and "
                      "nothing is charged after that."),
        "abo_knop": "Cancel my subscription",
        "abo_bezig": "Cancelling...",
        "abo_gelukt": ("Your subscription has been cancelled. You will get a confirmation by "
                       "email. Nothing more will be charged."),
        "eenmalig_kop": "You paid a one-off fee",
        "eenmalig_tekst": ("There is no subscription running and nothing is being charged. If "
                           "you do want to keep measuring, monitoring does that."),
        "eenmalig_knop": "See monitoring",

        "shopify_kop": "Your subscription runs through Shopify",
        "shopify_tekst": ("You pay through your Shopify invoice, not directly to us. You "
                          "cancel in Shopify itself, under the app. That is also where you "
                          "see exactly what is being charged."),
        "shopify_knop": "Open Krillo in Shopify",

        # De labels bij de dertien controlepunten. Komen uit de route en niet uit
        # het sjabloon, dus zonder deze regels stonden ze op een Engelse pagina
        # gewoon in het Nederlands.
        "stand_ok": "good",
        "stand_deels": "could be better",
        "stand_probleem": "needs work",

        "d_titel": "All measurements",
        "d_nav_actief": "Monitoring active",
        "d_eyebrow": "Monitoring",
        "d_sub": "This page always stays at the same address and is updated every week.",
        "d_bewaar": ("Keep this link, for example as a bookmark. You do not have to log in, "
                     "and you will always find your newest scan here."),
        "d_terug": "Back to what you do this week",

        "d_huidig_label": "Current AI readability",
        "d_huidig_uitleg": ("How well AI can read and understand your site. This is not a "
                            "chance that you get recommended."),
        "d_laatste_scan": "Last scan",
        "d_gestegen_met": "Up by",
        "d_gedaald_met": "Down by",
        "d_punten_sinds": "points since the last scan",
        "d_gelijk_gebleven": "The same as the last scan",
        "d_verloop_kop": "How your score has moved",

        "d_nieuw_kop": "New since the last scan",
        "d_nieuw_badge": "new",
        "d_alle_bevindingen": "All findings",
        "d_leeg": ("No scan has been done yet. Your first scan appears here as soon as it is "
                   "ready."),

        "d_vermeld_kop": "Do you get mentioned when someone asks AI?",
        "d_vermeld_uitleg_a": "Every week we ask",
        "d_vermeld_uitleg_b": ("buying questions that shoppers in your category really ask. "
                               "This measurement ran through"),
        "d_en": "and",
        "d_vermeld_sterkste": ("If the models do not say the same thing about a question, we "
                               "count the strongest outcome."),
        "d_bew_gestegen": "Up",
        "d_bew_gedaald": "Down",
        "d_bew_vaker": "Recommended more often",
        "d_bew_minder": "Recommended less often",
        "d_bew_veranderd": "Changed",
        "d_bew_sinds": "since the last measurement: from",
        "d_bew_naar": "to",
        "d_teller_genoemd": "Mentioned",
        "d_van": "of",
        "d_genoemd_uitleg": "Your shop appears in the answer.",
        "d_teller_aanbevolen": "Recommended",
        "d_aanbevolen_uitleg": "You are actually recommended, not only mentioned.",
        "d_teller_product": "With a product named",
        "d_product_uitleg": ("It is not only a pointer to your shop, an actual product of "
                             "yours is recommended."),
        "d_noemer_a": "We count",
        "d_noemer_b": "of your",
        "d_noemer_c": "questions. In",
        "d_noemer_d": ("questions the shopper asked about a brand or a product, not about a "
                       "shop. No web shop at all appears in answers like that, not even the "
                       "best one. Counting them would only make your number look better or "
                       "worse than it is."),
        "d_concurrenten_kop": "Who else gets mentioned",
        "d_concurrenten_uitleg": ("On the same questions. These are the shops you are up "
                                  "against."),
        "d_kol_winkel": "Shop",
        "d_jij": "(you)",
        "d_per_vraag": "Question by question",
        "d_per_vraag_uitleg": "The quote below comes straight out of the answer from the AI.",
        "d_vlag_aanbevolen": "recommended",
        "d_vlag_genoemd": "mentioned",
        "d_vlag_niet": "not mentioned",
        "d_plek": "place",
        "d_product_genoemd": "product named",
        "d_meet_kop1": "How we measure this.",
        "d_meet_a": "We ask the questions through the programming connection of",
        "d_meet_b": ("with nothing built around it. That comes close to what someone would see "
                     "in the app: there the search results of that moment, the location and "
                     "that person's history count as well. So we show counts and not "
                     "percentages, because percentages would suggest a precision that is not "
                     "there."),
        "d_meet_kop2": "Shop against product.",
        "d_meet_c": ('"Have a look at this shop" is something else than "the enamel mugs from '
                     'this shop are lovely". The second one leads to a sale much sooner, '
                     'because the buyer already knows what he is looking for. That is why we '
                     'count those two apart.'),
        "d_meet_kop3": "Please note.",
        "d_meet_d": ("Whether you get mentioned is not fully in your own hands. If a competitor "
                     "is big in the news or an AI model is updated, your number can change "
                     "without you doing anything wrong. That is why we show who else gets "
                     "mentioned, so you can make sense of a drop."),

        "d_verklaring_kop": "What does this mean for your site?",
        "d_verklaring_uitleg": ("We put your scan next to your mentions. What we can measure on "
                                "your site we call a fact. What we suspect we call a guess. We "
                                "keep that difference strict, because calling something a cause "
                                "while we have not measured it does not help you."),
        "d_blokkades_kop": "This provably holds AI back",
        "d_feit": "fact",
        "d_belemmeringen_kop": "This makes you harder to read",
        "d_belemmeringen_uitleg": ("These points help AI understand your site. Whether they "
                                   "decide if you get mentioned we do not know, so we do not "
                                   "claim that either."),
        "d_vermoeden": "guess",
        "d_conclusie_kop": "What this adds up to",

        "d_bronnen_kop": "Where are the shops that do get mentioned?",
        "d_bronnen_uitleg": ("Most of what AI says about a shop does not come from that shop "
                             "itself, but from what is written about it elsewhere. So we also "
                             "put your buying questions into an ordinary search engine and went "
                             "through the pages that came out of it. Below you can see who "
                             "appears on those pages and who does not."),
        "d_bron_teller_plekken": "Places checked",
        "d_bron_plekken_uitleg": ("Websites where shops in your category are listed side by "
                                  "side. Your own site does not count."),
        "d_bron_teller_erop": "You are on it",
        "d_bron_erop_uitleg": "Your shop name or a link to your site appears on the page.",
        "d_bron_teller_gemist": "Competitor yes, you no",
        "d_bron_gemist_uitleg": ("This is where the difference sits. These pages already exist, "
                                 "you do not have to make them."),
        "d_bron_tabel_kop": "Who is on how many of those websites",
        "d_kol_websites": "Websites",
        "d_gemiste_kop": "The pages you are not on yet",
        "d_gemiste_uitleg": ("These pages do list a shop that AI mentions, and not you. They "
                             "already exist and they are about exactly what you sell."),
        "d_hier_genoemd": "mentioned here:",
        "d_bron_conclusie_kop": "What this means",
        "d_bron_meet_kop1": "What this does and does not say.",
        "d_bron_meet_a": ("This is a fact: on these pages that shop is listed and you are not, "
                          "and you can check it yourself by clicking the link. What we do not "
                          "claim alongside it is that you get mentioned as soon as you are on "
                          "them. We do not know that and we do not measure it. We show where "
                          "the difference sits, not what causes the difference."),
        "d_bron_meet_kop2": "Why we do it this way.",
        "d_bron_meet_b": ("We deliberately never ask an AI model why it recommends a shop. A "
                          "model does not know that and then makes up an explanation that "
                          "sounds convincing. That is no use to you. These are real pages that "
                          "you can open yourself."),

        "d_controle_kop": "Is what AI says about you correct?",
        "d_controle_a": "We compared",
        "d_controle_b": ("statements about your shop with the text on your own site. If "
                         "something is claimed that is not correct, a buyer turns up with the "
                         "wrong expectation."),
        "d_controle_klopt": "Correct",
        "d_controle_kloptniet": "Not correct",
        "d_controle_onbekend": "Cannot be checked",
        "d_fout_bij": "On",
        "d_fout_zei": "AI said:",
        "d_fout_site": "Your site says:",
        "d_controle_geen_fouten": "We found nothing that is provably not correct.",
        "d_controle_meet_kop": 'Why is so much marked "cannot be checked"?',
        "d_controle_meet": ("We read a few pages of your site, not your whole shop. A statement "
                            "we do not find back there we call unknown and not an error. "
                            'Matters of taste such as "charming" cannot be checked at all.'),

        "d_eenmalig_tekst": ("There is no subscription running and nothing is being charged to "
                             "you. If you do want to keep measuring, you can for 39 euro per "
                             "month, cancellable monthly."),
        "d_voorbeeld_kop": "Preview",
        "d_voorbeeld_tekst": ("This is how a subscriber sees his own page. Only visible with "
                              "the admin key."),
        "d_opzeg_bevestig": ("Are you sure you want to cancel your monitoring? You keep access "
                             "until the end of the period you already paid for."),
        "d_opzeg_mislukt": ("Cancelling did not work. Email hallo@krillo.nl and we will sort it "
                            "out."),
        "d_opgezegd": "Cancelled",
        "d_opzeg_fout": "Something went wrong. Email hallo@krillo.nl and we will sort it out.",
    },
}


def teksten(taal):
    """De teksten voor deze taal. Onbekende taal wordt Nederlands.

    Nederlands als terugval en niet Engels, want dat is wat alle bestaande
    klanten al hadden en wat bij een onbekende winkel het meest waarschijnlijk
    klopt."""
    return TEKSTEN.get((taal or "nl").lower(), TEKSTEN["nl"])
