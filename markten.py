"""Welke landen de index nu meet: op EEN plek (28 september).

WAAROM DIT BESTAAT. Nino, 28 september: "het focust weer op Nederland en
Belgie, maar we gaan groeien". Overal op de site stond "for Dutch and Belgian
stores". Krillo is voor webshops, niet voor twee landen. Wat wel waar is: de
index MEET nu Nederland en Belgie. Dat is een feit dat mag blijven staan, maar
dan als "nu", met "meer landen volgen", en uit deze ene lijst. Komt Duitsland
erbij (stap 81), dan is dat hier een code in INDEX_LANDEN (of in Render) en
passen alle teksten zich aan.

REGEL VOOR NIEUWE TEKST: Krillo is "for online stores". Noem landen alleen waar
het over de meting gaat, en dan met index_landen_en() hieronder.
"""
import os

import sitetaal


def index_landen():
    """De landcodes die de index nu meet, kleine letters, in volgorde."""
    ruw = os.environ.get("INDEX_LANDEN", "nl,be")
    return tuple(c.strip().lower() for c in ruw.split(",") if c.strip())


def in_index(landcode):
    """Meet de index dit land? Een onbekend land (leeg) telt als ja: dan weten
    wij het niet, en beloven wij niets af te wijzen."""
    return not landcode or landcode.lower() in index_landen()


def _opsomming(namen, en="and"):
    if len(namen) <= 1:
        return "".join(namen)
    return ", ".join(namen[:-1]) + f" {en} " + namen[-1]


def index_landen_en():
    """'the Netherlands and Belgium', of met drie landen 'the Netherlands, Belgium and Germany'."""
    return _opsomming([sitetaal.landnaam(c, "en") for c in index_landen()])


def index_landen_nl():
    return _opsomming([sitetaal.landnaam(c, "nl") for c in index_landen()], "en")


def meting_zin_en():
    """De zin voor waar het over de meting gaat."""
    return f"The index measures {index_landen_en()} now; more countries follow."


# Landcode uit het domein. Alleen landen waarvan het domein het land zegt; een
# .com zegt niets (veel Nederlandse winkels zitten op .com), dan geen gok.
_DOMEIN_LAND = {".nl": "nl", ".be": "be", ".de": "de", ".at": "at", ".ch": "ch", ".fr": "fr",
                ".co.uk": "uk", ".uk": "uk", ".es": "es", ".it": "it", ".dk": "dk", ".se": "se",
                ".pl": "pl", ".ie": "ie", ".us": "us"}

# Landen voor de keuzelijst van de wachtlijst, met Engelse namen.
WACHTLIJST_LANDEN = {"de": "Germany", "uk": "the United Kingdom", "fr": "France", "us": "the United States",
                     "at": "Austria", "ch": "Switzerland", "es": "Spain", "it": "Italy", "dk": "Denmark",
                     "se": "Sweden", "pl": "Poland", "ie": "Ireland", "other": "another country"}


def land_uit_adres(url):
    """De landcode uit het domein, of None als het domein het land niet zegt."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url if "://" in (url or "") else f"https://{url}").netloc or "").lower().split(":")[0]
    except Exception:
        return None
    for staart in sorted(_DOMEIN_LAND, key=len, reverse=True):
        if host.endswith(staart):
            return _DOMEIN_LAND[staart]
    return None


def landnaam_en(code):
    return WACHTLIJST_LANDEN.get(code) or sitetaal.landnaam(code, "en")


def buiten_de_index(url):
    """Voor de gratis check: {"land", "naam"} als het domein een land zegt dat
    de index nog niet meet, anders None."""
    land = land_uit_adres(url)
    if not land or in_index(land):
        return None
    return {"land": land, "naam": landnaam_en(land)}
