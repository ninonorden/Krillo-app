"""De Anthropic-bibliotheek pas laden als hij echt nodig is (15 oktober 2026).

WAAROM. `import anthropic` kost 1,2 seconde en tientallen MB geheugen, en
zeven modules deden dat bij het starten, ook als er die dag geen enkele
modelvraag gesteld werd. Elke herstart van Render (en elke test) betaalde dat.
Nu wordt hij pas geladen bij de eerste anthropic.Anthropic(...). Gebruik:
    from lui_anthropic import anthropic
Daarna werkt alles zoals voorheen, ook een test die anthropic.Anthropic
vervangt door een nep-versie.
"""


class _Lui:
    def __getattr__(self, naam):
        import anthropic as echt
        return getattr(echt, naam)


anthropic = _Lui()
