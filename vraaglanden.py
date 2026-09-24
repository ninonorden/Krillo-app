"""Landen die hun EIGEN koopvragen krijgen (stap 76, 24 september).

WAAROM DIT BESTAND BESTAAT

Tot vandaag werd elke categorie gemeten met Nederlandse vragen ("welke
Nederlandse webshop..."), en kwam de Belgische ranglijst uit diezelfde
antwoorden: alleen de Belgische winkels bleven staan. Maar een Belgische koper
vraagt naar een Belgische webshop, en krijgt dan andere winkels te horen.
Een Belgische ranglijst uit Nederlandse vragen meet dus niet wat een
Belgische koper ziet.

Nu krijgt een land hier zijn eigen vragen. De vragen worden automatisch
bedacht (categoriemeting.bedenk_vragen, met de landnaam en de taal van
hieronder), gesnoeid en aangevuld zoals de Nederlandse. Een nieuw land is dus
een regel hier, en verder niets: de nachtronde pakt het vanzelf op zodra er
genoeg winkels van dat land in een categorie zitten.

Nederland staat hier NIET in: dat is de gewone ronde (land leeg in de
database). Duitsland, Frankrijk en de rest komen er pas bij als er winkels
van die landen in de lijst staan; een ronde zonder winkels meet niets en kost
wel geld.

Per land:
- landnaam: het bijvoeglijk naamwoord zoals het in een Nederlandse zin staat
  ("welke Belgische webshop"); zo wordt het in de opdracht gebruikt.
- taal: in welke taal de koper de vraag typt. Belgie: Nederlands, want de
  winkels in onze lijst zijn Vlaams. Franstalig Belgie is een apart land
  waard zodra daar winkels voor zijn.
"""

VRAAGLANDEN = {
    "be": {"landnaam": "Belgische", "taal": "Nederlands (zoals in Vlaanderen)"},
}


def heeft_eigen_vragen(land):
    return (land or "").lower() in VRAAGLANDEN


def vraagsleutel(slug, land=None):
    """Onder welke naam de vragen en antwoorden van een land bewaard worden.

    De vragen staan per categorie in de database. Belgische vragen onder
    "speelgoed@be" en de gewone onder "speelgoed": zo werken het aanvullen, het
    snoeien van zwakke vragen en het tellen per vraag voor elk land apart,
    zonder dat die code iets van landen hoeft te weten. De ranglijst zelf
    blijft onder "speelgoed" staan, want de pagina is /index/be/speelgoed."""
    land = (land or "").lower()
    return f"{slug}@{land}" if land in VRAAGLANDEN else slug


def hoort_bij_ronde(winkel_land, ronde_land, eigen_landen):
    """Hoort een winkel bij deze ronde, voor berichten en klantwerk?

    - Een ronde van een land (ronde_land = "be"): alleen winkels van dat land.
      De ronde scoort alle winkels van de categorie, maar een Nederlandse
      klant hoort geen bericht te krijgen over zijn plek bij Belgische vragen.
    - De gewone ronde: iedereen, BEHALVE winkels uit een land dat voor deze
      categorie al een eigen ronde heeft. Die krijgen hun cijfer daaruit, en
      anders krijgt een Belgische klant twee berichten per maand met twee
      verschillende posities."""
    winkel_land = (winkel_land or "").lower()
    if ronde_land:
        return winkel_land == ronde_land.lower()
    return winkel_land not in {(l or "").lower() for l in (eigen_landen or ())}
