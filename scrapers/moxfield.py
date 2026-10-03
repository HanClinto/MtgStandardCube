"""Moxfield public API scraper for Standard decklists."""

import time
import json
import requests
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path("data/cache")
SEARCH_URL = "https://api2.moxfield.com/v2/decks/search"
DECK_URL = "https://api2.moxfield.com/v3/decks/all/{public_id}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.moxfield.com/",
    "Origin": "https://www.moxfield.com",
}

COLOR_COMBO_NAMES = {
    frozenset(["W"]): "White",
    frozenset(["U"]): "Blue",
    frozenset(["B"]): "Black",
    frozenset(["R"]): "Red",
    frozenset(["G"]): "Green",
    frozenset(["W", "U"]): "Azorius",
    frozenset(["W", "B"]): "Orzhov",
    frozenset(["W", "R"]): "Boros",
    frozenset(["W", "G"]): "Selesnya",
    frozenset(["U", "B"]): "Dimir",
    frozenset(["U", "R"]): "Izzet",
    frozenset(["U", "G"]): "Simic",
    frozenset(["B", "R"]): "Rakdos",
    frozenset(["B", "G"]): "Golgari",
    frozenset(["R", "G"]): "Gruul",
    frozenset(["W", "U", "B"]): "Esper",
    frozenset(["W", "U", "R"]): "Jeskai",
    frozenset(["W", "U", "G"]): "Bant",
    frozenset(["W", "B", "R"]): "Mardu",
    frozenset(["W", "B", "G"]): "Abzan",
    frozenset(["W", "R", "G"]): "Naya",
    frozenset(["U", "B", "R"]): "Grixis",
    frozenset(["U", "B", "G"]): "Sultai",
    frozenset(["U", "R", "G"]): "Temur",
    frozenset(["B", "R", "G"]): "Jund",
    frozenset(["W", "U", "B", "R"]): "Yore-Tiller",
    frozenset(["W", "U", "B", "G"]): "Witch-Maw",
    frozenset(["W", "U", "R", "G"]): "Ink-Treader",
    frozenset(["W", "B", "R", "G"]): "Dune-Brood",
    frozenset(["U", "B", "R", "G"]): "Glint-Eye",
    frozenset(["W", "U", "B", "R", "G"]): "5-Color",
}


def get_all_decklists(
    use_cache: bool = True,
    cache_ttl_hours: float = 24,
    page_size: int = 64,
    max_pages: int = 5,
    sort_type: str = "views",
    min_cards: int = 58,
) -> list[dict]:
    """Return archetypes inferred from top Moxfield Standard decklists."""
    decks = _search_decks(
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
        page_size=page_size,
        max_pages=max_pages,
        sort_type=sort_type,
    )

    result = []
    for deck_meta in decks:
        pub_id = deck_meta.get("publicId") or deck_meta.get("public_id")
        if not pub_id:
            continue
        try:
            cards, colors = _get_deck_cards(
                pub_id, use_cache=use_cache, cache_ttl_hours=cache_ttl_hours
            )
            total_qty = sum(c["quantity"] for c in cards)
            if total_qty < min_cards:
                continue
            archetype = _infer_archetype(deck_meta, colors)
            result.append({
                "name": archetype,
                "slug": f"moxfield_{pub_id}",
                "metagame_pct": 0.0,  # Moxfield doesn't give meta share
                "source": "moxfield",
                "deck_name": deck_meta.get("name", ""),
                "views": deck_meta.get("viewCount", 0),
                "likes": deck_meta.get("likeCount", 0),
                "cards": cards,
            })
        except Exception as exc:
            print(f"[moxfield] Skipping {pub_id}: {exc}")

    print(f"[moxfield] Loaded {len(result)} decklists")
    return result


def _search_decks(
    use_cache: bool,
    cache_ttl_hours: float,
    page_size: int,
    max_pages: int,
    sort_type: str,
) -> list[dict]:
    cache_file = CACHE_DIR / f"moxfield_search_{sort_type}_{max_pages}.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        age_h = (datetime.now().timestamp() - data["scraped_at"]) / 3600
        if age_h < cache_ttl_hours:
            print(f"[moxfield] Using cached search results ({age_h:.1f}h old)")
            return data["decks"]

    all_decks: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "pageNumber": page,
            "pageSize": page_size,
            "sortType": sort_type,
            "sortDirection": "descending",
            "fmt": "standard",
            "board": "mainboard",
        }
        print(f"[moxfield] Fetching search page {page}/{max_pages}")
        resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        decks = data.get("data", [])
        if not decks:
            break
        all_decks.extend(decks)
        time.sleep(0.5)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"scraped_at": datetime.now().timestamp(), "decks": all_decks}, indent=2)
    )
    print(f"[moxfield] Found {len(all_decks)} decks")
    return all_decks


def _get_deck_cards(
    public_id: str, use_cache: bool, cache_ttl_hours: float
) -> tuple[list[dict], list[str]]:
    cache_file = CACHE_DIR / f"moxfield_deck_{public_id}.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        age_h = (datetime.now().timestamp() - data["scraped_at"]) / 3600
        if age_h < cache_ttl_hours:
            return data["cards"], data["colors"]

    url = DECK_URL.format(public_id=public_id)
    time.sleep(0.3)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    deck = resp.json()

    mainboard = deck.get("boards", {}).get("mainboard", {}).get("cards", {})
    cards = []
    for entry in mainboard.values():
        qty = entry.get("quantity", 0)
        card = entry.get("card", {})
        name = card.get("name", "")
        if name and qty:
            cards.append({"name": name, "quantity": qty, "sideboard": False})

    colors = deck.get("colorIdentity", [])

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {"scraped_at": datetime.now().timestamp(), "cards": cards, "colors": colors},
            indent=2,
        )
    )
    return cards, colors


def _infer_archetype(deck_meta: dict, colors: list[str]) -> str:
    """Derive a human-readable archetype label from deck name + colors."""
    color_name = COLOR_COMBO_NAMES.get(frozenset(colors), "Colorless")
    deck_name = deck_meta.get("name", "").strip()

    keywords = ["control", "aggro", "midrange", "combo", "tempo", "ramp", "reanimator", "burn"]
    for kw in keywords:
        if kw.lower() in deck_name.lower():
            return f"{color_name} {kw.capitalize()}"

    return f"{color_name} {deck_name}" if deck_name else color_name
