"""
Smart Minecraft Content Updater — Modrinth API
===============================================
Auto-detects and updates:
  - Fabric Mods       (/mods/*.jar)
  - Resource Packs    (/resourcepacks/*.zip)   — update only, NEVER removed
  - Data Packs        (/saves/*/datapacks/*.zip) — update only, NEVER removed

Priority system for mods:
  HIGH   — never removed, even if incompatible with current MC
  MEDIUM — asks you before removing (y/n prompt)
  LOW    — asks you before removing (y/n prompt)

How to find Modrinth slugs:
  The slug is the last part of the URL on modrinth.com.

  Mods:            modrinth.com/mod/<slug>             e.g. "sodium", "fabric-api"
  Resource Packs:  modrinth.com/resourcepack/<slug>    e.g. "faithful-32x"
  Data Packs:      modrinth.com/datapack/<slug>        e.g. "armor-stand-arms"

  In the Modrinth App: search for a mod → click it → the slug is in the URL bar
  or shown under the project title on the page.

Dependencies (all in global venv):
  aiohttp      — async HTTP
  python-dotenv — loads .env file

Usage:
  uv run --project ~/.global-venv python minecraft-mods.py
"""

import asyncio
import hashlib
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
from dotenv import load_dotenv

# Load .env from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

# ==================== CONFIG ====================

MC_DIR = Path("/Users/vivek/Library/Application Support/minecraft")

# "auto" = latest from Modrinth, or set manually e.g. "26.1.1"
GAME_VERSION = "26.1"

# Mod priority tiers — controls what happens when no compatible MC version exists.
#   HIGH   → NEVER removed. Kept no matter what.
#   MEDIUM → Asks you before removing (y/n prompt per mod).
#   LOW    → Asks you before removing (y/n prompt per mod).
#
# Mods NOT listed in any tier default to LOW.
# Use Modrinth slugs (same as the URL: modrinth.com/mod/<slug>)
MOD_PRIORITY = {
    "high": [
        "fabric-api",
        "sodium",
        "lithium",
        "modmenu",
        "entityculling",
        "immediatelyfast",
        "mouse-tweaks",
        "ukulib",
        "ukus-armor-hud",
        "better-block-entities",
        "macos-input-fixes",
        "dynamic-lights",
    ],
    "medium": [
        "dynamic-fps",
        "ferrite-core",
        "indium",
        "continuity",
        "elytra-chestplate-swapper",
        "clumps",
    ],
    "low": [
        # Everything not listed above defaults to low automatically
        "entitytexturefeatures",
        "entity-model-features",
        "appleskin",
        "3dskinlayers",
        "status-effect-bars",
        "freecam",
    ],
}

# Resource packs to install/update (Modrinth slugs)
# Script downloads the latest version if missing, updates if outdated.
# Find slugs at: modrinth.com/resourcepack/<slug>
RESOURCE_PACKS = [
    "faithful-32x",
    "fast-better-grass",
    "fresh-animations",
    "better-lanterns",
    "low-on-fire",
    "new-glowing-ores",
    "3d-crops",
    "rays-3d-rails",
    "better-lanterns",
    "rays-3d-ladders",
    "vvi",
    "3d-mace!",
    # Add more slugs here
]

# Data packs to install/update (Modrinth slugs)
# Installed into ALL world save folders.
# Find slugs at: modrinth.com/datapack/<slug>
DATA_PACKS = [
    "armor-stand-arms",
    "blazeandcaves-advancements-pack",
    "master-cutter",
    # Add more slugs here
]

# Set True to preview without downloading or removing anything
DRY_RUN = False

# Modrinth API token — loaded from .env file (MODRINTH_TOKEN=mrp_xxx)
# Get it at: modrinth.com → Account → Settings → Security → PAT
MODRINTH_TOKEN: Optional[str] = os.getenv("MODRINTH_TOKEN") or None

# ==================== CONSTANTS ====================

MODRINTH_API = "https://api.modrinth.com/v2"
STATE_FILE   = Path(__file__).parent / ".updater-state.json"
DB_FILE      = Path(__file__).parent / "database.json"
SEPARATOR    = "─" * 60

LOG_ICONS = {
    "ok":      "✓",
    "update":  "↑",
    "missing": "✗",
    "install": "+",
    "skip":    "~",
    "fail":    "✗",
    "info":    "•",
    "section": "▶",
    "ask":     "?",
    "keep":    "■",
    "down":    "⬇",
}


# ==================== LOGGING ====================

def log(icon_key: str, msg: str, indent: int = 2):
    prefix = " " * indent + LOG_ICONS.get(icon_key, " ")
    print(f"{prefix}  {msg}")


def section(title: str):
    print(f"\n  {LOG_ICONS['section']}  {title}")
    print(f"  {SEPARATOR}")


# ==================== STATE FILE ====================

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"mods": {}, "resourcepacks": {}, "datapacks": {}, "game_version": None}


def save_state(state: dict):
    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ==================== DATABASE HISTORY ====================

def load_db() -> dict:
    if DB_FILE.exists():
        try:
            return json.loads(DB_FILE.read_text())
        except Exception:
            pass
    return {"runs": []}


def save_run_to_db(
    game_version: str,
    mods_before: list[str],
    mods_after: list[str],
    updated: list[str],
    removed: list[str],
    installed: list[str],
    cross_check_fixed: list[str],
):
    """Append a run record to database.json history."""
    db = load_db()
    db["runs"].append({
        "timestamp":        datetime.now().isoformat(timespec="seconds"),
        "game_version":     game_version,
        "mods_before":      mods_before,
        "mods_after":       mods_after,
        "updated":          updated,
        "removed":          removed,
        "installed":        installed,
        "cross_check_fixed": cross_check_fixed,
    })
    # Keep last 50 runs
    db["runs"] = db["runs"][-50:]
    DB_FILE.write_text(json.dumps(db, indent=2))


# ==================== HELPERS ====================

def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def read_fabric_metadata(jar_path: Path) -> dict:
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            if "fabric.mod.json" in zf.namelist():
                with zf.open("fabric.mod.json") as f:
                    d = json.loads(f.read())
                    return {
                        "id":      d.get("id"),
                        "name":    d.get("name") or d.get("id") or jar_path.stem,
                        "version": d.get("version", "?"),
                        "mc_dep":  d.get("depends", {}).get("minecraft", ""),
                    }
    except Exception:
        pass
    return {"id": None, "name": jar_path.stem, "version": "?", "mc_dep": ""}


def detect_game_version(mc_dir: Path) -> Optional[str]:
    profiles_file = mc_dir / "launcher_profiles.json"
    if profiles_file.exists():
        try:
            profiles = json.loads(profiles_file.read_text()).get("profiles", {})
            for profile in profiles.values():
                version_id = profile.get("lastVersionId", "")
                m = re.search(r"fabric-loader-[\d.]+-(\d+\.\d+(?:\.\d+)?)", version_id)
                if m:
                    return m.group(1)
        except Exception:
            pass

    mods_path = mc_dir / "mods"
    filename_pattern = re.compile(r"(?:mc|minecraft[-_]?)(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)
    for jar in mods_path.glob("*.jar"):
        m = filename_pattern.search(jar.stem)
        if m:
            return m.group(1)

    for jar in mods_path.glob("*.jar"):
        meta = read_fabric_metadata(jar)
        dep = meta.get("mc_dep", "")
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", dep)
        if m:
            return m.group(1)

    return None


def get_primary_file(version: dict) -> Optional[dict]:
    files = version.get("files", [])
    return next((f for f in files if f.get("primary")), files[0] if files else None)


def build_headers() -> dict:
    h = {"User-Agent": "minecraft-smart-updater/3.0 (vivek)"}
    if MODRINTH_TOKEN:
        h["Authorization"] = MODRINTH_TOKEN
    return h


async def resolve_priority_ids(session: aiohttp.ClientSession) -> dict[str, set[str]]:
    """
    Resolve Modrinth slugs in MOD_PRIORITY to project IDs.
    Returns {"high": {id1, id2}, "medium": {id3}, "low": {id4}}.
    """
    resolved: dict[str, set[str]] = {"high": set(), "medium": set(), "low": set()}
    all_slugs = {
        slug: tier
        for tier in ("high", "medium", "low")
        for slug in MOD_PRIORITY.get(tier, [])
    }
    for slug, tier in all_slugs.items():
        info = await get_project(session, slug)
        if info:
            resolved[tier].add(info["id"])
        await asyncio.sleep(0.1)
    return resolved


def get_mod_tier(project_id: str, priority_ids: dict[str, set[str]]) -> str:
    if project_id in priority_ids["high"]:
        return "HIGH"
    if project_id in priority_ids["medium"]:
        return "MEDIUM"
    return "LOW"


# ==================== MODRINTH API ====================

async def bulk_check_updates(
    session: aiohttp.ClientSession,
    hashes: list[str],
    loaders: Optional[list[str]],
    game_version: str,
) -> dict:
    body: dict = {
        "hashes": hashes,
        "algorithm": "sha1",
        "game_versions": [game_version],
    }
    if loaders:
        body["loaders"] = loaders

    async with session.post(f"{MODRINTH_API}/version_files/update", json=body) as resp:
        if resp.status == 200:
            return await resp.json()
        return {}


async def identify_file_by_hash(
    session: aiohttp.ClientSession,
    file_hash: str,
) -> Optional[str]:
    async with session.get(
        f"{MODRINTH_API}/version_file/{file_hash}",
        params={"algorithm": "sha1"},
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get("project_id")
        return None


async def get_latest_version_for_project(
    session: aiohttp.ClientSession,
    project_id: str,
    loaders: list[str],
    game_version: str,
) -> Optional[dict]:
    async with session.get(
        f"{MODRINTH_API}/project/{project_id}/version",
        params={
            "loaders":       json.dumps(loaders),
            "game_versions": json.dumps([game_version]),
        },
    ) as resp:
        if resp.status != 200:
            return None
        versions = await resp.json()
        releases = [v for v in versions if v.get("version_type") == "release"]
        return releases[0] if releases else (versions[0] if versions else None)


async def get_latest_version_for_slug(
    session: aiohttp.ClientSession,
    slug: str,
    loaders: list[str],
    game_version: str,
) -> Optional[dict]:
    async with session.get(
        f"{MODRINTH_API}/project/{slug}/version",
        params={
            "loaders":       json.dumps(loaders),
            "game_versions": json.dumps([game_version]),
        },
    ) as resp:
        if resp.status != 200:
            return None
        versions = await resp.json()
        releases = [v for v in versions if v.get("version_type") == "release"]
        return releases[0] if releases else (versions[0] if versions else None)


async def fetch_latest_mc_version(session: aiohttp.ClientSession) -> Optional[str]:
    async with session.get(f"{MODRINTH_API}/tag/game_version") as resp:
        if resp.status != 200:
            return None
        versions = await resp.json()
        releases = [v["version"] for v in versions if v.get("version_type") == "release"]
        return releases[0] if releases else None


async def get_project(
    session: aiohttp.ClientSession,
    slug: str,
) -> Optional[dict]:
    async with session.get(f"{MODRINTH_API}/project/{slug}") as resp:
        return await resp.json() if resp.status == 200 else None


async def download_file(
    session: aiohttp.ClientSession,
    version: dict,
    dest_folder: Path,
) -> Optional[Path]:
    pf = get_primary_file(version)
    if not pf:
        return None

    dest = dest_folder / pf["filename"]
    expected = pf["hashes"]["sha1"]
    try:
        async with session.get(pf["url"]) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
        if sha1_file(dest) != expected:
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception:
        dest.unlink(missing_ok=True)
        return None


# ==================== CONTENT UPDATER ====================

async def process_content(
    session: aiohttp.ClientSession,
    label: str,
    files: list[Path],
    dest_folder: Path,
    state_bucket: dict,
    removed_bucket: dict,
    game_version: str,
    loaders: Optional[list[str]] = None,
    removal_mode: str = "never",          # "never" | "priority"
    priority_ids: Optional[dict] = None,  # required when removal_mode="priority"
    is_downgrade: bool = False,           # True when user targets a lower MC version
) -> tuple[dict, dict]:
    """
    Generic update flow for mods, resource packs, or data packs.

    removal_mode:
      "never"    → resource packs / data packs: update only, NEVER remove
      "priority" → mods: HIGH=keep, MEDIUM/LOW=ask user per mod

    Returns (new_state, updated_removed_bucket).
    """
    if label:
        section(label)

    new_state: dict[str, dict] = {}
    new_removed: dict[str, dict] = dict(removed_bucket)

    if not files:
        log("info", "No files found.")
        return new_state, new_removed

    # Hash all files
    hash_to_file: dict[str, Path] = {}
    for f in files:
        hash_to_file[sha1_file(f)] = f

    # Bulk Modrinth check
    log("info", f"Checking {len(files)} file(s) on Modrinth...")
    updates = await bulk_check_updates(session, list(hash_to_file.keys()), loaders, game_version)

    up_to_date:      list[dict] = []
    needs_update:    list[dict] = []
    no_result_hashes: list[tuple[str, Path]] = []

    for h, path in hash_to_file.items():
        name = path.name

        if h not in updates:
            no_result_hashes.append((h, path))
            continue

        new_ver     = updates[h]
        pf          = get_primary_file(new_ver)
        new_hash    = pf["hashes"]["sha1"] if pf else h
        project_id  = new_ver.get("project_id", "")
        new_ver_num = new_ver.get("version_number", "?")

        new_state[new_ver.get("name", name)] = {
            "hash": new_hash, "project_id": project_id,
            "version": new_ver_num, "filename": pf["filename"] if pf else name,
        }

        if new_hash == h:
            # Same hash — but verify the version actually targets our game_version
            target_gvs = new_ver.get("game_versions", [])
            if target_gvs and game_version not in target_gvs:
                # Same file but Modrinth says it's for a different MC version
                # Force re-download the correct version for our target
                correct = await get_latest_version_for_project(
                    session, project_id, loaders or [], game_version
                )
                if correct:
                    cpf = get_primary_file(correct)
                    if cpf and cpf["hashes"]["sha1"] != h:
                        needs_update.append({
                            "name": name, "old_path": path, "new_version": correct,
                            "new_ver_num": correct.get("version_number", "?"),
                            "project_id": project_id,
                        })
                        continue
                up_to_date.append({"name": name, "version": new_ver_num})
            else:
                up_to_date.append({"name": name, "version": new_ver_num})
        else:
            needs_update.append({
                "name": name, "old_path": path, "new_version": new_ver,
                "new_ver_num": new_ver_num, "project_id": project_id,
            })

    # ---- Deep-check: hashes not found in bulk update ----
    truly_unknown:    list[str]  = []
    incompatible_now: list[dict] = []

    if no_result_hashes:
        log("info", f"Identifying {len(no_result_hashes)} unmatched file(s)...")
        for h, path in no_result_hashes:
            project_id = await identify_file_by_hash(session, h)
            await asyncio.sleep(0.15)

            if not project_id:
                truly_unknown.append(path.name)
                new_state[path.name] = {"hash": h, "filename": path.name}
                continue

            compatible = await get_latest_version_for_project(
                session, project_id, loaders or [], game_version
            )
            await asyncio.sleep(0.15)

            if compatible:
                pf  = get_primary_file(compatible)
                ver = compatible.get("version_number", "?")
                needs_update.append({
                    "name": path.name, "old_path": path, "new_version": compatible,
                    "new_ver_num": ver, "project_id": project_id,
                })
            else:
                incompatible_now.append({
                    "name": path.name, "path": path,
                    "hash": h, "project_id": project_id,
                })

    # ---- Print status ----
    for m in up_to_date:
        log("ok", f"{m['name']}  ({m['version']})")

    for m in needs_update:
        log("update", f"{m['name']}  → {m['new_ver_num']}")

    for name in truly_unknown:
        log("skip", f"{name}  (not on Modrinth — kept)")

    # ---- Download updates ----
    if needs_update:
        print()
        action_word = "Downgrading" if is_downgrade else "Downloading"
        icon = "down" if is_downgrade else "info"
        log(icon, f"{action_word} {len(needs_update)} update(s)...")
        for i, item in enumerate(needs_update, 1):
            label_str = f"[{i}/{len(needs_update)}] {item['name']} → {item['new_ver_num']}"
            if DRY_RUN:
                log("skip", f"[DRY RUN] {label_str}")
                continue

            # When downgrading mods, ask per mod before replacing
            if is_downgrade and removal_mode == "priority":
                print(f"\n    {LOG_ICONS['down']}  {label_str}")
                print(f"       This will downgrade to MC {game_version}.")
                answer = input(f"       Downgrade this mod? (y/n): ").strip().lower()
                if answer != "y":
                    log("keep", f"Kept current version of {item['name']}")
                    # Keep old file in state
                    old = item["old_path"]
                    new_state[old.name] = {"hash": sha1_file(old), "filename": old.name}
                    continue
                print(f"    ⬇  {label_str} ... ", end="", flush=True)
            else:
                print(f"    ↓  {label_str} ... ", end="", flush=True)

            new_path = await download_file(session, item["new_version"], dest_folder)
            if new_path:
                old = item["old_path"]
                if old.exists() and old.name != new_path.name:
                    old.unlink()
                print("done ✓")
            else:
                print("FAILED ✗")
            await asyncio.sleep(0.25)

    # ---- Handle incompatible files ----
    if incompatible_now:
        print()

        if removal_mode == "never":
            # Resource packs / data packs — NEVER remove, just keep
            log("info", "Incompatible files (kept — update only, no removal):")
            for m in incompatible_now:
                log("keep", f"{m['name']}  — no {game_version} version (kept)")
                new_state[m["name"]] = {
                    "hash": m["hash"], "filename": m["name"],
                    "project_id": m["project_id"],
                }

        elif removal_mode == "priority":
            # Mods — priority-based removal
            pids = priority_ids or {"high": set(), "medium": set(), "low": set()}
            log("info", f"{len(incompatible_now)} mod(s) incompatible with {game_version}:")
            print()

            for m in incompatible_now:
                pid  = m["project_id"]
                name = m["name"]
                tier = get_mod_tier(pid, pids)

                if tier == "HIGH":
                    # ─── HIGH: never remove ───
                    log("keep", f"[{tier}]  {name}  — kept (never removed)")
                    new_state[name] = {
                        "hash": m["hash"], "filename": name, "project_id": pid,
                    }

                elif DRY_RUN:
                    log("skip", f"[DRY RUN] [{tier}] Would ask to remove {name}")

                else:
                    # ─── MEDIUM / LOW: ask user ───
                    print(f"    {LOG_ICONS['ask']}  [{tier}]  {name}")
                    print(f"       No compatible version for MC {game_version} yet.")
                    answer = input(f"       Remove this mod? (y/n): ").strip().lower()

                    if answer == "y":
                        m["path"].unlink()
                        log("missing", f"Removed  {name}")
                        new_removed[pid] = {
                            "project_id": pid, "filename": name,
                            "removed_on": game_version,
                        }
                    else:
                        log("keep", f"Kept  {name}")
                        new_state[name] = {
                            "hash": m["hash"], "filename": name, "project_id": pid,
                        }

    return new_state, new_removed


async def check_previously_removed(
    session: aiohttp.ClientSession,
    removed_bucket: dict,
    dest_folder: Path,
    game_version: str,
    loaders: list[str],
) -> dict:
    """Check removed mods — if a compatible version now exists, download it."""
    if not removed_bucket:
        return removed_bucket

    section(f"Checking {len(removed_bucket)} Previously Removed Mod(s)")
    first_entry = next(iter(removed_bucket.values()), {})
    log("info", f"Removed on MC {first_entry.get('removed_on', '?')} — checking {game_version}...")
    print()

    still_waiting: dict[str, dict] = {}

    for project_id, info in removed_bucket.items():
        fname = info.get("filename", project_id)
        compatible = await get_latest_version_for_project(
            session, project_id, loaders, game_version
        )
        await asyncio.sleep(0.15)

        if not compatible:
            log("missing", f"{fname}  — still no {game_version} version")
            still_waiting[project_id] = info
            continue

        ver = compatible.get("version_number", "?")
        if DRY_RUN:
            log("skip", f"[DRY RUN] Would reinstall {fname} {ver}")
            still_waiting[project_id] = info
            continue

        print(f"    +  {fname} → {ver} ... ", end="", flush=True)
        path = await download_file(session, compatible, dest_folder)
        if path:
            print("done ✓  (auto-reinstalled)")
        else:
            print("FAILED ✗")
            still_waiting[project_id] = info

        await asyncio.sleep(0.25)

    return still_waiting


async def process_priority_mods(
    session: aiohttp.ClientSession,
    mods_path: Path,
    game_version: str,
    state_bucket: dict,
) -> None:
    """
    Check all mods from MOD_PRIORITY that are not installed yet.
    - If latest MC version available → ask user to download (y/n)
    - If NO compatible version exists → tell user and skip
    """
    installed_ids = {v.get("project_id") for v in state_bucket.values() if v.get("project_id")}

    # Also build installed project IDs by hashing every jar in the folder
    # This catches mods not tracked in state (like manually added jars)
    for jar in mods_path.glob("*.jar"):
        h = sha1_file(jar)
        pid = await identify_file_by_hash(session, h)
        if pid:
            installed_ids.add(pid)
        await asyncio.sleep(0.05)

    all_priority_slugs = [
        slug
        for tier in ("high", "medium", "low")
        for slug in MOD_PRIORITY.get(tier, [])
    ]

    missing_priority = []
    for slug in all_priority_slugs:
        info = await get_project(session, slug)
        if not info:
            continue
        if info["id"] not in installed_ids:
            missing_priority.append((slug, info.get("title", slug), info["id"]))

    if not missing_priority:
        return

    section(f"Priority Mods — {len(missing_priority)} Not Installed")

    for i, (slug, title, _) in enumerate(missing_priority, 1):
        latest = await get_latest_version_for_slug(session, slug, ["fabric"], game_version)

        if not latest:
            # No compatible version for current MC
            log("fail", f"[{i}/{len(missing_priority)}] {title}  — no version for MC {game_version}")
            continue

        ver = latest.get("version_number", "?")

        if DRY_RUN:
            log("skip", f"[DRY RUN] Would ask to install {title} {ver}")
            continue

        # Ask user before downloading
        print(f"\n    {LOG_ICONS['ask']}  [{i}/{len(missing_priority)}]  {title}  (v{ver})")
        print(f"       Latest version available for MC {game_version}.")
        answer = input(f"       Download this mod? (y/n): ").strip().lower()

        if answer == "y":
            print(f"    ↓  Installing {title} {ver} ... ", end="", flush=True)
            path = await download_file(session, latest, mods_path)
            print("done ✓" if path else "FAILED ✗")
        else:
            log("skip", f"Skipped  {title}")

        await asyncio.sleep(0.25)


async def process_pack_list(
    session: aiohttp.ClientSession,
    slug_list: list[str],
    dest_folder: Path,
    game_version: str,
    pack_type: str,  # "resource pack" or "data pack"
) -> None:
    """
    Install missing packs and update existing ones from a slug list.
    Downloads the latest version compatible with game_version (never higher).
    - If already installed (same hash) → skip
    - If old version found → update (replace old file)
    - If not installed at all → download
    """
    if not slug_list:
        return

    section(f"{pack_type.title()} List  ({len(slug_list)} configured)")

    for i, slug in enumerate(slug_list, 1):
        info = await get_project(session, slug)
        if not info:
            log("fail", f"[{i}/{len(slug_list)}] {slug}  — not found on Modrinth")
            continue

        title = info.get("title", slug)

        # Try current game version first, fallback to any latest version
        latest = await get_latest_version_for_slug(session, slug, [], game_version)
        if not latest:
            # No version for current MC — get the absolute latest available
            async with session.get(f"{MODRINTH_API}/project/{slug}/version") as resp:
                if resp.status == 200:
                    all_versions = await resp.json()
                    releases = [v for v in all_versions if v.get("version_type") == "release"]
                    latest = releases[0] if releases else (all_versions[0] if all_versions else None)

        if not latest:
            log("skip", f"[{i}/{len(slug_list)}] {title}  — no version on Modrinth")
            await asyncio.sleep(0.15)
            continue

        pf = get_primary_file(latest)
        if not pf:
            log("fail", f"[{i}/{len(slug_list)}] {title}  — no downloadable file")
            continue

        latest_hash = pf["hashes"]["sha1"]
        ver         = latest.get("version_number", "?")

        # Check if this exact version is already installed (by hash)
        already_installed = False
        old_file: Optional[Path] = None
        for existing in list(dest_folder.glob("*.zip")) + list(dest_folder.glob("*.jar")):
            if sha1_file(existing) == latest_hash:
                already_installed = True
                break
            name_lower = title.lower().replace(" ", "").replace("-", "")
            file_lower = existing.name.lower().replace(" ", "").replace("-", "")
            if name_lower in file_lower:
                old_file = existing

        if already_installed:
            log("ok", f"[{i}/{len(slug_list)}] {title}  ({ver})")
            continue

        if DRY_RUN:
            action = "update" if old_file else "install"
            log("skip", f"[DRY RUN] Would {action} {title} {ver}")
            continue

        # Auto-download — resource packs and data packs are never removed,
        # so we don't need to ask. Just download the latest.
        action = "Updating" if old_file else "Installing"
        print(f"    ↓  [{i}/{len(slug_list)}] {action} {title} → {ver} ... ", end="", flush=True)
        new_path = await download_file(session, latest, dest_folder)
        if new_path:
            if old_file and old_file.exists() and old_file.name != new_path.name:
                old_file.unlink()
            print("done ✓")
        else:
            print("FAILED ✗")

        await asyncio.sleep(0.25)


# ==================== MAIN ====================

async def main():
    mods_path          = MC_DIR / "mods"
    resourcepacks_path = MC_DIR / "resourcepacks"
    saves_path         = MC_DIR / "saves"

    if not MC_DIR.exists():
        print(f"ERROR: Minecraft directory not found: {MC_DIR}")
        return

    # Detect MC version
    game_version = GAME_VERSION
    connector_pre = aiohttp.TCPConnector(limit=2)
    async with aiohttp.ClientSession(headers=build_headers(), connector=connector_pre) as pre_session:
        latest_mc = await fetch_latest_mc_version(pre_session)

    if game_version == "auto":
        if latest_mc:
            game_version = latest_mc
            version_src  = "latest from Modrinth"
        else:
            detected = detect_game_version(MC_DIR)
            game_version = detected or "1.21.1"
            version_src  = "auto-detected locally" if detected else "fallback default"
    else:
        version_src = "config"

    state = load_state()
    prev_version = state.get("game_version")
    is_downgrade = False
    if prev_version and prev_version != game_version:
        try:
            prev_parts = tuple(int(x) for x in prev_version.split("."))
            curr_parts = tuple(int(x) for x in game_version.split("."))
            is_downgrade = curr_parts < prev_parts
        except ValueError:
            pass

    new_state:   dict[str, dict] = {"mods": {}, "resourcepacks": {}, "datapacks": {}}
    new_removed: dict[str, dict] = {
        "mods": state.get("removed_incompatible", {}).get("mods", {}),
    }

    print(f"\n{'═' * 60}")
    print(f"  Smart Minecraft Content Updater  v3.0")
    print(f"{'═' * 60}")
    print(f"  MC Directory : {MC_DIR}")
    print(f"  Game Version : {game_version}  ({version_src})")
    if is_downgrade:
        print(f"  ⬇ DOWNGRADE  : {prev_version} → {game_version}")
        print(f"                 Mods: asks per mod  |  Resource/Data packs: skipped")
    print(f"  Loader       : Fabric")
    print(f"  Priority     : {len(MOD_PRIORITY['high'])} HIGH, "
          f"{len(MOD_PRIORITY['medium'])} MEDIUM, "
          f"rest LOW")
    if DRY_RUN:
        print(f"  ⚠  DRY RUN — no files will be changed")
    print(f"{'═' * 60}")

    connector = aiohttp.TCPConnector(limit=5)
    timeout   = aiohttp.ClientTimeout(total=120)
    headers   = build_headers()

    async with aiohttp.ClientSession(headers=headers, connector=connector, timeout=timeout) as session:

        # Resolve priority slugs → project IDs
        log("info", "Resolving mod priority list...")
        priority_ids = await resolve_priority_ids(session)

        # ── 0. CHECK PREVIOUSLY REMOVED MODS ────────────────────
        if new_removed["mods"]:
            new_removed["mods"] = await check_previously_removed(
                session        = session,
                removed_bucket = new_removed["mods"],
                dest_folder    = mods_path,
                game_version   = game_version,
                loaders        = ["fabric"],
            )

        # Snapshot mods before changes for database history
        mods_before = [f.name for f in mods_path.glob("*.jar")] if mods_path.exists() else []

        # ── 1. MODS ──────────────────────────────────────────────
        if mods_path.exists():
            jar_files = sorted(mods_path.glob("*.jar"))
            new_state["mods"], new_removed["mods"] = await process_content(
                session        = session,
                label          = f"Fabric Mods  ({len(jar_files)} installed)",
                files          = jar_files,
                dest_folder    = mods_path,
                state_bucket   = state.get("mods", {}),
                removed_bucket = new_removed["mods"],
                game_version   = game_version,
                loaders        = ["fabric"],
                removal_mode   = "priority",
                priority_ids   = priority_ids,
                is_downgrade   = is_downgrade,
            )
            if not is_downgrade:
                await process_priority_mods(session, mods_path, game_version, new_state["mods"])
        else:
            print("\n  No mods folder found — skipping mods.")

        # ── 2. RESOURCE PACKS (update only, NEVER remove, NEVER downgrade) ─
        if is_downgrade:
            section("Resource Packs  (skipped — no downgrade for resource packs)")
        elif resourcepacks_path.exists():
            rp_files = sorted(
                list(resourcepacks_path.glob("*.zip")) +
                list(resourcepacks_path.glob("*.jar"))
            )
            new_state["resourcepacks"], _ = await process_content(
                session        = session,
                label          = f"Resource Packs  ({len(rp_files)} installed)",
                files          = rp_files,
                dest_folder    = resourcepacks_path,
                state_bucket   = state.get("resourcepacks", {}),
                removed_bucket = {},
                game_version   = game_version,
                loaders        = None,
                removal_mode   = "never",
            )
        else:
            print("\n  No resourcepacks folder found — skipping.")

        # ── 2b. RESOURCE PACK LIST (install/update from config) ──
        if RESOURCE_PACKS and resourcepacks_path.exists() and not is_downgrade:
            await process_pack_list(
                session      = session,
                slug_list    = RESOURCE_PACKS,
                dest_folder  = resourcepacks_path,
                game_version = game_version,
                pack_type    = "resource pack",
            )

        # ── 3. DATA PACKS (update only, NEVER remove, NEVER downgrade) ──
        if is_downgrade:
            section("Data Packs  (skipped — no downgrade for data packs)")
        elif saves_path.exists():
            worlds = [d for d in saves_path.iterdir() if d.is_dir()]
            all_dp_files: list[Path] = []

            for world in worlds:
                dp_folder = world / "datapacks"
                if dp_folder.exists():
                    all_dp_files.extend(dp_folder.glob("*.zip"))

            if all_dp_files:
                section(f"Data Packs  ({len(all_dp_files)} across {len(worlds)} world(s))")
                for world in worlds:
                    dp_folder = world / "datapacks"
                    if not dp_folder.exists():
                        continue
                    world_files = sorted(dp_folder.glob("*.zip"))
                    if not world_files:
                        continue

                    print(f"\n    World: {world.name}")
                    world_state, _ = await process_content(
                        session        = session,
                        label          = "",
                        files          = world_files,
                        dest_folder    = dp_folder,
                        state_bucket   = state.get("datapacks", {}).get(world.name, {}),
                        removed_bucket = {},
                        game_version   = game_version,
                        loaders        = None,
                        removal_mode   = "never",
                    )
                    new_state["datapacks"][world.name] = world_state
            else:
                section("Data Packs")
                log("info", "No data packs found in any world.")

        # ── 3b. DATA PACK LIST (install/update into all worlds) ──
        if DATA_PACKS and saves_path.exists() and not is_downgrade:
            worlds_with_dp = [
                d for d in saves_path.iterdir()
                if d.is_dir() and (d / "datapacks").exists()
            ]
            if worlds_with_dp:
                for world in worlds_with_dp:
                    dp_folder = world / "datapacks"
                    section(f"Data Pack List → {world.name}")
                    await process_pack_list(
                        session      = session,
                        slug_list    = DATA_PACKS,
                        dest_folder  = dp_folder,
                        game_version = game_version,
                        pack_type    = "data pack",
                    )

        # ── 4. FINAL CROSS-CHECK — verify ALL mods match game_version exactly ──
        if mods_path.exists():
            section(f"Final Cross-Check — MC {game_version}")
            final_jars = list(mods_path.glob("*.jar"))
            mismatched = []

            for jar in final_jars:
                h = sha1_file(jar)
                meta = read_fabric_metadata(jar)
                mod_name = meta.get("name", jar.name)

                # Check 1: Modrinth game_versions field
                modrinth_mismatch = False
                project_id = None
                mod_ver = meta.get("version", "?")
                supports = ""

                async with session.get(
                    f"{MODRINTH_API}/version_file/{h}",
                    params={"algorithm": "sha1"},
                ) as resp:
                    if resp.status == 200:
                        ver_data = await resp.json()
                        gvs = ver_data.get("game_versions", [])
                        project_id = ver_data.get("project_id")
                        mod_ver = ver_data.get("version_number", mod_ver)
                        if gvs and game_version not in gvs:
                            modrinth_mismatch = True
                            supports = ", ".join(gvs[:3]) + ("..." if len(gvs) > 3 else "")

                # Check 2: fabric.mod.json depends.minecraft
                fabric_mismatch = False
                mc_dep = meta.get("mc_dep", "")
                if mc_dep and isinstance(mc_dep, str):
                    # Exact version dependency like "26.1.1" or "~26.1.1"
                    dep_clean = mc_dep.strip().lstrip("~>=<^")
                    if dep_clean and dep_clean != game_version and "." in dep_clean:
                        try:
                            dep_parts = tuple(int(x) for x in dep_clean.split("."))
                            gv_parts  = tuple(int(x) for x in game_version.split("."))
                            if dep_parts != gv_parts:
                                fabric_mismatch = True
                        except ValueError:
                            pass

                if modrinth_mismatch or fabric_mismatch:
                    mismatched.append({
                        "name": mod_name, "file": jar, "version": mod_ver,
                        "supports": supports or mc_dep,
                        "project_id": project_id, "hash": h,
                    })

                await asyncio.sleep(0.08)

            if not mismatched:
                log("ok", f"All {len(final_jars)} mods are compatible with MC {game_version}")
            else:
                log("fail", f"{len(mismatched)} mod(s) NOT compatible with MC {game_version}:")
                for m in mismatched:
                    log("missing", f"{m['name']} v{m['version']}  (supports: {m['supports']})")

                # Auto-fix: replace every mismatched mod with the correct version
                print()
                log("info", "Auto-fixing incompatible mods...")
                for m in mismatched:
                    pid = m.get("project_id")
                    if not pid:
                        # Try to identify by hash
                        pid = await identify_file_by_hash(session, m["hash"])
                    if not pid:
                        log("skip", f"{m['name']}  — can't identify on Modrinth")
                        continue
                    correct = await get_latest_version_for_project(
                        session, pid, ["fabric"], game_version
                    )
                    if correct:
                        cpf = get_primary_file(correct)
                        # Skip if the "correct" version is the same file we already have
                        if cpf and cpf["hashes"]["sha1"] == m["hash"]:
                            log("ok", f"{m['name']}  — same file works for {game_version}")
                            continue
                        ver = correct.get("version_number", "?")
                        if DRY_RUN:
                            log("skip", f"[DRY RUN] Would replace {m['name']} → v{ver}")
                            continue
                        print(f"    ⬇  {m['name']}  v{m['version']} → v{ver} ... ", end="", flush=True)
                        new_path = await download_file(session, correct, mods_path)
                        if new_path:
                            old = m["file"]
                            if old.exists() and old.name != new_path.name:
                                old.unlink()
                            print("done ✓")
                        else:
                            print("FAILED ✗")
                        await asyncio.sleep(0.25)
                    else:
                        log("missing", f"{m['name']}  — no version for MC {game_version}")

    # Snapshot mods after all changes
    mods_after = [f.name for f in mods_path.glob("*.jar")] if mods_path.exists() else []

    # Save state
    save_state({
        **new_state,
        "game_version":         game_version,
        "removed_incompatible": new_removed,
    })

    # Save run history to database.json
    added   = [f for f in mods_after if f not in mods_before]
    removed = [f for f in mods_before if f not in mods_after]
    save_run_to_db(
        game_version       = game_version,
        mods_before        = sorted(mods_before),
        mods_after         = sorted(mods_after),
        updated            = sorted(set(added) & set(removed)),  # files that were swapped
        removed            = sorted(set(removed) - set(added)),
        installed          = sorted(set(added) - set(removed)),
        cross_check_fixed  = [],  # populated above if cross-check ran
    )

    print(f"\n{'═' * 60}")
    print(f"  Done!")
    print(f"  State    → {STATE_FILE.name}")
    print(f"  History  → {DB_FILE.name}")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
