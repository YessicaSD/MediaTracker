# Media Tracker

My personal log of movies, series, games and books — a generated Hugo site
built from my Obsidian vault.

## How it works

Content lives in Obsidian. Entries are created with the
[hugo-mediatracker-plugin](https://github.com/christt105/hugo-mediatracker-plugin),
which pulls metadata and artwork from TMDB, TheTVDB, IGDB, Steam and Open
Library. A migration script (`scripts/migration.py`) then converts those
Obsidian notes into Hugo page bundles under `content/`. **`content/` is
therefore generated — manual edits will be overwritten on the next run.**

```
obsidian/  ←── Obsidian vault, notes created by hugo-mediatracker-plugin
      │        (Movies/, TV/, Seasons/, Games/, Books/, Covers/)
      ▼
scripts/migration.py
      │
      ▼
content/  ←── generated, do not edit by hand
      │
      ▼
hugo build → GitHub Actions → GitHub Pages
```

`obsidian/` is a self-contained vault folder at the repo root (gitignored,
same as `content/.obsidian` was before) — open it directly in Obsidian.

## Stack

| Tool | Role |
|------|------|
| [Hugo](https://gohugo.io/) | Static site generator |
| [hugo-mediatracker-theme](https://github.com/christt105/hugo-mediatracker-theme) | Theme (Hugo Module) |
| [Obsidian](https://obsidian.md/) | Note editing / source of truth |
| [hugo-mediatracker-plugin](https://github.com/christt105/hugo-mediatracker-plugin) | Creates entries in Obsidian (TMDB / TheTVDB / IGDB / Steam / Open Library) |
| GitHub Actions | Build & deploy to Pages |

## Adding an entry

1. Open `obsidian/` as a vault in Obsidian (the Media Tracker plugin is
   already installed and configured there).
2. Use the plugin to search and create a note under `Movies/`, `TV/`,
   `Seasons/`, `Games/` or `Books/`.
3. Run the migration script to regenerate `content/`:

   ```bash
   pip install -r requirements.txt
   python scripts/migration.py
   ```

4. Review the diff (`git status` / `git diff`) and commit.

## Running locally

```bash
hugo server
```

Requires Hugo extended + Go (for modules) and Python 3 (for the migration
script). The theme is fetched automatically via `go.mod`.

## RSS feeds

| Feed | URL |
|------|-----|
| All content | `/index.xml` |
| Finished items | `/finished.xml` |
