Surfaced - lokale ontwikkelversie
==================================

Starten:
1. pip install -r requirements.txt
2. python3 app.py
3. Ga naar http://127.0.0.1:5000 in je browser
4. Vul een echte website-URL in en klik op "Scan gratis"

Structuur:
- app.py            De webserver (Flask) die de pagina toont en de scan-API aanbiedt
- scan_engine.py     De scan-logica: robots.txt, leesbaarheid, productinfo, basis-check
- templates/index.html   De landingspagina, nu gekoppeld aan de echte scan
- static/            Leeg, voor toekomstige eigen afbeeldingen/bestanden

Volgende stappen die logisch volgen:
- Laag 3 toevoegen (checken of AI-modellen de shop al noemen) aan scan_engine.py
- De betaalde audit en het abonnement bouwen
- Hosten op een dienst als Render, Railway of Fly.io zodat het écht online staat
