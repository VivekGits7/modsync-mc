# ModSync MC

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Minecraft](https://img.shields.io/badge/Minecraft-Fabric-8B5E34?logo=data:image/svg+xml;base64,&logoColor=white)
![Modrinth](https://img.shields.io/badge/Modrinth-API-00AF5C?logo=modrinth&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

A single Python script that keeps your Minecraft Fabric mods, resource packs, and data packs perfectly in sync with any Minecraft version you want. Update, downgrade, install, remove — all in one run.

---

## Why This Script Exists

If you play Minecraft with Fabric mods, you know the pain:

- **Minecraft updates, mods break.** Every time Mojang drops a new version, you have to manually check which mods have updated, download them one by one, and hope nothing conflicts.
- **Switching versions is a nightmare.** Want to play on an older server? You'd have to manually swap out every mod file to match that version.
- **Resource packs and data packs get forgotten.** They need updates too, but nobody remembers to check.
- **You accidentally delete a mod you needed.** Or keep one that's been abandoned. There's no system to manage what stays and what goes.

**ModSync MC fixes all of this.** You run one command, and it:

1. Checks **every** `.jar` in your `mods/` folder against the Modrinth API
2. Downloads the correct version of each mod for your target Minecraft version
3. Updates resource packs and data packs across all your world saves
4. Asks before removing anything (based on a priority system YOU control)
5. Auto-reinstalls mods that were previously removed if a compatible version is now available
6. Runs a final cross-check to make sure **every single mod** matches your target version

No more manual downloads. No more broken mod folders after an update. Just run the script and play.

---

## How to Use This Script

This section walks you through everything step by step. Even if you've never used Python or a terminal before, you'll be fine.

### Step 1: Get Your Modrinth API Token

The script talks to [Modrinth](https://modrinth.com) (the mod hosting platform) to check for updates and download files. You need a personal access token (PAT) so the API doesn't rate-limit you.

1. Go to [modrinth.com](https://modrinth.com) and log in (or create an account)
2. Click your **profile icon** (top right) → **Settings**
3. Scroll down to **Security** section
4. Under **Personal Access Tokens (PATs)**, click **Create a token**
5. Give it a name like `modsync` and click **Create**
6. **Copy the token** — it starts with `mrp_` (e.g., `mrp_abc123xyz...`)
7. Save it somewhere safe — you won't be able to see it again

Now create a `.env` file in the **project root** (same level as `pyproject.toml`):

```
.env
```

Open it in any text editor (Notepad, TextEdit, VS Code, whatever) and paste:

```env
MODRINTH_TOKEN=mrp_your_token_here
```

Replace `mrp_your_token_here` with the actual token you copied.

> **Note:** The `.env` file is git-ignored. Your token never gets uploaded anywhere.

---

### Step 2: Find the Modrinth Slug for Any Mod, Resource Pack, or Data Pack

A **slug** is just the short name in the Modrinth URL. It's how the script knows which project to look up.

#### For Mods

1. Go to [modrinth.com](https://modrinth.com) and search for a mod (e.g., "Sodium")
2. Click on the mod page
3. Look at the URL in your browser:
   ```
   https://modrinth.com/mod/sodium
                              ^^^^^^
                              this is the slug
   ```
4. The slug is always the last part after `/mod/`

**More examples:**

| Mod Name | URL | Slug |
|----------|-----|------|
| Fabric API | `modrinth.com/mod/fabric-api` | `fabric-api` |
| Sodium | `modrinth.com/mod/sodium` | `sodium` |
| Lithium | `modrinth.com/mod/lithium` | `lithium` |
| Mod Menu | `modrinth.com/mod/modmenu` | `modmenu` |
| Dynamic Lights | `modrinth.com/mod/dynamic-lights` | `dynamic-lights` |

#### For Resource Packs

Same idea, but the URL has `/resourcepack/` instead of `/mod/`:

```
https://modrinth.com/resourcepack/faithful-32x
                                    ^^^^^^^^^^^^
                                    this is the slug
```

| Resource Pack | URL | Slug |
|---------------|-----|------|
| Faithful 32x | `modrinth.com/resourcepack/faithful-32x` | `faithful-32x` |
| Fresh Animations | `modrinth.com/resourcepack/fresh-animations` | `fresh-animations` |

#### For Data Packs

URL has `/datapack/`:

```
https://modrinth.com/datapack/armor-stand-arms
                               ^^^^^^^^^^^^^^^
                               this is the slug
```

| Data Pack | URL | Slug |
|-----------|-----|------|
| Armor Stand Arms | `modrinth.com/datapack/armor-stand-arms` | `armor-stand-arms` |
| BlazeAndCave's Advancements | `modrinth.com/datapack/blazeandcaves-advancements-pack` | `blazeandcaves-advancements-pack` |

#### Using the Modrinth App

If you use the Modrinth desktop app:
1. Search for a mod/pack
2. Click on it
3. The slug appears in the URL bar at the top of the app window, or right under the project title

---

### Step 3: Configure Your Mod List

Open the script file at `script/modsync-mc.py` in any text editor. You'll see three lists near the top:

#### Mod Priority Tiers

```python
MOD_PRIORITY = {
    "high": [
        "fabric-api",
        "sodium",
        # Add your must-have mods here
    ],
    "medium": [
        "dynamic-fps",
        # Mods you like but can live without
    ],
    "low": [
        "appleskin",
        # Nice-to-have mods
    ],
}
```

**What the tiers mean:**

| Tier | What happens when a mod has no compatible version |
|------|--------------------------------------------------|
| **HIGH** | **Never removed.** Kept in your mods folder no matter what. |
| **MEDIUM** | Script **asks you** (y/n prompt) before removing it. |
| **LOW** | Script **asks you** (y/n prompt) before removing it. |

Any mod that's installed but **not listed** in any tier defaults to **LOW**.

> **Tip:** Put your essential mods (Fabric API, Sodium, Lithium) in `high`. Put cosmetic/optional mods in `medium` or `low`.

#### Resource Packs List

```python
RESOURCE_PACKS = [
    "faithful-32x",
    "fresh-animations",
    # Add more slugs here
]
```

These get automatically downloaded if missing and updated if outdated. Resource packs are **never removed** — only updated.

#### Data Packs List

```python
DATA_PACKS = [
    "armor-stand-arms",
    # Add more slugs here
]
```

Data packs are installed into **every world save** that has a `datapacks/` folder. Like resource packs, they're **never removed**.

---

### Step 4: Set Your Target Minecraft Version

In the same script file, find this line near the top:

```python
GAME_VERSION = "26.1"
```

Change it to whatever Minecraft version you want your mods to target:

- `"1.21.1"` — specific version
- `"1.20.4"` — older version (the script will downgrade mods)
- `"auto"` — automatically detect the latest version from Modrinth

---

### Step 5: Set Your Minecraft Directory

Find this line in the script:

```python
MC_DIR = Path("/Users/vivek/Library/Application Support/minecraft")
```

Change the path to match **your** Minecraft installation:

| OS | Default Path |
|----|-------------|
| **macOS** | `/Users/YOUR_USERNAME/Library/Application Support/minecraft` |
| **Windows** | `C:/Users/YOUR_USERNAME/AppData/Roaming/.minecraft` |
| **Linux** | `/home/YOUR_USERNAME/.minecraft` |

Replace `YOUR_USERNAME` with your actual computer username.

---

## Setting Up the Repository

### Prerequisites

- **Python 3.11+** — [Download here](https://www.python.org/downloads/)
- **uv** (Python package manager) — Install it:
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **Git** — [Download here](https://git-scm.com/downloads)

### Clone the Repo

```bash
git clone https://github.com/VivekGits7/modsync-mc.git
cd modsync-mc
```

### Sync Dependencies with UV

UV handles all the Python dependencies. Run this once after cloning:

```bash
uv sync
```

This reads `pyproject.toml` and installs:
- `aiohttp` — async HTTP client for talking to the Modrinth API
- `python-dotenv` — loads your `.env` file with the API token

If you ever pull new changes that add dependencies, just run `uv sync` again.

---

## Running the Script

After you've done the setup above (token, config, dependencies), run:

```bash
uv run python script/modsync-mc.py
```

That's it. The script will:

1. Connect to the Modrinth API
2. Scan your mods folder, resource packs, and data packs
3. Show you what's up-to-date, what needs updating, and what's incompatible
4. Download updates automatically
5. Ask you before removing anything
6. Run a final cross-check to verify everything matches

### Dry Run Mode

Want to see what the script *would* do without changing any files? Set this in the script:

```python
DRY_RUN = True
```

Then run normally. It'll show all the actions but won't download or delete anything.

---

## Features

- **Bulk update** all Fabric mods to any target Minecraft version
- **Downgrade support** — switch to an older MC version and the script adjusts everything
- **Priority system** — control which mods are never removed, which ones ask, and which are expendable
- **Resource pack sync** — auto-install and update resource packs from Modrinth (never removed)
- **Data pack sync** — auto-install data packs into all world saves (never removed)
- **Auto-reinstall** — mods you removed because they were incompatible get automatically reinstalled when a compatible version drops
- **Final cross-check** — verifies every single mod in your folder actually supports your target MC version
- **SHA1 integrity** — every download is hash-verified against Modrinth's checksums
- **Run history** — tracks every run in `database.json` (last 50 runs) so you can see what changed
- **Dry run mode** — preview all changes without touching any files

---

## Project Structure

```
modsync-mc/
├── script/
│   └── modsync-mc.py          # The main script — all logic lives here
├── .env                       # Your Modrinth API token (create this yourself)
├── .env.example               # Template showing required env vars
├── .gitignore                 # Keeps secrets and generated files out of git
├── pyproject.toml             # Python dependencies (aiohttp, python-dotenv)
├── .python-version            # Python 3.11+
└── README.md                  # You are here
```

**Auto-generated files (git-ignored):**

| File | Purpose |
|------|---------|
| `.updater-state.json` | Tracks the current state of all mods/packs between runs |
| `database.json` | History of the last 50 runs (what was updated, removed, installed) |

---

## Tech Stack

| Tool | Purpose |
|------|---------|
| **Python 3.11+** | Runtime |
| **aiohttp** | Async HTTP client for Modrinth API calls |
| **python-dotenv** | Loads `.env` file for the API token |
| **Modrinth API v2** | Mod/resource pack/data pack lookup, versioning, downloads |
| **uv** | Fast Python package manager |

---

## License

MIT License — [Vivek Vishwakarma](https://github.com/VivekGits7)
