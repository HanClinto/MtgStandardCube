"""Color-balance a ranked card list into a cube."""

from utils.scryfall import get_cards_metadata, color_category


def build_cube(
    ranked_cards: list[dict],
    color_slots: dict[str, int],
    use_cache: bool = True,
) -> dict[str, list[dict]]:
    """
    Select cards from ranked_cards to fill color_slots.

    color_slots keys: white, blue, black, red, green, multicolor, artifact, land

    Returns dict keyed by color category, each value a list of card dicts
    (includes ranking info + scryfall metadata).
    """
    card_names = [c["name"] for c in ranked_cards]
    print(f"[color_balance] Fetching Scryfall metadata for {len(card_names)} cards...")
    metadata = get_cards_metadata(card_names, use_cache=use_cache)

    # Enrich ranked cards with metadata and category
    enriched: list[dict] = []
    for card in ranked_cards:
        meta = metadata.get(card["name"])
        if meta is None:
            continue
        category = color_category(meta)
        enriched.append({**card, **meta, "color_category": category})

    # Sort each category bucket by final_score and pick top N
    buckets: dict[str, list[dict]] = {cat: [] for cat in color_slots}
    for card in enriched:
        cat = card["color_category"]
        if cat in buckets:
            buckets[cat].append(card)
        elif cat == "colorless":
            buckets.setdefault("artifact", []).append(card)

    cube: dict[str, list[dict]] = {}
    for cat, limit in color_slots.items():
        candidates = sorted(buckets.get(cat, []), key=lambda c: c["final_score"], reverse=True)
        cube[cat] = candidates[:limit]

    total = sum(len(v) for v in cube.values())
    print(f"[color_balance] Cube assembled: {total} cards")
    for cat, cards in cube.items():
        print(f"  {cat:12s}: {len(cards):3d} / {color_slots[cat]}")

    return cube


def flatten_cube(cube: dict[str, list[dict]]) -> list[dict]:
    """Flatten cube dict into a single sorted list."""
    order = ["white", "blue", "black", "red", "green", "multicolor", "artifact", "land"]
    rows = []
    for cat in order:
        for card in cube.get(cat, []):
            rows.append({**card, "color_category": cat})
    return rows
