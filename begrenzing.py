"""Een plafond op elk antwoord van een andere site (15 oktober 2026).

WAAROM. Op 15 oktober ging de dienst vanaf 2 uur 's nachts elk uur over de
512 MB van Render. De geheugenlog van de uurronde wees het aan: 157 MB na de
klantmails, en zes seconden later dood. De stap daarna zoekt mailadressen op de
sites van winkels (homepage, contactpagina's, sitemap.xml). Geen enkel verzoek
had een maximale grootte: requests leest standaard het HELE antwoord in het
geheugen, en pakt ingepakte (gzip) antwoorden ook nog uit. Een winkel met een
sitemap van honderden MB, of een site die een groot bestand terugstuurt, blies
het geheugen in seconden op. En omdat de dienst omviel voordat die winkel als
"bekeken" stond, kwam dezelfde winkel elk uur weer aan de beurt.

Wat dit doet: elk verzoek via requests (ook requests.get en requests.post) wordt
in stukjes gelezen, en na MAX_ANTWOORD_BYTES (uitgepakt) stoppen we. De rest van
het antwoord wordt nooit opgehaald. Een webpagina, een sitemap of een antwoord
van een AI-model is ruim kleiner dan dat; alleen wat toch al onbruikbaar groot
was, wordt afgekapt. Wie zelf stream=True vraagt, regelt het zelf en blijft
ongemoeid.

Wordt een keer aangezet (zet_aan), bovenaan app.py, voordat er iets ophaalt.
"""
import os

import requests

MAX_ANTWOORD_BYTES = int(os.environ.get("MAX_ANTWOORD_BYTES", str(5 * 1024 * 1024)))
_stand = {"aan": False, "afgekapt": 0}
_origineel = requests.sessions.Session.request


def _begrensd(self, method, url, *args, **kwargs):
    if kwargs.get("stream"):
        return _origineel(self, method, url, *args, **kwargs)
    kwargs["stream"] = True
    antwoord = _origineel(self, method, url, *args, **kwargs)
    stukken, totaal, afgekapt = [], 0, False
    try:
        # iter_content pakt gzip uit: het plafond geldt dus voor wat er echt in
        # het geheugen komt, ook bij een klein ingepakt bestand dat enorm uitpakt.
        for stuk in antwoord.iter_content(64 * 1024):
            stukken.append(stuk)
            totaal += len(stuk)
            if totaal > MAX_ANTWOORD_BYTES:
                afgekapt = True
                break
    finally:
        if afgekapt:
            antwoord.close()
    inhoud = b"".join(stukken)
    antwoord._content = inhoud[:MAX_ANTWOORD_BYTES] if afgekapt else inhoud
    antwoord._content_consumed = True
    if afgekapt:
        _stand["afgekapt"] += 1
        print(f"BEGRENZING: antwoord van {str(url)[:120]} afgekapt op "
              f"{MAX_ANTWOORD_BYTES // (1024 * 1024)} MB (groter dan toegestaan).")
    return antwoord


def zet_aan():
    if _stand["aan"]:
        return
    requests.sessions.Session.request = _begrensd
    _stand["aan"] = True
