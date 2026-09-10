"""Waar de app staat, vanuit welke map de test ook gedraaid wordt.

De tests stonden eerst in een losse werkmap naast een uitgepakte kopie van de
app. Nu staan ze in de app zelf, zodat in GitHub zichtbaar is wat er bewaakt
wordt. Dit bestand vangt dat verschil op, zodat geen enkele test een vast pad
hoeft te kennen."""
import os

_HIER = os.path.dirname(os.path.abspath(__file__))

for _kandidaat in (os.path.dirname(_HIER), os.path.join(_HIER, "krillo_extract")):
    if os.path.exists(os.path.join(_kandidaat, "app.py")):
        APP = _kandidaat
        break
else:
    raise RuntimeError("app.py niet gevonden vanuit " + _HIER)

TEMPLATES = os.path.join(APP, "templates")


def lees(bestandsnaam):
    """De inhoud van een bestand uit de app, als tekst."""
    return open(os.path.join(APP, bestandsnaam)).read()
