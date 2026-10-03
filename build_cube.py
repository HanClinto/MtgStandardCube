#!/usr/bin/env python3
"""
MTG Standard Cube Builder
Usage:
  python build_cube.py [--config config.yaml] [--size 360] [--no-cache] [--output output/cube.csv]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import yaml


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def merge_archetypes(goldfish_archs: list[dict], moxfield_archs: list[dict]) -> list[dict]:
    """Tag each archetype with its source before merging."""
    for a in goldfish_archs:
        a.setdefault("source", "goldfish")
    for a in moxfield_archs:
        a.setdefault("source", "moxfield")
    return goldfish_archs + moxfield_archs


def run(config: dict, use_cache: bool, output_path: str) -> None:
    src_cfg = config.get("data_sources", {})
    rank_cfg = config.get("ranking", {})
    color_slots = config.get("color_slots", {})

    # Validate slots
    total_slots = sum(color_slots.values())
    cube_size = config.get("cube_size", 360)
    if total_slots != cube_size:
        print(
            f"[warn] color_slots sum to {total_slots}, but cube_size is {cube_size}. "
            "Using color_slots as-is."
        )

    all_archetypes: list[dict] = []

    if src_cfg.get("mtgo", {}).get("enabled", True):
        from scrapers.mtgo import get_all_decklists as mtgo_decklists
        mtgo_cfg = src_cfg["mtgo"]
        archs = mtgo_decklists(
            use_cache=use_cache,
            cache_ttl_hours=mtgo_cfg.get("cache_ttl_hours", 24),
            max_events=mtgo_cfg.get("max_events", 20),
            mtgo_only=mtgo_cfg.get("mtgo_only", True),
        )
        base_weight = mtgo_cfg.get("weight", 1.0)
        for a in archs:
            # source_weight is already set per-deck (placement × tier); scale by base
            a["source_weight"] = a.get("source_weight", 1.0) * base_weight
        all_archetypes.extend(archs)
        print(f"[main] MTGO: {len(archs)} tournament decklists loaded")

    if src_cfg.get("moxfield", {}).get("enabled", True):
        from scrapers.moxfield import get_all_decklists as mf_decklists
        mf_cfg = src_cfg["moxfield"]
        archs = mf_decklists(
            use_cache=use_cache,
            cache_ttl_hours=mf_cfg.get("cache_ttl_hours", 24),
            page_size=mf_cfg.get("page_size", 64),
            max_pages=mf_cfg.get("max_pages", 5),
            sort_type=mf_cfg.get("sort_type", "views"),
            min_cards=mf_cfg.get("min_cards", 58),
        )
        for a in archs:
            a["source_weight"] = mf_cfg.get("weight", 0.8)
        all_archetypes.extend(archs)
        print(f"[main] Moxfield: {len(archs)} decklists loaded")

    if not all_archetypes:
        sys.exit("[error] No archetypes loaded. Check your config and network.")

    print(f"\n[main] Ranking {sum(len(a['cards']) for a in all_archetypes)} card entries "
          f"across {len(all_archetypes)} archetypes...")

    from analysis.rank import rank_cards
    ranked = rank_cards(
        all_archetypes,
        playset_size=rank_cfg.get("playset_size", 4),
        cross_archetype_weight=rank_cfg.get("cross_archetype_weight", 0.2),
        min_archetype_appearances=rank_cfg.get("min_archetype_appearances", 1),
    )
    print(f"[main] {len(ranked)} unique cards ranked")

    from analysis.color_balance import build_cube, flatten_cube
    cube = build_cube(ranked, color_slots, use_cache=use_cache)
    flat = flatten_cube(cube)

    # Write CSV
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "color_category", "name", "final_score", "base_score",
        "archetype_count", "archetypes", "cmc", "type_line",
        "rarity", "set", "set_name", "scryfall_uri",
    ]
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for card in flat:
            row = dict(card)
            row["archetypes"] = "; ".join(row.get("archetypes", []))
            writer.writerow(row)

    print(f"\n[main] Cube written to {out}  ({len(flat)} cards)")

    # Also write a JSON summary of archetype coverage
    summary_path = out.with_suffix(".archetypes.json")
    archetype_names = sorted({a["name"] for a in all_archetypes})
    summary_path.write_text(json.dumps({"archetypes": archetype_names}, indent=2))
    print(f"[main] Archetype list written to {summary_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an MTG Standard cube from live decklists")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--size", type=int, default=None, help="Override cube_size from config")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached scrape data")
    parser.add_argument(
        "--output", default="output/cube.csv", help="Output CSV path"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.size:
        config["cube_size"] = args.size
        # Scale slots proportionally
        current_total = sum(config["color_slots"].values())
        scale = args.size / current_total
        config["color_slots"] = {
            k: max(1, round(v * scale)) for k, v in config["color_slots"].items()
        }

    run(config, use_cache=not args.no_cache, output_path=args.output)


if __name__ == "__main__":
    main()
