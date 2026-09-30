"""Het commandocentrum (stap 172, 29 september): alle agents op een plek.

WAAROM DIT BESTAAT. Nino: "een plek om alle agents te zien en te sturen,
geavanceerd, geen losse statische pagina's". Tot nu toe had elke agent zijn
eigen beheerpagina, en aan- of uitzetten kon alleen met een variabele in Render
(en een herstart). Nu:
- per agent: wat hij doet, of hij aan staat, wat hij de laatste 24 uur deed,
  wat de laatste ronde zei (of zijn fout), en een link naar zijn eigen pagina;
- een schakelaar per agent die METEEN werkt: de uurronde vraagt aan(sleutel)
  voordat hij de agent laat draaien. Opgeslagen in de database, dus zonder
  herstart en zonder Render;
- bovenaan wat er op Nino wacht (dezelfde lijst als het ochtendbericht);
- de laatste rondes onder elkaar, met wat er misging.
Dezelfde gegevens komen als JSON uit /api/agents, zodat Claude in de Claude-app
later precies hetzelfde kan lezen en dezelfde knoppen kan bedienen (stap 150).

Wat NIET via deze schakelaars gaat: de koude mail zelf (die heeft zijn eigen
aan/uit en volume op /admin/benadering) en de nachtelijke metingen.
"""
import json
import os

import db

SLEUTEL = "agents_uit"

# (sleutel, naam, wat hij doet, sleutel in agentwereld, sleutel in het rondeverslag,
#  schakelaar in Render die hem ook uitzet, eigen pagina)
AGENTS = [
    ("verkoop", "Verkoopagent", "volgt winkels op die hun pagina als mens bekeken", "verkoop", "opvolging", None, "/admin/verkoop"),
    ("beweging", "Bewegingsagent", "mailt winkels die na de maandmeting stegen of daalden", "beweging", "beweging", None, "/admin/benadering"),
    ("badge", "Badge-agent", "feliciteert de top van elke ranglijst met een badge", "badge", "badge", None, "/admin/benadering"),
    ("bureau", "Bureauvinder", "zoekt bureaus onderaan winkels en mailt ze", "bureau", "bureaus", None, "/admin/bureaus"),
    ("klant", "Klantagenten", "houden klanten vast, Watch naar Fix, terugwinnen", "klant", "klanten", None, "/admin/bestellingen"),
    ("proef", "Proefherinnering", "herinnert proefklanten drie dagen voor het einde", None, "proef", None, "/admin/bestellingen"),
    ("plekmelding", "Plekmelding", "meldt wie zijn plek volgt als die verandert", None, "plekmelding", None, "/admin/benadering"),
    ("pers", "Persagent", "stuurt het persbericht naar de vakmedia", "pers", "pers", "PERSBERICHT_AUTO", "/admin/persbericht"),
    ("linkedin", "LinkedIn-agent", "zet drie posts per week klaar", None, "linkedin", "LINKEDINAGENT", "/admin/linkedin"),
    ("artikel", "Artikelagent", "schrijft elke dinsdag een concept-artikel met cijfers uit de index", None, "artikel", None, "/admin/artikelen"),
    ("lijstjes", "Lijstjesagent", "vraagt schrijvers van GEO-lijstjes om Krillo", "lijstjes", "lijstjes", "LIJSTJESAGENT", "/admin/lijstjes"),
    ("wachtlijst", "Wachtpost", "meldt wie op een land wacht zodra het aan staat", "wacht", "wachtlijst", None, "/admin/wachtlijst"),
]
SLEUTELS = {a[0] for a in AGENTS}


def uitgezet():
    try:
        waarde = json.loads(db.get_instelling(SLEUTEL) or "[]")
        return set(waarde) if isinstance(waarde, list) else set()
    except Exception:
        return set()


def aan(sleutel):
    """Mag deze agent draaien? Bij twijfel (database weg): ja, zoals voorheen."""
    return sleutel not in uitgezet()


def zet(sleutel, aanzetten):
    if sleutel not in SLEUTELS:
        return False
    uit = uitgezet()
    if aanzetten:
        uit.discard(sleutel)
    else:
        uit.add(sleutel)
    db.zet_instelling(SLEUTEL, json.dumps(sorted(uit)))
    return True


def _kort(waarde):
    """Wat een agent in de laatste ronde teruggaf, in een regel."""
    if waarde is None:
        return ""
    if isinstance(waarde, dict):
        delen = []
        for k, v in list(waarde.items())[:4]:
            if isinstance(v, (list, tuple)):
                v = len(v)
            elif isinstance(v, dict):
                v = "…"
            delen.append(f"{k}: {v}")
        return ", ".join(delen)
    if isinstance(waarde, (list, tuple)):
        return f"{len(waarde)} stuks"
    return str(waarde)[:120]


def overzicht(wereld=None, verslagen=None, te_doen=None):
    """Alles voor de pagina en voor /api/agents."""
    if wereld is None:
        import agentwereld
        wereld = agentwereld.stand("24 hours")
    if verslagen is None:
        import benadering
        verslagen = benadering.rondeverslagen()
    per_wereld = {a["sleutel"]: a for a in (wereld or {}).get("agents", [])}
    laatste = verslagen[0] if verslagen else {}
    fouten = " ".join(laatste.get("mislukt") or [])
    uit = uitgezet()
    agents = []
    for sleutel, naam, wat, wsleutel, vsleutel, env, pagina in AGENTS:
        w = per_wereld.get(wsleutel) or {}
        env_uit = bool(env and os.environ.get(env) == "uit")
        agents.append({
            "sleutel": sleutel, "naam": naam, "wat": wat, "pagina": pagina,
            "aan": sleutel not in uit and not env_uit,
            "env_uit": env_uit, "env": env,
            "vandaag": w.get("recent"), "totaal": w.get("totaal"),
            "laatste": _kort(laatste.get(vsleutel)),
            "fout": next((f for f in (laatste.get("mislukt") or [])
                          if f.split(":")[0] in (vsleutel, sleutel)), None) if fouten else None,
        })
    return {"agents": agents, "te_doen": te_doen or [],
            "rondes": [{"moment": r.get("moment"), "gemaild": r.get("gemaild"),
                        "mislukt": r.get("mislukt") or []} for r in verslagen[:12]],
            "klanten": (wereld or {}).get("klanten")}
