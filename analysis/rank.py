"""Card ranking algorithm.

Score formula per card:
  base_score = Σ (copies/playset_size) × archetype_weight × source_weight
  final_score = base_score × (1 + (archetype_count - 1) × cross_archetype_weight)

archetype_weight:
  - For Goldfish sources: metagame_pct (0-100) → normalized to sum to 1
  - For Moxfield sources: uniform weight based on views/likes rank
"""

from collections import defaultdict


def rank_cards(
    archetypes: list[dict],
    playset_size: int = 4,
    cross_archetype_weight: float = 0.2,
    min_archetype_appearances: int = 1,
) -> list[dict]:
    """
    archetypes: list of dicts with keys:
      name, metagame_pct, source (goldfish|moxfield), source_weight, cards
      cards: list of {name, quantity}

    Returns list of card dicts sorted by final_score descending.
    """
    # Normalize goldfish metagame weights separately; moxfield gets rank-based weight
    goldfish_archs = [a for a in archetypes if a.get("source", "goldfish") == "goldfish"]
    moxfield_archs = [a for a in archetypes if a.get("source") == "moxfield"]

    total_pct = sum(a["metagame_pct"] for a in goldfish_archs) or 1.0

    def arch_weight(arch: dict) -> float:
        if arch.get("source") == "moxfield":
            return arch.get("source_weight", 0.8)
        # Goldfish: weight by meta share, floor at 0.5% to include fringe decks
        pct = max(arch["metagame_pct"], 0.5)
        return (pct / total_pct) * 100 * arch.get("source_weight", 1.0)

    card_scores: dict[str, float] = defaultdict(float)
    card_archetypes: dict[str, set] = defaultdict(set)

    for arch in archetypes:
        w = arch_weight(arch)
        arch_label = arch["name"]
        for card in arch.get("cards", []):
            name = card["name"]
            qty = card["quantity"]
            normalized = min(qty / playset_size, 1.0)
            card_scores[name] += normalized * w
            card_archetypes[name].add(arch_label)

    results = []
    for name, base_score in card_scores.items():
        arch_count = len(card_archetypes[name])
        if arch_count < min_archetype_appearances:
            continue
        bonus = 1.0 + (arch_count - 1) * cross_archetype_weight
        final_score = base_score * bonus
        results.append({
            "name": name,
            "base_score": round(base_score, 4),
            "final_score": round(final_score, 4),
            "archetype_count": arch_count,
            "archetypes": sorted(card_archetypes[name]),
        })

    results.sort(key=lambda c: c["final_score"], reverse=True)
    return results
