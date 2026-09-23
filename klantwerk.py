"""Het beeld van een klant uit de maandmeting van zijn categorie.

WAAROM DIT BESTAAT (stap 72, 23 september)

Tot nu toe kwam alles wat een klant op zijn dashboard ziet uit een EIGEN
meting: dertig koopvragen, alleen voor hem. Die draaide bij de start van zijn
abonnement en daarna nooit meer, want de wekelijkse eigen meting is er op 21
september uitgehaald (stap 66, die botste met de index). Gevolg: zijn
oplossingen, de vragen die hij mist en de winkels die boven hem staan bleven
voor altijd staan op de dag dat hij klant werd. Voor Fix is dat de kern van
het product: elke maand de drie dingen die het meeste opleveren.

De oplossing is niet zijn eigen meting terugzetten, want dan meten we dezelfde
vragen twee keer en betalen we twee keer. De MAANDMETING VAN ZIJN CATEGORIE
stelt namelijk precies die dertig koopvragen al, voor alle winkels tegelijk.
Wat er ontbrak was de vertaalslag: van "wat zei AI in deze categorie" naar
"wat betekent dat voor deze ene winkel".

Dat is wat dit bestand doet. Het kost geen enkele modelaanroep: de antwoorden
zijn al gelezen en bewaard, hier wordt alleen gekoppeld en weggeschreven.

WAT ER NIET IN ZIT, en waarom dat eerlijk moet blijven staan:
- soort_vermelding (wordt je winkel genoemd of je product). Het leesmodel van
  de categorie geeft dat niet terug; dat blijft leeg tot de leesopdracht dat
  ook doet.
- de toon van de vermelding. Zelfde reden.
Het bewijs (de zin waarin je genoemd wordt) komt er wel bij, en dat kost
niets: die zin staat in het bewaarde antwoord.
"""

import re

import categoriemeting
import db

# Hoeveel tekens van een zin we als bewijs bewaren. Een hele alinea is geen
# bewijs meer maar een lap tekst, en de kolom is niet oneindig.
BEWIJS_MAX = 300


def _zin_met_naam(antwoord, naam):
    """De eerste zin uit het antwoord waarin deze winkel genoemd wordt.

    Waarom dit lokaal mag: we zoeken een naam die het leesmodel al uit dit
    antwoord gehaald heeft, dus hij staat er gegarandeerd in. Er wordt niets
    geraden en er gaat geen vraag naar een model.

    Geeft None als de naam net anders gespeld in de tekst staat dan in de
    lijst. Liever geen bewijs dan een willekeurige zin."""
    if not antwoord or not naam:
        return None
    # Splitsen op zinseinde, maar ook op opsommingstekens en regeleindes: AI
    # antwoordt vaak in lijstjes, en dan is "de zin" een regel.
    stukken = re.split(r"(?<=[.!?])\s+|\n+", str(antwoord))
    laag = naam.lower()
    for stuk in stukken:
        if laag in stuk.lower():
            schoon = " ".join(stuk.split())
            return schoon[:BEWIJS_MAX] or None
    return None


def beoordelingen_uit_ronde(ronde, categorie, winkels=None):
    """Zet de antwoorden van een meetronde om in beoordelingen per klant.

    winkels is de lijst waarvoor dat gebeurt: [{"webshop_url": ...}, ...].
    Standaard zijn dat de lopende klanten in deze categorie. Er wordt dus
    alleen werk gemaakt voor wie ervoor betaalt.

    Geeft terug hoeveel klanten en hoeveel regels het opleverde. Bestaat een
    regel al (dezelfde ronde, dezelfde winkel, hetzelfde antwoord), dan
    verandert er niets: een tweede keer draaien is veilig."""
    verslag = {"klanten": 0, "regels": 0, "ronde": ronde}
    if not ronde:
        return verslag
    if winkels is None:
        winkels = db.klanten_in_categorie(categorie)
    winkels = [w for w in winkels if w.get("webshop_url")]
    verslag["klanten"] = len(winkels)
    if not winkels:
        return verslag

    antwoorden = db.antwoorden_met_tekst_van_ronde(ronde)
    if not antwoorden:
        return verslag

    meting_id = f"cat-{ronde}"
    rijen = []
    for a in antwoorden:
        genoemde = {
            "winkels": (a.get("genoemde_winkels") or {}).get("winkels") or [],
            "aanbevolen": (a.get("genoemde_winkels") or {}).get("aanbevolen") or [],
        }
        koppeling = categoriemeting.koppel_aan_winkels(genoemde, winkels)
        namen = [w.get("naam") for w in genoemde["winkels"] if w.get("naam")]
        for winkel in winkels:
            url = winkel["webshop_url"]
            hoe = koppeling.get(url) or {}
            rijen.append({
                # Het kenmerk van het antwoord plus de winkel: hetzelfde
                # antwoord levert voor elke klant een eigen regel op. Vandaar
                # dat beoordelingen sinds vandaag uniek is op die twee samen
                # en niet meer op het antwoord alleen.
                "antwoord_id": a["id"],
                "meting_id": meting_id,
                "webshop_url": url,
                "vraag": a.get("vraag"),
                "intentie": None,
                "model": a.get("model"),
                "winkel_kon_genoemd": bool(a.get("winkel_kon_genoemd")),
                "genoemd": bool(hoe.get("genoemd")),
                "positie": hoe.get("positie"),
                "aantal_winkels": len(namen),
                "aanbevolen": bool(hoe.get("aanbevolen")),
                # Toon en soort vermelding komen niet uit de leesopdracht van
                # de categorie. Leeg laten in plaats van verzinnen.
                "toon": None,
                "soort_vermelding": None,
                "bewijs": (_zin_met_naam(a.get("antwoord"), hoe.get("als_naam"))
                           if hoe.get("genoemd") else None),
                "winkels": genoemde["winkels"],
                "merken": [],
                "aanbevolen_winkels": genoemde["aanbevolen"],
                "bron": "categorie",
            })

    verslag["regels"] = db.bewaar_beoordelingen_veel(rijen)
    return verslag
