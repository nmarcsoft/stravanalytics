KEYWORDS: dict[str, list[str]] = {
    "VMA": ["vma", "vo2", "vitesse maximale aérobie", "interval", "répét", "fractionnés"],
    "SEUIL": ["seuil", "threshold", "tempo", "lactate", "allure seuil"],
    "EF": [
        "ef", "endurance fondamentale", "sortie longue", "fondamental",
        "récup", "recovery", "footing", "z2", "zone 2",
    ],
}


def classify(name: str, description: str | None = None) -> str:
    text = f"{name} {description or ''}".lower()
    for session_type, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return session_type
    return "OTHER"
