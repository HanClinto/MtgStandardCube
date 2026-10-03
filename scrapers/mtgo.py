"""MTGO Standard tournament scraper via MtgTop8.

MtgTop8 aggregates MTGO Challenge, Preliminary, and League results with
archetype labels and placement data — all sourced from mtgo.com.

Placement-based weights:
  1st: 1.0  2nd: 0.9  3-4th: 0.8  5-8th: 0.7  9-16th: 0.5  17+: 0.3

Event-tier weights:
  Challenge 32/64: 1.5   Challenge 16: 1.0   Preliminary: 0.7   League: 0.5
"""

import re
import time
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path("data/cache")
BASE_URL = "https://www.mtgtop8.com"
FORMAT_URL = f"{BASE_URL}/format?f=ST"
HEADERS = {
    "User-Agent": "MtgStandardCubeBuilder/1.0 (github.com/HanClinto/MtgStandardCube)",
    "Accept-Language": "en-US,en;q=0.9",
}

PLACEMENT_WEIGHT = {
    1: 1.0,
    2: 0.9,
    3: 0.8,
    4: 0.8,
    5: 0.7,
    6: 0.7,
    7: 0.7,
    8: 0.7,
}
PLACEMENT_DEFAULT = 0.4  # 9th and beyond


def _event_tier_weight(event_name: str) -> float:
    name = event_name.lower()
    if re.search(r"challenge\s*(32|64)", name):
        return 1.5
    if re.search(r"challenge\s*16", name):
        return 1.2
    if "challenge" in name:
        return 1.0
    if "preliminary" in name or "prelim" in name:
        return 0.7
    if "league" in name or "5-0" in name:
        return 0.5
    if "showcase" in name or "championship" in name:
        return 2.0
    return 0.8


def get_all_decklists(
    use_cache: bool = True,
    cache_ttl_hours: float = 24,
    max_events: int = 20,
    mtgo_only: bool = True,
) -> list[dict]:
    """Return decklists from recent MTGO Standard events via MtgTop8."""
    events = _get_recent_events(
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
        max_events=max_events,
        mtgo_only=mtgo_only,
    )

    result = []
    for event in events:
        for deck in event.get("decks", []):
            cards = deck.get("cards", [])
            if not cards:
                continue
            result.append({
                "name": deck["archetype"],
                "slug": f"mtgo_{event['event_id']}_{deck['deck_id']}",
                "metagame_pct": 0.0,
                "source": "mtgo",
                "source_weight": deck["weight"],
                "event_name": event["name"],
                "placement": deck.get("placement"),
                "cards": cards,
            })

    print(f"[mtgo] Loaded {len(result)} tournament decklists from {len(events)} events")
    return result


def _get_recent_events(
    use_cache: bool, cache_ttl_hours: float, max_events: int, mtgo_only: bool
) -> list[dict]:
    cache_file = CACHE_DIR / f"mtgo_events_{max_events}.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        age_h = (datetime.now().timestamp() - data["scraped_at"]) / 3600
        if age_h < cache_ttl_hours:
            print(f"[mtgo] Using cached event list ({age_h:.1f}h old)")
            return data["events"]

    print(f"[mtgo] Fetching Standard events from MtgTop8")
    resp = requests.get(FORMAT_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    event_stubs = _parse_event_list(resp.text, mtgo_only=mtgo_only)[:max_events]
    print(f"[mtgo] Found {len(event_stubs)} relevant events, fetching decklists...")

    events = []
    for stub in event_stubs:
        try:
            decks = _get_event_decks(stub, use_cache=use_cache, cache_ttl_hours=cache_ttl_hours)
            events.append({**stub, "decks": decks})
        except Exception as exc:
            print(f"[mtgo] Skipping event {stub['event_id']}: {exc}")
        time.sleep(0.5)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"scraped_at": datetime.now().timestamp(), "events": events}, indent=2)
    )
    return events


def _parse_event_list(html: str, mtgo_only: bool) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    stubs = []

    for a in soup.select('a[href*="event?e="]'):
        href = a.get("href", "")
        name = a.get_text(strip=True)
        if not name or "→" in name or name.isdigit():
            continue

        m = re.search(r"e=(\d+)", href)
        if not m:
            continue
        event_id = m.group(1)

        if mtgo_only and "mtgo" not in name.lower():
            continue
        if event_id in seen:
            continue
        seen.add(event_id)

        stubs.append({"event_id": event_id, "name": name, "href": href})

    return stubs


def _get_event_decks(stub: dict, use_cache: bool, cache_ttl_hours: float) -> list[dict]:
    event_id = stub["event_id"]
    cache_file = CACHE_DIR / f"mtgo_event_{event_id}.json"

    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        age_h = (datetime.now().timestamp() - data["scraped_at"]) / 3600
        if age_h < cache_ttl_hours:
            return data["decks"]

    url = f"{BASE_URL}/event?e={event_id}&f=ST"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    tier_weight = _event_tier_weight(stub["name"])
    deck_links = _parse_deck_links(soup)
    print(f"[mtgo] Event {stub['name']}: {len(deck_links)} decks")

    decks = []
    for i, deck_stub in enumerate(deck_links):
        try:
            cards = _get_deck_cards(
                deck_stub["deck_id"], event_id, use_cache=use_cache, cache_ttl_hours=cache_ttl_hours
            )
            if not cards:
                continue
            placement = deck_stub.get("placement", i + 1)
            p_weight = PLACEMENT_WEIGHT.get(placement, PLACEMENT_DEFAULT)
            decks.append({
                **deck_stub,
                "cards": cards,
                "weight": round(tier_weight * p_weight, 3),
            })
            time.sleep(0.3)
        except Exception as exc:
            print(f"[mtgo]   Skipping deck {deck_stub['deck_id']}: {exc}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"scraped_at": datetime.now().timestamp(), "decks": decks}, indent=2)
    )
    return decks


def _parse_deck_links(soup: BeautifulSoup) -> list[dict]:
    """Extract deck id, archetype, and placement from an event page."""
    seen: set[str] = set()
    decks = []

    # Placement is inferred from order; archetype is the link text
    placement = 0
    for a in soup.select('a[href*="d="]'):
        href = a.get("href", "")
        name = a.get_text(strip=True)
        if not name or "→" in name or not name[0].isalpha():
            continue
        m = re.search(r"d=(\d+)", href)
        if not m:
            continue
        deck_id = m.group(1)
        if deck_id in seen:
            continue
        seen.add(deck_id)
        placement += 1
        decks.append({"deck_id": deck_id, "archetype": name, "placement": placement})

    return decks


def _get_deck_cards(deck_id: str, event_id: str, use_cache: bool, cache_ttl_hours: float) -> list[dict]:
    cache_file = CACHE_DIR / f"mtgo_deck_{deck_id}.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        age_h = (datetime.now().timestamp() - data["scraped_at"]) / 3600
        if age_h < cache_ttl_hours:
            return data["cards"]

    url = f"{BASE_URL}/event?e={event_id}&d={deck_id}&f=ST"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    cards = _parse_deck_html(resp.text)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"scraped_at": datetime.now().timestamp(), "cards": cards}, indent=2)
    )
    return cards


def _parse_deck_html(html: str) -> list[dict]:
    """Parse MtgTop8 deck page: .deck_line = mainboard, .O14 after SIDEBOARD header = side."""
    soup = BeautifulSoup(html, "lxml")
    cards = []
    in_sideboard = False

    for el in soup.select(".deck_line, .O14"):
        text = el.get_text(strip=True)
        if text.upper() == "SIDEBOARD":
            in_sideboard = True
            continue

        # Text is like "4 Lightning Bolt" or "4Lightning Bolt" (occasional no-space)
        m = re.match(r"^(\d+)\s*(.+)$", text)
        if m:
            qty = int(m.group(1))
            name = m.group(2).strip()
            if qty and name:
                cards.append({"name": name, "quantity": qty, "sideboard": in_sideboard})

    return [c for c in cards if not c["sideboard"]]
