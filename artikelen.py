"""
Krillo - artikelen.

De inhoud van de kennissectie. Dit is bewust geen ingewikkeld systeem: de
artikelen staan hier gewoon in een lijst. Dat is genoeg tot er zoveel artikelen
zijn dat je ze niet meer wil beheren in code.

Waarom deze sectie bestaat: zoekmachines en AI-assistenten hebben inhoud nodig
om een website te kunnen vinden en citeren. Een site met alleen verkooptekst
wordt zelden aanbevolen. Dit is precies wat Krillo aan klanten adviseert, dus
we passen het ook op onszelf toe.
"""

ARTIKELEN = [
    {
        "slug": "wat-is-ai-zichtbaarheid",
        "titel": "Wat is AI-zichtbaarheid en waarom raakt het jouw webshop?",
        "samenvatting": "Steeds meer kopers vragen ChatGPT om een aanbeveling in plaats van te googelen. Dit is wat dat betekent voor je webshop, en hoe je erachter komt of jij genoemd wordt.",
        "datum": "2026-08-20",
        "leestijd": "5 minuten",
        "inhoud": [
            ("", "Er is de afgelopen twee jaar iets veranderd in hoe mensen dingen kopen, en de meeste webshop-eigenaren hebben het nog niet door. Waar iemand vroeger googelde op 'beste wandelschoenen', vraagt diezelfde persoon nu aan ChatGPT: welke wandelschoenen raad je aan voor een meerdaagse tocht. En dan krijgt hij geen lijst met tien links, maar een antwoord met twee of drie namen erin."),
            ("Het verschil met gewoon zoeken", "Bij een zoekmachine strijd je om een plek in een lijst. Sta je op plek acht, dan word je soms nog aangeklikt. Bij een AI-assistent bestaat die lijst niet. Er is een antwoord, en daar sta je in of niet. Er is geen plek acht."),
            ("", "Dat maakt het spel harder, maar ook eerlijker. Een AI kijkt namelijk niet naar hoeveel je aan advertenties uitgeeft. Hij kijkt naar of hij jouw website kan lezen, of hij begrijpt wat je verkoopt, en of hij je ergens anders tegenkomt."),
            ("Waarom veel webshops onzichtbaar zijn", "De meeste webshops zijn gebouwd voor mensen, niet voor machines. Dat klinkt logisch, maar het heeft gevolgen. Een moderne webshop bouwt zijn inhoud vaak pas op nadat de pagina geladen is. Een bezoeker merkt daar niets van, maar de meeste AI-robots wachten daar niet op. Die zien een lege pagina en gaan verder."),
            ("", "Daar komt bij dat veel shops per ongeluk de robots buitensluiten die ChatGPT en Gemini gebruiken. Niet uit onwil, maar omdat in een instellingsbestand ooit een regel is gezet die alle onbekende bezoekers weert. Het gevolg is hetzelfde: je bestaat niet voor die assistent."),
            ("Wat je er zelf aan kan doen", "Begin met drie dingen. Check of je site AI-robots binnenlaat. Zorg dat je belangrijkste tekst gewoon in de pagina staat en niet pas later verschijnt. En geef je producten machine-leesbare informatie mee, zodat een assistent zeker weet wat iets is en wat het kost."),
            ("", "Wil je weten hoe je er nu voor staat, dan kan je op krillo.nl gratis je webshop laten scannen. Je krijgt binnen een minuut je score en alle bevindingen te zien, zonder account en zonder betaalgegevens."),
        ],
    },
    {
        "slug": "chatgpt-blokkeert-je-webshop",
        "titel": "Blokkeert jouw webshop per ongeluk ChatGPT?",
        "samenvatting": "Veel webshops sluiten AI-robots buiten zonder het te weten, door één regel in een bestand dat niemand ooit bekijkt. Zo check je het in twee minuten.",
        "datum": "2026-08-20",
        "leestijd": "4 minuten",
        "inhoud": [
            ("", "Op vrijwel elke website staat een bestandje dat robots.txt heet. Het is een kort tekstbestand dat aan bezoekende robots vertelt wat ze wel en niet mogen bekijken. Het staat er meestal al vanaf de dag dat je site gebouwd werd, en de meeste eigenaren hebben het nooit geopend."),
            ("Het probleem in één regel", "In dat bestand kan een regel staan die zegt: alle robots, blijf overal weg. Dat is soms bewust zo gezet, bijvoorbeeld toen de site nog in aanbouw was, en daarna vergeten. Maar het treft ook de robots van ChatGPT, Gemini en Perplexity. Die krijgen dan bij de deur te horen dat ze niet naar binnen mogen, en gaan weg zonder ooit je producten te zien."),
            ("Zo check je het zelf", "Typ je eigen webadres in de browser en zet er achteraan: /robots.txt. Dus bijvoorbeeld jouwwebshop.nl/robots.txt. Je krijgt dan een simpel tekstscherm te zien."),
            ("", "Zoek naar regels waarin de naam van een AI-robot staat, zoals GPTBot, ClaudeBot, PerplexityBot of Google-Extended. Staat daar bij eentje een regel met Disallow gevolgd door een schuine streep, dan wordt die robot volledig geweerd. Staat er helemaal geen robots.txt, dan is er meestal niets aan de hand, want dan mag iedereen gewoon binnen."),
            ("Wat je eraan doet", "Wil je AI-assistenten toelaten, dan moet er voor elke robot komen te staan dat hij welkom is. Dat ziet er zo uit, met per robot een eigen blokje: de naam van de robot, en daaronder Allow gevolgd door een schuine streep."),
            ("", "Ben je hier niet zeker van, laat het dan doen door degene die je website heeft gebouwd. Het is een aanpassing van een paar minuten, en het is precies het soort ding waar je later spijt van hebt als het maandenlang verkeerd staat."),
            ("Een keuze, geen verplichting", "Voor de eerlijkheid: sommige bedrijven willen juist niet dat AI hun inhoud gebruikt, en blokkeren die robots bewust. Dat is een legitieme keuze. Het punt is dat het een keuze moet zijn, en niet iets dat per ongeluk gebeurt terwijl je klanten misloopt."),
        ],
    },
    {
        "slug": "productinformatie-leesbaar-voor-ai",
        "titel": "Zo maak je je productinformatie leesbaar voor AI",
        "samenvatting": "Een AI-assistent moet zeker weten wat je verkoopt en wat het kost voordat hij je durft aan te bevelen. Dit is hoe je hem die zekerheid geeft.",
        "datum": "2026-08-20",
        "leestijd": "6 minuten",
        "inhoud": [
            ("", "Stel je voor dat iemand aan ChatGPT vraagt waar hij goedkope tuinstoelen kan kopen. De assistent moet dan van jouw pagina kunnen aflezen dat het om een tuinstoel gaat, wat die kost, en of hij op voorraad is. Een mens ziet dat in één oogopslag. Een machine niet, tenzij je het er expliciet bij zet."),
            ("Wat machine-leesbare informatie is", "Er bestaat een afspraak, gebruikt door zo goed als alle grote techbedrijven, om informatie op een pagina in een vast formaat mee te sturen. Het is een klein stukje code dat de bezoeker nooit ziet, maar dat voor een machine glashelder is: dit is een product, dit is de naam, dit is de prijs, dit is de voorraad."),
            ("", "Zonder die informatie moet een assistent gokken op basis van de tekst op je pagina. Soms gaat dat goed. Vaak gaat het mis, en dan noemt hij je liever niet, omdat hij niet zeker weet of hij iets verkeerds zegt."),
            ("Wat het oplevert", "Webshops met goede machine-leesbare productinformatie worden vaker en met meer zekerheid genoemd. Niet omdat een AI ze aardiger vindt, maar omdat hij bij die shops zeker weet wat hij zegt. Een assistent die twijfelt, kiest de bron waar hij niet over hoeft te twijfelen."),
            ("Waar het meestal misgaat", "Twee dingen zien we het vaakst. Ten eerste: de informatie staat wel op de productpagina's, maar niet op de homepage of de categoriepagina's. Ten tweede: er staat helemaal niets, meestal omdat het webshopsysteem het niet automatisch meestuurt en niemand het ooit heeft toegevoegd."),
            ("", "Gebruik je Shopify of WooCommerce, dan zit een deel hiervan er vaak al standaard in. Heb je een op maat gemaakte webshop, dan is de kans groter dat het ontbreekt, want dan moet iemand het bewust hebben ingebouwd."),
            ("Hoe je erachter komt", "Je hoeft dit niet zelf uit te zoeken. Een gratis scan op krillo.nl checkt onder andere dit punt, en kijkt daarvoor ook op je product- en categoriepagina's, niet alleen op je homepage. Je ziet dan meteen of het er staat en waar het ontbreekt."),
        ],
    },
    {
        "slug": "veelgestelde-vragen-ai",
        "titel": "Waarom veelgestelde vragen je zichtbaarheid bij AI verhogen",
        "samenvatting": "AI-assistenten citeren het liefst teksten die een vraag direct beantwoorden. Een goede vragensectie is daarom een van de snelste manieren om genoemd te worden.",
        "datum": "2026-08-20",
        "leestijd": "4 minuten",
        "inhoud": [
            ("", "Als iemand een AI-assistent iets vraagt, zoekt die assistent naar tekst die precies die vraag beantwoordt. Hoe dichter jouw tekst bij de vraag ligt, hoe groter de kans dat hij jouw woorden overneemt. Dat is de reden waarom een sectie met veelgestelde vragen zoveel effect heeft."),
            ("Vraag en antwoord, letterlijk", "Het werkt het beste als je de vraag ook echt als vraag opschrijft, in de woorden die een klant zou gebruiken. Dus niet 'Levertijden', maar 'Hoe snel wordt mijn bestelling geleverd?'. En daaronder een kort, direct antwoord in twee of drie zinnen."),
            ("", "Vermijd de neiging om er een verhaal van te maken. Een assistent pakt het liefst een antwoord dat op zichzelf staat en meteen klopt, zonder dat hij drie alinea's moet samenvatten."),
            ("Ook nog als officiële vraag markeren", "Er is een extra stap die veel shops overslaan. Naast de zichtbare tekst kan je die vragen en antwoorden ook meesturen in een vorm die machines direct herkennen als vraag en antwoord. Dan hoeft een assistent niet te raden of dit een vragensectie is, hij weet het zeker."),
            ("Welke vragen je zou moeten opnemen", "Begin met de vragen die je klanten je echt stellen. Kijk in je mailbox of je klantenservice-berichten van de afgelopen maand. Dat zijn precies de vragen die anderen ook aan een AI stellen. Denk aan levertijden, retourneren, garantie, verzendkosten, en hoe je je product kiest of onderhoudt."),
            ("", "Tien goede vragen zijn meer waard dan dertig oppervlakkige. Schrijf ze zoals je ze aan de telefoon zou beantwoorden."),
        ],
    },
    {
        "slug": "google-verkeer-daalt-waar-gaat-het-heen",
        "titel": "Je Google-verkeer daalt. Waar gaat het heen?",
        "samenvatting": "Veel webshops zien hun bezoekersaantallen zakken terwijl hun posities gelijk bleven. Dit is wat er waarschijnlijk gebeurt, en hoe je het in je eigen cijfers terugziet.",
        "datum": "2026-08-22",
        "leestijd": "5 minuten",
        "inhoud": [
            ("", "Er is een patroon dat de laatste tijd bij veel webshops opduikt. Je posities in Google zijn niet gezakt. Je hebt niets veranderd aan je site. En toch komen er minder mensen binnen dan een jaar geleden, zonder dat je kan aanwijzen waarom."),
            ("Wat er waarschijnlijk gebeurt", "Zoeken is de afgelopen jaren veranderd. Een deel van de vragen die vroeger tot een klik leidden, wordt nu bovenaan de zoekpagina al beantwoord. En een ander deel wordt helemaal niet meer aan een zoekmachine gesteld, maar aan een AI-assistent."),
            ("", "Bij allebei geldt hetzelfde: iemand krijgt een antwoord zonder een website te bezoeken. Je positie is dan nog steeds vier, maar er wordt minder vaak op plek vier geklikt. Voor jou ziet dat eruit als onverklaarbaar verlies."),
            ("Hoe je het in je eigen cijfers ziet", "Kijk in Google Search Console naar je vertoningen en je kliks over de laatste twee jaar. Zie je dat de vertoningen gelijk blijven of stijgen terwijl de kliks dalen, dan is dat het patroon. Mensen zien je nog wel, maar hoeven niet meer door te klikken."),
            ("", "Kijk daarnaast in je bezoekersstatistieken of er verkeer binnenkomt vanaf chatgpt.com, perplexity.ai of gemini.google.com. Is dat er, dan word je al genoemd in AI-antwoorden. Is het er niet, dan zegt dat op zichzelf nog niet dat je nergens genoemd wordt: veel mensen lezen een aanbeveling en typen daarna je naam gewoon in."),
            ("Wat je er wel en niet aan kan doen", "Het eerlijke antwoord is dat je die klik niet terugkrijgt. Wat je wel kan doen is zorgen dat je in het antwoord staat. Word je genoemd, dan onthoudt iemand je naam en komt hij later alsnog, alleen niet meer via de weg die je gewend was te meten."),
            ("", "Dat begint bij drie dingen die je zelf kan controleren. Laat je site AI-robots binnen. Staat je belangrijkste tekst gewoon in de pagina, of verschijnt hij pas later? En kan een machine zien wat een product is, wat het kost en of het op voorraad ligt?"),
            ("", "Wil je weten of je nu genoemd wordt, dan kan je dat op krillo.nl gratis laten testen. We stellen vijf koopvragen aan AI zoals een klant ze zou stellen, en je ziet bij hoeveel daarvan jouw winkel in het antwoord stond en welke winkels er wel stonden."),
        ],
    },
    {
        "slug": "weten-of-chatgpt-je-webshop-noemt",
        "titel": "Zo kom je erachter of ChatGPT jouw webshop noemt",
        "samenvatting": "Zelf even iets vragen aan ChatGPT geeft een misleidend antwoord. Dit is waarom, en hoe je het wel betrouwbaar meet.",
        "datum": "2026-08-22",
        "leestijd": "4 minuten",
        "inhoud": [
            ("", "De eerste reactie van bijna iedereen is hetzelfde: ChatGPT openen en vragen 'welke webshop verkoopt X'. Dat is een logische eerste stap, maar de uitkomst is minder waard dan hij lijkt."),
            ("Waarom je eigen test je misleidt", "Drie dingen zitten in de weg. Ten eerste onthoudt een assistent wat je eerder besproken hebt, dus als jij al eens over je eigen winkel praatte, is de kans groot dat hij hem noemt om jou een plezier te doen. Ten tweede verschillen antwoorden van dag tot dag en van gebruiker tot gebruiker. En ten derde stel je onbewust de vraag waarvan je hoopt dat je erop scoort."),
            ("", "Het gevolg is dat je eigen test bijna altijd te positief uitvalt. Je vraagt het een keer, je staat erin, en je concludeert dat het goed zit."),
            ("Hoe je het wel doet", "Drie regels maken het verschil. Stel meerdere verschillende vragen, niet een. Stel ze zonder eerdere gesprekken, in een leeg venster of via de API. En schrijf de vragen op zoals een koper ze zou stellen, niet zoals jij ze zou stellen."),
            ("", "Een koper vraagt niet 'is winkel X goed'. Hij vraagt 'waar koop ik een goede regenjas voor op de fiets' en noemt jouw naam helemaal niet. Precies daar wil je weten of je in het antwoord staat."),
            ("Tel per vraag, niet per antwoord", "Nog iets waar je jezelf mee voor de gek kan houden. Als je dezelfde vraag aan twee assistenten stelt en je staat in allebei de antwoorden, dan is dat een vraag waarbij je genoemd wordt en niet twee. Reken je per antwoord, dan lijkt je uitkomst twee keer zo goed als hij is."),
            ("Genoemd is niet aanbevolen", "Let ten slotte op het verschil tussen erin voorkomen en aangeraden worden. 'Je kan ook eens bij X kijken' is iets anders dan 'de regenjassen van X zijn de beste keuze'. Alleen het tweede levert klanten op."),
            ("", "Wil je dit niet handmatig doen, dan kan je op krillo.nl een gratis test draaien. Wij bedenken vijf koopvragen op basis van wat jij verkoopt, stellen die zonder voorgeschiedenis aan AI, en laten zien bij hoeveel vragen je genoemd werd en wie er nog meer stond."),
        ],
    },
    {
        "slug": "genoemd-versus-aanbevolen",
        "titel": "Genoemd worden is niet hetzelfde als aanbevolen worden",
        "samenvatting": "In een AI-antwoord staan is leuk, maar het verschil tussen erbij staan en aangeraden worden bepaalt of er iemand koopt.",
        "datum": "2026-08-22",
        "leestijd": "4 minuten",
        "inhoud": [
            ("", "Stel, iemand vraagt aan een AI-assistent waar hij goed keukengerei kan kopen. Het antwoord noemt vijf winkels. Jij staat erbij. Goed nieuws, zou je denken."),
            ("", "Maar lees hoe je erbij staat. 'Er zijn ook kleinere aanbieders zoals jouwwinkel.nl' is iets heel anders dan 'voor pannen die lang meegaan is jouwwinkel.nl de beste keuze'. In het eerste geval ben je een voetnoot. In het tweede geval ben je het advies."),
            ("Vier niveaus", "Het loopt ongeveer zo op. Je komt helemaal niet voor. Je wordt genoemd als een van meerdere opties. Je wordt genoemd met een reden erbij. Of een concreet product van jou wordt aangeraden."),
            ("", "Dat laatste is verreweg het meest waard. Iemand die te horen krijgt dat een specifiek product bij jou goed is, hoeft niets meer uit te zoeken. Iemand die jouw naam in een rijtje van vijf ziet, klikt meestal op de eerste."),
            ("Waarom shops hierin blijven hangen", "Genoemd worden gaat vaak vanzelf zodra een assistent je site kan lezen en begrijpt wat je verkoopt. Aanbevolen worden vraagt meer: dan moet er ergens iets staan waaruit blijkt waaróm jij een goede keuze bent. Een duidelijke reden, een specialisme, een productbeschrijving die verder gaat dan afmetingen en kleur."),
            ("", "Assistenten leunen daarbij niet alleen op je eigen site. Ze pakken ook op wat elders over je geschreven staat: vergelijkingen, blogs, fora, recensies. Sta je nergens buiten je eigen site, dan is er weinig waar een aanbeveling op kan rusten."),
            ("Wat je hiermee doet", "Kijk niet alleen of je voorkomt, maar hoe. Zoek in het antwoord het zinnetje waarin je genoemd wordt en lees het letterlijk. Staat er een reden bij? Nee? Dan weet je waar je aan moet werken, en dat is iets anders dan meer content maken."),
            ("", "Op krillo.nl meten we dit verschil apart. Je ziet niet alleen bij hoeveel vragen je genoemd werd, maar ook bij hoeveel je echt aanbevolen werd, met de zin erbij waarop dat gebaseerd is."),
        ],
    },
    {
        "slug": "llms-txt-nodig-of-niet",
        "titel": "Heb je llms.txt nodig voor je webshop?",
        "samenvatting": "Er wordt veel over geschreven, maar het eerlijke antwoord is genuanceerder dan ja of nee. Wat het is, wat het doet, en wat er belangrijker is.",
        "datum": "2026-08-22",
        "leestijd": "4 minuten",
        "inhoud": [
            ("", "Als je je verdiept in AI-zichtbaarheid kom je al snel llms.txt tegen, meestal met de boodschap dat je het echt moet hebben. Het eerlijke antwoord is minder stellig, en het lijkt ons nuttiger om dat gewoon te zeggen."),
            ("Wat het is", "llms.txt is een tekstbestand dat je op je website zet, net als robots.txt. Erin staat in gewone taal wat je site is, wat de belangrijkste pagina's zijn en waar een AI-assistent moet beginnen met lezen. Het idee is dat een assistent dan niet hoeft te raden wat belangrijk is."),
            ("Wat het wel doet", "Het kost je een half uur en het kan geen kwaad. Het dwingt je bovendien om in twee alinea's op te schrijven wat je verkoopt en voor wie, en dat is een nuttige oefening op zich. Veel webshops kunnen die vraag verrassend slecht beantwoorden."),
            ("Wat het niet doet", "Het is geen officiële standaard die alle assistenten volgen, en er is geen garantie dat het gelezen wordt. Wie belooft dat je met llms.txt in AI-antwoorden komt, belooft iets wat hij niet kan waarmaken."),
            ("", "Belangrijker is de basis eronder. Laat je site AI-robots binnen? Staat je tekst gewoon in de pagina, of wordt hij pas later opgebouwd? Kan een machine zien wat een product is en wat het kost? Als daar iets misgaat, verandert een llms.txt daar niets aan."),
            ("De volgorde die wij zouden aanhouden", "Eerst controleren of robots binnen mogen. Dan controleren of je belangrijkste tekst direct leesbaar is. Dan je productinformatie machine-leesbaar maken. Dan een goede vragensectie. En dan pas, als bonus, llms.txt."),
            ("", "Op krillo.nl controleren we alle dertien punten gratis, en llms.txt is er daar een van. Je ziet meteen welke ervan bij jou het meeste opleveren, in plaats van dat je begint bij het punt waar toevallig het meest over geschreven wordt."),
        ],
    },
]


def get_artikel(slug):
    for artikel in ARTIKELEN:
        if artikel["slug"] == slug:
            return artikel
    return None
