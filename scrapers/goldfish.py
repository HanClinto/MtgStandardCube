"""MTGGoldfish Standard metagame scraper."""

import re
import time
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path("data/cache")
METAGAME_URL = "https://www.mtggoldfish.com/metagame/standard/full"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def get_all_decklists(use_cache: bool = True, cache_ttl_hours: float = 24) -> list[dict]:
    """Return list of archetypes, each with name, metagame_pct, slug, and cards."""
    archetypes = _get_metagame(use_cache=use_cache, cache_ttl_hours=cache_ttl_hours)
    result = []
    for arch in archetypes:
        try:
            cards = _get_decklist(
                arch["slug"], use_cache=use_cache, cache_ttl_hours=cache_ttl_hours
            )
            if not cards:
                continue
            result.append({**arch, "cards": cards})
        except Exception as exc:
            print(f"[goldfish] Skipping {arch['slug']}: {exc}")
    print(f"[goldfish] Loaded {len(result)} archetypes with decklists")
    return result


def _get_metagame(use_cache: bool, cache_ttl_hours: float) -> list[dict]:
    cache_file = CACHE_DIR / "goldfish_metagame.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        age_h = (datetime.now().timestamp() - data["scraped_at"]) / 3600
        if age_h < cache_ttl_hours:
            print(f"[goldfish] Using cached metagame ({age_h:.1f}h old)")
            return data["archetypes"]

    print(f"[goldfish] Fetching metagame from {METAGAME_URL}")
    resp = requests.get(METAGAME_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    archetypes = _parse_metagame_html(resp.text)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"scraped_at": datetime.now().timestamp(), "archetypes": archetypes}, indent=2)
    )
    print(f"[goldfish] Found {len(archetypes)} archetypes")
    return archetypes


def _parse_metagame_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    archetypes = []

    for tile in soup.select(".archetype-tile"):
        name_el = tile.select_one(".archetype-tile-title a")
        if not name_el:
            continue

        name = name_el.get_text(strip=True)
        href = name_el.get("href", "")
        # href looks like /archetype/standard-azorius-control
        slug = href.rstrip("/").split("/")[-1]

        pct = 0.0
        for el in tile.select(".archetype-tile-stats-title, .percentage"):
            m = re.search(r"([\d.]+)%", el.get_text())
            if m:
                pct = float(m.group(1))
                break

        if slug:
            archetypes.append({"name": name, "slug": slug, "metagame_pct": pct})

    return archetypes


def _get_decklist(slug: str, use_cache: bool, cache_ttl_hours: float) -> list[dict]:
    cache_file = CACHE_DIR / f"goldfish_deck_{slug}.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        age_h = (datetime.now().timestamp() - data["scraped_at"]) / 3600
        if age_h < cache_ttl_hours:
            return data["cards"]

    # Try the archetype download endpoint first; fall back to page scraping
    cards = _try_download_endpoint(slug) or _scrape_archetype_page(slug)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"scraped_at": datetime.now().timestamp(), "slug": slug, "cards": cards}, indent=2)
    )
    return cards


def _try_download_endpoint(slug: str) -> list[dict] | None:
    """Attempt to download the archetype's representative deck as text."""
    url = f"https://www.mtggoldfish.com/archetype/{slug}/download"
    time.sleep(1)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        cards = _parse_arena_text(resp.text)
        if cards:
            print(f"[goldfish] Downloaded {len(cards)} mainboard cards for {slug}")
            return cards
    except Exception:
        pass
    return None


def _scrape_archetype_page(slug: str) -> list[dict]:
    """Parse decklist table from the archetype HTML page."""
    url = f"https://www.mtggoldfish.com/archetype/{slug}#online"
    time.sleep(1)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return _parse_archetype_html(resp.text)


def _parse_archetype_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = []
    in_sideboard = False

    # The deck view table rows
    for row in soup.select("table.deck-view-deck-table tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            section = row.get_text(strip=True).lower()
            if "sideboard" in section:
                in_sideboard = True
            continue
        try:
            qty = int(cells[0].get_text(strip=True))
            name = cells[1].get_text(strip=True)
            if name and qty:
                cards.append({"name": name, "quantity": qty, "sideboard": in_sideboard})
        except (ValueError, IndexError):
            continue

    return [c for c in cards if not c["sideboard"]]


def _parse_arena_text(text: str) -> list[dict]:
    """Parse Arena/MTGO export format into card list (mainboard only)."""
    cards = []
    in_sideboard = False
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            in_sideboard = True  # blank line separates sideboard
            continue
        if line.lower() in ("sideboard", "deck"):
            in_sideboard = line.lower() == "sideboard"
            continue
        m = re.match(r"^(\d+)x?\s+(.+?)(?:\s+\([\w\d]+\)\s+\d+)?$", line)
        if m:
            qty, name = int(m.group(1)), m.group(2).strip()
            cards.append({"name": name, "quantity": qty, "sideboard": in_sideboard})

    return [c for c in cards if not c["sideboard"]]
