"""
Krillo - fase 5 stap 10: waarschuwingen die ergens over gaan.

Het risico dat in de roadmap vastligt: vermeldingen zijn niet in de hand van de
klant. Komt een concurrent groot in het nieuws of wordt een AI-model
bijgewerkt, dan zakt een klant van vier naar twee zonder dat hij iets fout deed.
Hij ziet een dalende grafiek op een dienst waar hij voor betaalt en zegt op.

Een kale melding "je bent gedaald" maakt dat erger. Daarom staat er bij elke
daling of het aan hem lag of aan de markt. Dat is af te leiden uit de meting
zelf: daalt iedereen, dan is het de markt of het model. Daalt alleen hij
terwijl een concurrent stijgt, dan is er iets veranderd in zijn voordeel of
nadeel en is er wel iets te doen.

Bewust geen agent maar een vast rekenmodel. De vergelijking tussen twee rondes
ligt vast en is elke keer hetzelfde, dus daar hoort geen AI bij die er kosten
en onvoorspelbaarheid aan toevoegt. De echte trend-analyse over langere tijd
staat in fase 6.
"""

from datetime import datetime, timezone

# Onder dit verschil melden we niets. Een vermelding heen of weer is ruis:
# AI-antwoorden verschillen van dag tot dag zonder dat er iets veranderd is.
DREMPEL = int(__import__("os").environ.get("WAARSCHUWING_DREMPEL", "2"))


def _zelfde_winkel(naam, eigen):
    """Of twee schrijfwijzen dezelfde winkel zijn. Verbindingswoorden en
    leestekens tellen niet mee."""
    import re as _re

    def plat(t):
        delen = [d for d in _re.split(r"[^a-z0-9]+", (t or "").lower().replace("&", " en ")) if d]
        return "".join(d for d in delen if d not in ("en", "and", "de", "het"))

    a, b = plat(naam), plat(eigen)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def _rondes(beoordelingen):
    """Splitst de beoordelingen op meetronde, nieuwste eerst."""
    per_ronde = {}
    for b in beoordelingen:
        meting_id = b.get("meting_id")
        if not meting_id:
            continue
        per_ronde.setdefault(meting_id, []).append(b)
    return sorted(
        per_ronde.values(),
        # datetime.min als terugval, niet None. Een ronde waarvan geen enkele
        # regel een datum heeft mag de sortering niet laten klappen; die hoort
        # gewoon achteraan.
        key=lambda regels: max(
            (r.get("beoordeeld_op") for r in regels if r.get("beoordeeld_op")),
            default=datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )


def _cijfers(regels):
    """Telt per VRAAG, niet per antwoord.

    Dit is belangrijker dan het lijkt. Doet een AI-aanbieder de ene week wel mee
    en de andere week niet, dan verdubbelt of halveert het aantal antwoorden
    terwijl er precies evenveel vragen gesteld zijn. Telden we per antwoord, dan
    zouden twee rondes daardoor als onvergelijkbaar gelden en zou een klant
    nooit te horen krijgen dat hij gestegen of gedaald is. Per vraag tellen
    maakt de vergelijking bestand tegen een aanbieder die af en toe uitvalt.

    Zeggen twee modellen iets anders over dezelfde vraag, dan telt de sterkste
    uitkomst, net als op de klantpagina."""
    per_vraag = {}
    for r in regels:
        vraag = r.get("vraag")
        if not vraag:
            continue
        regel = per_vraag.setdefault(vraag, {
            "telt_mee": False, "genoemd": False, "aanbevolen": False, "winkels": set(),
        })
        if r.get("winkel_kon_genoemd"):
            regel["telt_mee"] = True
            for w in (r.get("winkels") or []):
                naam = (w.get("naam") or "").strip()
                if naam:
                    regel["winkels"].add(naam)
        regel["genoemd"] = regel["genoemd"] or bool(r.get("genoemd"))
        regel["aanbevolen"] = regel["aanbevolen"] or bool(r.get("aanbevolen"))

    telbaar = [v for v in per_vraag.values() if v["telt_mee"]]
    winkels = {}
    for v in telbaar:
        for naam in v["winkels"]:
            winkels[naam] = winkels.get(naam, 0) + 1
    return {
        "telbaar": len(telbaar),
        "genoemd": len([v for v in telbaar if v["genoemd"]]),
        "aanbevolen": len([v for v in telbaar if v["aanbevolen"]]),
        "winkels": winkels,
    }


def vergelijk(beoordelingen, eigen_naam=None, taal="nl"):
    """Vergelijkt de laatste meetronde met de vorige.

    taal is "nl" of "en", en gaat alleen over de duiding: de zin die de klant
    leest. De cijfers, de drempel en of we iets melden zijn in beide talen
    precies gelijk. Alles wat niet "en" is wordt Nederlands.

    Geeft None terug als er nog geen twee rondes zijn, want dan valt er niets
    te vergelijken en is elke melding een verzinsel."""
    taal = "en" if taal == "en" else "nl"
    rondes = _rondes(beoordelingen)
    if len(rondes) < 2:
        return None

    nu, toen = _cijfers(rondes[0]), _cijfers(rondes[1])
    verschil = nu["genoemd"] - toen["genoemd"]
    verschil_aanbevolen = nu["aanbevolen"] - toen["aanbevolen"]

    # Twee rondes zijn alleen te vergelijken als er ongeveer evenveel vragen in
    # meetelden. Mislukte een ronde half, bijvoorbeeld doordat een aanbieder
    # dichtzat of antwoorden afgekapt werden, dan lijkt de volgende ronde een
    # enorme stijging terwijl er alleen maar meer gemeten is. Dat als winst
    # presenteren is misleidend, dus dan zeggen we niets over stijgen of dalen.
    kleinste = min(nu["telbaar"], toen["telbaar"])
    grootste = max(nu["telbaar"], toen["telbaar"])
    vergelijkbaar = bool(kleinste) and kleinste >= grootste * 0.75

    # Wie is er gestegen of gedaald, onze eigen winkel niet meegerekend.
    eigen = (eigen_naam or "").lower()
    bewegingen = []
    for naam in set(nu["winkels"]) | set(toen["winkels"]):
        # Niet op exacte gelijkheid vergelijken. Het model schrijft "Dille &
        # Kamille" waar het winkelprofiel "Dille en Kamille" zegt, en dan
        # stond de eigen winkel in zijn eigen stijgers- en dalerslijst met een
        # zin als "jij daalt terwijl Dille & Kamille stijgt".
        if _zelfde_winkel(naam, eigen):
            continue
        stap = nu["winkels"].get(naam, 0) - toen["winkels"].get(naam, 0)
        if abs(stap) >= DREMPEL:
            bewegingen.append({"naam": naam, "verschil": stap,
                               "nu": nu["winkels"].get(naam, 0)})
    # Allebei op grootte van de beweging, niet op het getal zelf. Sorteren op
    # het getal zette de dalers precies verkeerd om: -2 kwam boven -6, en dan
    # meldde het bericht de kleinste daler in plaats van de grootste.
    stijgers = sorted([b for b in bewegingen if b["verschil"] > 0],
                      key=lambda b: b["verschil"], reverse=True)
    dalers = sorted([b for b in bewegingen if b["verschil"] < 0],
                    key=lambda b: b["verschil"])

    if not vergelijkbaar:
        if taal == "en":
            onvergelijkbaar = (
                f"This measurement counted {nu['telbaar']} usable questions, the previous one "
                f"{toen['telbaar']}. That gap is too big to put the two side by side fairly, so "
                f"we are not saying yet whether you went up or down. From the next measurement on "
                f"we can."
            )
        else:
            onvergelijkbaar = (
                f"Deze meting telde {nu['telbaar']} bruikbare vragen, de vorige "
                f"{toen['telbaar']}. Dat verschil is te groot om de twee eerlijk naast elkaar te "
                f"leggen, dus we zeggen nog niet of je gestegen of gedaald bent. Vanaf de volgende "
                f"meting kan dat wel."
            )
        return {
            "nu": nu, "toen": toen, "verschil": verschil,
            "verschil_aanbevolen": verschil_aanbevolen,
            "stijgers": [], "dalers": [], "melden": False, "vergelijkbaar": False,
            "duiding": onvergelijkbaar,
        }

    return {
        "nu": nu,
        "toen": toen,
        "verschil": verschil,
        "verschil_aanbevolen": verschil_aanbevolen,
        "stijgers": stijgers[:3],
        "dalers": dalers[:3],
        "vergelijkbaar": True,
        "melden": abs(verschil) >= DREMPEL or abs(verschil_aanbevolen) >= DREMPEL,
        "duiding": _duiding(verschil, nu, toen, stijgers, dalers, taal),
    }


def _duiding_en(verschil, nu, toen, stijgers, dalers):
    """De Engelse tegenhanger van _duiding. Dezelfde gevallen, dezelfde
    volgorde, dezelfde grenzen."""
    if abs(verschil) < DREMPEL:
        return ("Your mentions stayed about the same. Small differences are normal: AI answers "
                "vary from day to day without anything having changed.")

    if verschil < 0:
        totaal_nu = sum(nu["winkels"].values())
        totaal_toen = sum(toen["winkels"].values())
        if totaal_toen and totaal_nu < totaal_toen * 0.75:
            return ("Almost every store is mentioned less this round, not just you. That points to "
                    "a change at the AI models themselves and not to something you did wrong. "
                    "Waiting to see what the next round does is the sensible thing here.")
        if stijgers:
            namen = ", ".join(s["naam"] for s in stijgers)
            return (f"You are going down while {namen} is going up. That is the most useful "
                    f"outcome: something changed in favour of those stores. Look at what they do "
                    f"differently, for example new articles or listings on comparison sites.")
        return ("You are going down without a competitor clearly going up. That can be down to a "
                "change on your own site, or to normal variation. If it drops further next round, "
                "something is really going on.")

    if dalers:
        namen = ", ".join(d["naam"] for d in dalers)
        return (f"You are going up while {namen} is going down. You have gained ground on these "
                f"stores.")
    return ("You are mentioned more often than last round. The market as a whole has not shifted, "
            "so this is a gain.")


def _duiding(verschil, nu, toen, stijgers, dalers, taal="nl"):
    """De zin die eronder hoort: lag het aan jou of aan de markt?"""
    if taal == "en":
        return _duiding_en(verschil, nu, toen, stijgers, dalers)

    if abs(verschil) < DREMPEL:
        return ("Je vermeldingen zijn ongeveer gelijk gebleven. Kleine verschillen horen "
                "erbij: AI-antwoorden wisselen van dag tot dag zonder dat er iets veranderd is.")

    if verschil < 0:
        # Daalt iedereen even hard, dan is het niet de klant maar het model.
        totaal_nu = sum(nu["winkels"].values())
        totaal_toen = sum(toen["winkels"].values())
        if totaal_toen and totaal_nu < totaal_toen * 0.75:
            return ("Bijna alle winkels worden deze ronde minder genoemd, niet alleen jij. "
                    "Dat wijst op een verandering bij de AI-modellen zelf en niet op iets wat "
                    "jij fout deed. Afwachten wat de volgende ronde doet is hier het "
                    "verstandigste.")
        if stijgers:
            namen = ", ".join(s["naam"] for s in stijgers)
            return (f"Jij daalt terwijl {namen} stijgt. Dat is de meest bruikbare uitkomst: er "
                    f"is iets veranderd in het voordeel van die winkels. Kijk wat zij anders "
                    f"doen, bijvoorbeeld nieuwe artikelen of vermeldingen op vergelijkingssites.")
        return ("Je daalt zonder dat er een concurrent duidelijk stijgt. Dat kan aan een "
                "wijziging op je eigen site liggen, of aan schommeling. Zakt het volgende ronde "
                "verder, dan is er echt iets aan de hand.")

    if dalers:
        namen = ", ".join(d["naam"] for d in dalers)
        return (f"Je stijgt terwijl {namen} daalt. Je hebt terrein gewonnen op deze winkels.")
    return ("Je wordt vaker genoemd dan vorige ronde. De markt als geheel is niet verschoven, "
            "dus dit is winst.")


def bericht(webshop_url, uitkomst, controle_samenvatting=None, taal="nl"):
    """Maakt de tekst voor de klant. Geen opsmuk, gewoon wat er veranderd is en
    wat dat betekent. Geeft None terug als er niets te melden valt.

    taal is "nl" of "en". De duiding zit al in uitkomst en hoort dan in dezelfde
    taal gemaakt te zijn, dus geef vergelijk() dezelfde taal mee.

    De woorden "gone up" en "gone down" zijn niet vrijblijvend: de mail leest de
    eerste zin om te bepalen of het goed of slecht nieuws is. Verander je ze
    hier, verander ze dan ook in emailing.send_vermeldingen_update."""
    if not uitkomst or not uitkomst["melden"]:
        if not (controle_samenvatting and controle_samenvatting.get("klopt_niet")):
            return None

    engels = taal == "en"
    regels = []
    if uitkomst and uitkomst["melden"]:
        verschil = uitkomst["verschil"]
        nu, toen = uitkomst["nu"], uitkomst["toen"]
        if engels:
            richting = "gone up" if verschil > 0 else "gone down"
            regels.append(
                f"Your mentions have {richting}: from {toen['genoemd']} to {nu['genoemd']} "
                f"of the {nu['telbaar']} questions."
            )
            if uitkomst["verschil_aanbevolen"]:
                regels.append(
                    f"You are now really recommended in {nu['aanbevolen']} questions, last round "
                    f"that was {toen['aanbevolen']}."
                )
        else:
            richting = "gestegen" if verschil > 0 else "gedaald"
            regels.append(
                f"Je vermeldingen zijn {richting}: van {toen['genoemd']} naar {nu['genoemd']} "
                f"van de {nu['telbaar']} vragen."
            )
            if uitkomst["verschil_aanbevolen"]:
                regels.append(
                    f"Je wordt nu bij {nu['aanbevolen']} vragen echt aanbevolen, vorige ronde waren "
                    f"dat er {toen['aanbevolen']}."
                )
        regels.append(uitkomst["duiding"])

    if controle_samenvatting and controle_samenvatting.get("klopt_niet"):
        aantal = controle_samenvatting["klopt_niet"]
        if engels:
            regels.append(
                f"On top of that, AI says something about your store {aantal} times that does not "
                f"match what your site says. That is on your monitoring page, with the sentence "
                f"itself."
            )
        else:
            regels.append(
                f"Daarnaast zegt AI {aantal} keer iets over je winkel dat niet klopt met wat er op "
                f"je site staat. Dat staat op je monitoringpagina, met de zin erbij."
            )

    return "\n\n".join(regels) if regels else None
