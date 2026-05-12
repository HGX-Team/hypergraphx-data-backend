#!/usr/bin/env python3
"""Download PokéAPI resources and write the CSV inputs used by Pokemon datasets."""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


BASE_URL = "https://pokeapi.co/api/v2"
USER_AGENT = "hypergraphx-data-pokemon-builder/1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep after retries and every 50 Pokemon.")
    return parser.parse_args()


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def get_json(session: requests.Session, url: str):
    for _ in range(3):
        response = session.get(url, timeout=60)
        if response.status_code == 200:
            return response.json()
        time.sleep(1.0)
    response.raise_for_status()


def extract_id_from_url(url: str) -> int:
    path = urlparse(url).path.rstrip("/")
    return int(path.split("/")[-1])


def fetch_all(session: requests.Session, endpoint: str):
    data = get_json(session, f"{BASE_URL}/{endpoint}?limit=100000&offset=0")
    results = data["results"]
    while data.get("next"):
        data = get_json(session, data["next"])
        results.extend(data["results"])
    return results


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    session = new_session()

    print("Fetching Pokemon list...")
    pokemon_list = fetch_all(session, "pokemon")
    print(f"Total Pokemon resources: {len(pokemon_list)}")

    with (
        (output_dir / "pokemon.csv").open("w", newline="", encoding="utf-8") as f_pokemon,
        (output_dir / "moves.csv").open("w", newline="", encoding="utf-8") as f_moves,
        (output_dir / "location_areas.csv").open("w", newline="", encoding="utf-8") as f_locs,
        (output_dir / "pokemon_move_raw.csv").open("w", newline="", encoding="utf-8") as f_pmr,
        (output_dir / "pokemon_location_raw.csv").open("w", newline="", encoding="utf-8") as f_plr,
        (output_dir / "incidence_moves_any.csv").open("w", newline="", encoding="utf-8") as f_im,
        (output_dir / "incidence_locations_any.csv").open("w", newline="", encoding="utf-8") as f_il,
        (output_dir / "incidence_moves_dual_any.csv").open("w", newline="", encoding="utf-8") as f_imd,
        (output_dir / "incidence_locations_dual_any.csv").open("w", newline="", encoding="utf-8") as f_ild,
    ):
        pokemon_writer = csv.writer(f_pokemon)
        moves_writer = csv.writer(f_moves)
        locations_writer = csv.writer(f_locs)
        pokemon_moves_writer = csv.writer(f_pmr)
        pokemon_locations_writer = csv.writer(f_plr)
        incidence_moves_writer = csv.writer(f_im)
        incidence_locations_writer = csv.writer(f_il)
        incidence_moves_dual_writer = csv.writer(f_imd)
        incidence_locations_dual_writer = csv.writer(f_ild)

        pokemon_writer.writerow([
            "pokemon_id", "pokemon_name", "species_name", "generation_name",
            "is_default", "primary_type", "secondary_type", "height", "weight",
            "base_hp", "base_attack", "base_defense", "base_sp_attack",
            "base_sp_defense", "base_speed",
        ])
        moves_writer.writerow([
            "move_id", "move_name", "move_type", "damage_class", "power",
            "accuracy", "pp", "generation_name",
        ])
        locations_writer.writerow([
            "location_area_id", "location_area_name", "location_name", "region_name",
        ])
        pokemon_moves_writer.writerow(["pokemon_id", "move_id", "version_group", "learn_method", "level"])
        pokemon_locations_writer.writerow(["pokemon_id", "location_area_id", "version", "encounter_method"])
        incidence_moves_writer.writerow(["move_id", "pokemon_id"])
        incidence_locations_writer.writerow(["location_area_id", "pokemon_id"])
        incidence_moves_dual_writer.writerow(["pokemon_edge_id", "move_id"])
        incidence_locations_dual_writer.writerow(["pokemon_edge_id", "location_area_id"])

        seen_moves = set()
        move_pairs_any = set()
        location_area_cache = {}
        location_pairs_any = set()

        for index, pokemon_ref in enumerate(pokemon_list, start=1):
            pokemon_data = get_json(session, pokemon_ref["url"])
            pokemon_id = pokemon_data["id"]

            species_data = get_json(session, pokemon_data["species"]["url"])
            generation = species_data["generation"]["name"] if species_data.get("generation") else ""

            types_sorted = sorted(pokemon_data["types"], key=lambda item: item["slot"])
            primary_type = types_sorted[0]["type"]["name"] if types_sorted else ""
            secondary_type = types_sorted[1]["type"]["name"] if len(types_sorted) > 1 else ""
            stats = {stat["stat"]["name"]: stat["base_stat"] for stat in pokemon_data["stats"]}

            pokemon_writer.writerow([
                pokemon_id,
                pokemon_data["name"],
                species_data["name"],
                generation,
                int(pokemon_data["is_default"]),
                primary_type,
                secondary_type,
                pokemon_data["height"],
                pokemon_data["weight"],
                stats.get("hp"),
                stats.get("attack"),
                stats.get("defense"),
                stats.get("special-attack"),
                stats.get("special-defense"),
                stats.get("speed"),
            ])

            for move_ref in pokemon_data["moves"]:
                move_id = extract_id_from_url(move_ref["move"]["url"])
                seen_moves.add(move_id)

                for version_detail in move_ref["version_group_details"]:
                    pokemon_moves_writer.writerow([
                        pokemon_id,
                        move_id,
                        version_detail["version_group"]["name"],
                        version_detail["move_learn_method"]["name"],
                        version_detail["level_learned_at"],
                    ])

                pair = (move_id, pokemon_id)
                if pair not in move_pairs_any:
                    move_pairs_any.add(pair)
                    incidence_moves_writer.writerow([move_id, pokemon_id])
                    incidence_moves_dual_writer.writerow([pokemon_id, move_id])

            encounters = get_json(session, f"{BASE_URL}/pokemon/{pokemon_id}/encounters")
            seen_areas_for_pokemon = set()

            for encounter in encounters:
                area = encounter["location_area"]
                area_id = extract_id_from_url(area["url"])

                if area_id not in location_area_cache:
                    area_data = get_json(session, area["url"])
                    location = area_data["location"]
                    location_data = get_json(session, location["url"])
                    region = location_data["region"]["name"] if location_data.get("region") else ""
                    location_area_cache[area_id] = (area["name"], location["name"], region)

                for version_detail in encounter["version_details"]:
                    method = ""
                    if version_detail["encounter_details"]:
                        method = version_detail["encounter_details"][0]["method"]["name"]
                    pokemon_locations_writer.writerow([
                        pokemon_id,
                        area_id,
                        version_detail["version"]["name"],
                        method,
                    ])

                if area_id not in seen_areas_for_pokemon:
                    seen_areas_for_pokemon.add(area_id)
                    pair = (area_id, pokemon_id)
                    if pair not in location_pairs_any:
                        location_pairs_any.add(pair)
                        incidence_locations_writer.writerow([area_id, pokemon_id])
                        incidence_locations_dual_writer.writerow([pokemon_id, area_id])

            if index % 50 == 0:
                print(f"Processed {index} Pokemon...")
                time.sleep(args.sleep)

        print(f"Total distinct moves seen: {len(seen_moves)}")
        print(f"Total distinct location areas seen: {len(location_area_cache)}")

        for move_id in sorted(seen_moves):
            move_data = get_json(session, f"{BASE_URL}/move/{move_id}/")
            generation = move_data["generation"]["name"] if move_data.get("generation") else ""
            moves_writer.writerow([
                move_id,
                move_data["name"],
                move_data["type"]["name"] if move_data.get("type") else "",
                move_data["damage_class"]["name"] if move_data.get("damage_class") else "",
                move_data["power"],
                move_data["accuracy"],
                move_data["pp"],
                generation,
            ])

        for area_id in sorted(location_area_cache):
            area_name, location_name, region = location_area_cache[area_id]
            locations_writer.writerow([area_id, area_name, location_name, region])

    print(f"Done. CSV files written to {output_dir}")


if __name__ == "__main__":
    main()
