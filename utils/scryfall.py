"""Scryfall API helpers — card metadata and bulk lookups."""

import time
import json
import requests
from pathlib import Path

CACHE_DIR = Path("data/cache")
SCRYFALL_COLLECTION_URL = "https://api.scryfall.com/cards/collection"
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
BATCH_SIZE = 75  # Scryfall collection endpoint max


def get_cards_metadata(card_names: list[str], use_cache: bool = True) -> dict[str, dict]:
    """
    Fetch color/type metadata for a list of card names from Scryfall.
    Returns a dict keyed by canonical card name.
    """
    cache_file = CACHE_DIR / "scryfall_cards.json"
    cache: dict[str, dict] = {}

    if use_cache and cache_file.exists():
        cache = json.loads(cache_file.read_text())

    missing = [n for n in card_names if n not in cache]
    if missing:
        fetched = _fetch_collection(missing)
        cache.update(fetched)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=2))

    return {n: cache[n] for n in card_names if n in cache}


def _fetch_collection(names: list[str]) -> dict[str, dict]:
    result = {}
    for i in range(0, len(names), BATCH_SIZE):
        batch = names[i : i + BATCH_SIZE]
        identifiers = [{"name": n} for n in batch]
        resp = requests.post(
            SCRYFALL_COLLECTION_URL,
            json={"identifiers": identifiers},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        for card in data.get("data", []):
            name = card["name"]
            result[name] = _extract_metadata(card)

        not_found = data.get("not_found", [])
        if not_found:
            print(f"[scryfall] {len(not_found)} cards not found: {[n['name'] for n in not_found]}")

        if i + BATCH_SIZE < len(names):
            time.sleep(0.1)

    return result


def _extract_metadata(card: dict) -> dict:
    colors = card.get("colors") or card.get("card_faces", [{}])[0].get("colors", [])
    # For split/adventure/mdfc cards, union the colors of all faces
    if "card_faces" in card:
        all_colors: set[str] = set()
        for face in card["card_faces"]:
            all_colors.update(face.get("colors", []))
        colors = sorted(all_colors)

    color_identity = card.get("color_identity", [])
    type_line = card.get("type_line", "")
    is_land = "Land" in type_line
    is_artifact = "Artifact" in type_line
    is_creature = "Creature" in type_line

    return {
        "name": card["name"],
        "colors": colors,
        "color_identity": color_identity,
        "type_line": type_line,
        "is_land": is_land,
        "is_artifact": is_artifact,
        "is_creature": is_creature,
        "cmc": card.get("cmc", 0),
        "rarity": card.get("rarity", ""),
        "set": card.get("set", ""),
        "set_name": card.get("set_name", ""),
        "scryfall_uri": card.get("scryfall_uri", ""),
    }


def color_category(metadata: dict) -> str:
    """Return the color category string for a card's metadata."""
    if metadata["is_land"]:
        return "land"
    colors = metadata["colors"]
    if len(colors) == 0:
        if metadata["is_artifact"]:
            return "artifact"
        return "colorless"
    if len(colors) == 1:
        return {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}[colors[0]]
    return "multicolor"
