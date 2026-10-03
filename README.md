# MTG Standard Cube Builder

Automatically builds a color-balanced MTG cube from current Standard metagame data.
Scrapes top decklists from MTGGoldfish and Moxfield, ranks cards by format presence,
and outputs a cube list balanced across colors.

## How it works

1. **Scrape** — fetches Standard archetypes + decklists from MTGGoldfish (with metagame %)
   and top-viewed Standard decks from Moxfield.
2. **Rank** — scores each card by how heavily it's played across archetypes:
   - Frequency × archetype meta-share → base score
   - Cross-archetype bonus for cards that appear in multiple strategies
3. **Balance** — looks up color/type metadata via Scryfall, then fills configurable
   per-color slot quotas (default: 60 per color + 40 multicolor + 12 artifact + 8 land).
4. **Output** — `output/cube.csv` with full card details and ranking scores.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Build with defaults (360-card cube, uses cache if fresh)
python build_cube.py

# 540-card cube, skip cache
python build_cube.py --size 540 --no-cache

# Custom config
python build_cube.py --config my_config.yaml --output output/my_cube.csv
```

## Configuration

Edit `config.yaml` to adjust:
- `cube_size` — total card count (default 360)
- `color_slots` — cards per color/category
- `ranking.cross_archetype_weight` — bonus for cross-archetype cards
- `data_sources.goldfish/moxfield` — enable/disable sources, set weights and cache TTL

## Output

`output/cube.csv` columns:
| Column | Description |
|---|---|
| `color_category` | white / blue / black / red / green / multicolor / artifact / land |
| `name` | Card name |
| `final_score` | Ranking score (higher = more format-defining) |
| `archetype_count` | Number of archetypes this card appears in |
| `archetypes` | Semicolon-separated archetype names |
| `cmc` | Converted mana cost |
| `type_line` | Card type |
| `rarity` | Card rarity |
| `set` | Printing set code |

## Standard sizes

| Size | Use case |
|---|---|
| 360 | 8-player draft (default) |
| 450 | 10-player draft or deeper pool |
| 540 | Large cube / multiple formats |
