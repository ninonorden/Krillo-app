"""Sleutels van klanten versleuteld bewaren.

Waarom dit bestaat: bij WooCommerce geeft de eigenaar ons twee sleutels waarmee
je in zijn hele winkel kunt schrijven. Die horen niet leesbaar in een database
te staan. Raakt er ooit een kopie van de database weg, dan is het verschil
tussen "vervelend" en "elke klant zijn winkel kwijt" precies dit bestand.

Hoe het werkt: één hoofdsleutel in Render (KLUIS_SLEUTEL), en daarmee wordt elk
geheim versleuteld voordat het opgeslagen wordt.

Wat dit NIET is: bescherming tegen iemand die de server zelf overneemt. Die
heeft de hoofdsleutel ook. Het is bescherming tegen een gelekte database, een
back-up die ergens rondslingert, en tegen onszelf: nu kan niemand per ongeluk
een sleutel van een klant in een logregel of op een beheerpagina zetten.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets


class GeenSleutel(Exception):
    """De hoofdsleutel ontbreekt. Dan bewaren wij niets."""


def _hoofdsleutel():
    ruw = (os.environ.get("KLUIS_SLEUTEL") or "").strip()
    if len(ruw) < 32:
        raise GeenSleutel(
            "KLUIS_SLEUTEL ontbreekt of is te kort. Zet in Render een regel "
            "KLUIS_SLEUTEL met minstens 32 willekeurige tekens. Zonder die "
            "sleutel bewaren wij geen sleutels van klanten.")
    return hashlib.sha256(ruw.encode("utf-8")).digest()


def beschikbaar():
    try:
        _hoofdsleutel()
        return True
    except GeenSleutel:
        return False


def _stroom(sleutel, zout, lengte):
    """De sleutelstroom om mee te versleutelen.

    Bewust opgebouwd uit sha256 en niet uit een kant-en-klare bibliotheek: dan
    hoeft er niets bij te komen op de server. Dit is geen eigen bedenksel maar
    de gewone tellermanier, met per blok een nieuwe hash over sleutel, zout en
    bloknummer."""
    uit = b""
    blok = 0
    while len(uit) < lengte:
        uit += hashlib.sha256(sleutel + zout + blok.to_bytes(4, "big")).digest()
        blok += 1
    return uit[:lengte]


def sluit(gegevens):
    """Versleutelt een woordenboek en geeft er één tekstregel van terug.

    Er gaat een handtekening overheen. Zonder die handtekening zou iemand met
    toegang tot de database de versleutelde tekst kunnen veranderen, en dan
    krijgen wij bij het openen iets anders terug dan er ooit in ging."""
    sleutel = _hoofdsleutel()
    klaar = json.dumps(gegevens, ensure_ascii=False).encode("utf-8")
    zout = secrets.token_bytes(16)
    stroom = _stroom(sleutel, zout, len(klaar))
    versleuteld = bytes(a ^ b for a, b in zip(klaar, stroom))
    handtekening = hmac.new(sleutel, zout + versleuteld, hashlib.sha256).digest()
    return base64.b64encode(zout + handtekening + versleuteld).decode("ascii")


def open_(regel):
    """Ontsleutelt. Geeft None terug als er iets niet klopt.

    None en geen uitzondering, want de aanroeper moet hier gewoon mee door
    kunnen: een koppeling die niet te openen is, is een koppeling die opnieuw
    gelegd moet worden. Dat is vervelend, geen ramp."""
    if not regel:
        return None
    try:
        sleutel = _hoofdsleutel()
        ruw = base64.b64decode(regel)
    except Exception:
        return None
    if len(ruw) < 48:
        return None
    zout, handtekening, versleuteld = ruw[:16], ruw[16:48], ruw[48:]
    verwacht = hmac.new(sleutel, zout + versleuteld, hashlib.sha256).digest()
    if not hmac.compare_digest(verwacht, handtekening):
        print("LET OP: een bewaard geheim klopt niet met zijn handtekening.")
        return None
    stroom = _stroom(sleutel, zout, len(versleuteld))
    try:
        return json.loads(bytes(a ^ b for a, b in zip(versleuteld, stroom)))
    except Exception:
        return None
