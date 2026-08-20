Krillo
======

Lokaal draaien:
1. pip install -r requirements.txt
2. python3 app.py
3. Ga naar http://127.0.0.1:5000 in je browser
4. Vul een webshop-URL in en klik op "Scan gratis"

Bestanden:
- app.py            Webserver (Flask): pagina's, API, webhook, achtergrondtaken
- scan_engine.py    De 13 controlepunten van de gratis scan
- ai_content.py     De AI-teksten voor de betaalde audit
- koopvragen.py     Bedenkt per webshop de koopvragen en zoekt dubbelingen
- metingen.py       Stelt die koopvragen aan de AI-modellen en bewaart de antwoorden
- kosten.py         Prijzen per model, kostenberekening en de kostenrem
- db.py             Alle databasefuncties (Neon Postgres)
- emailing.py       Alle e-mail via de Brevo API
- payments.py       Mollie: betalingen, abonnementen, opzeggen
- artikelen.py      De artikelen als Python-lijst
- templates/        Alle pagina's
- static/           Favicon en deelafbeelding

Omgevingsvariabelen (in Render):
  Nodig: ANTHROPIC_API_KEY, BREVO_API_KEY, MOLLIE_API_KEY, DATABASE_URL,
         CRON_KEY, ADMIN_KEY, BEHEERDER_EMAIL
  Voor de metingen: OPENAI_API_KEY, GOOGLE_API_KEY
  Optioneel: BTW_REGELING, GRENS_PER_SCAN_EURO, GRENS_PER_SCAN_AANROEPEN,
         GRENS_PER_KLANT_MAAND_EURO, GRENS_TOTAAL_DAG_EURO, MAX_POGINGEN,
         METINGEN_AAN, MEET_MODEL_OPENAI, MEET_MODEL_GOOGLE,
         MEET_MODEL_ANTHROPIC, MEET_VRAGEN_PER_RONDE, MEET_MAX_TOKENS

Beheerpagina's (alleen met ?key=ADMIN_KEY, zonder sleutel geven ze 404):
- /admin/bestellingen   Betaalde bestellingen uit Mollie
- /admin/koopvragen     Koopvragen genereren, beoordelen en ontdubbelen
- /admin/metingen       De antwoorden van de AI-modellen op die koopvragen
- /admin/kosten         AI-kosten per klant en per model
