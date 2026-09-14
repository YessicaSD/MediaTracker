import os
import re
import shutil
import hashlib
import requests
import frontmatter
from pathlib import Path

# ==========================================
# CONFIGURATION
# ==========================================

# Base directory (Project Root), relative to this script
BASE_DIR = Path(__file__).parent.parent.absolute()

# Source Configuration (Obsidian Vault)
SOURCE_CONFIG = {
    # Root of the dedicated Media Tracker Obsidian vault. Lives inside the
    # repo (gitignored) so opening it in Obsidian is just "open this folder".
    "root": BASE_DIR / "obsidian",

    # Subdirectories within the root to scan
    # Key: Valid 'type' in frontmatter (matches the plugin's note type)
    # Value: Folder name relative to 'root' (must match the plugin's
    # movies_folder / tv_folder / seasons_folder / games_folder / books_folder)
    "folders": {
        "movie": "Movies",
        "tv": "TV",
        "season": "Seasons",
        "videogame": "Games",
        "book": "Books",
    },

    # Centralized covers/banners folder (fallback lookup for local images)
    "covers_dir": "Covers",
}

# Destination Configuration (Hugo)
DEST_CONFIG = {
    "content_dir": BASE_DIR / "content",
    "static_images_dir": BASE_DIR / "static" / "images",
    "cache_dir": BASE_DIR / "static" / "images_cache",

    # Mapping Obsidian types to Hugo content sections
    "section_map": {
        "movie": "movies",
        "tv": "tv",
        "season": "seasons",
        "videogame": "games",
        "book": "books",
    }
}

# Frontmatter Fields to Clean/Process
# These keys contain wikilinks that need to be cleaned up
FRONTMATTER_LINKS = ["serie", "series", "temporadas", "seasons", "related"]

# Map raw status values from the plugin to the canonical keys used by the
# theme (finished / in_progress / paused / dropped / not_started). Values not
# listed are written unchanged.
STATUS_MAP = {
    "Finished": "finished",
    "In Progress": "in_progress",
    "Paused": "paused",
    "Dropped": "dropped",
    "Not Started": "not_started",
    "Acabado": "finished",
    "En Curso": "in_progress",
    "Pausado": "paused",
    "Abandonado": "dropped",
    "Sin Empezar": "not_started",
}

# ==========================================
# INITIALIZATION
# ==========================================

# Define full source paths
SOURCE_ROOT = SOURCE_CONFIG["root"]
SOURCE_DIRS = {k: SOURCE_ROOT / v for k, v in SOURCE_CONFIG["folders"].items()}
SOURCE_COVERS_DIR = SOURCE_ROOT / SOURCE_CONFIG["covers_dir"]

# Define full destination paths
COVERS_DIR = DEST_CONFIG["static_images_dir"] / "covers"
BANNERS_DIR = DEST_CONFIG["static_images_dir"] / "banners"

# Ensure directories exist
DEST_CONFIG["cache_dir"].mkdir(parents=True, exist_ok=True)
COVERS_DIR.mkdir(parents=True, exist_ok=True)
BANNERS_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def clean_wikilink(text):
    """
    Parses Obsidian wikilinks:
    [[Name]] -> Name
    [[Path/To/Name|Alias]] -> Alias
    """
    if not isinstance(text, str):
        return text

    match = re.search(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', text)
    if match:
        return match.group(1)
    return text

def convert_wikilinks(text, known_files):
    """
    Converts [[Path/To/Note|Alias]] to [Alias]({{< ref "Note" >}})
    Only if "Note" is in known_files.
    """
    def replacer(match):
        inner = match.group(1)
        alias = inner
        target = inner

        if '|' in inner:
            target, alias = inner.split('|', 1)

        filename = target.split('/')[-1]
        if filename.endswith('.md'):
            filename = filename[:-3]

        if filename in known_files:
            return f'[{alias}]({{{{< ref "{filename}" >}}}})'
        else:
            return alias

    # Negative lookbehind to avoid matching ![[...]] (images)
    return re.sub(r'(?<!\!)\[\[(.*?)\]\]', replacer, text)

def get_image_filename(source_str):
    """
    Generates a unique filename.
    PRIORITY 1: Image ID extracted from URL (TMDB/TVDB) to allow cover updates.
    PRIORITY 2: MD5 Hash of the full string (for local files or rare URLs).
    """
    source_str = str(source_str)

    if "tmdb.org" in source_str:
        try:
            filename_with_ext = source_str.split('/')[-1]
            image_id = filename_with_ext.split('.')[0]
            ext = filename_with_ext.split('.')[1]
            return f"tmdb_{image_id}.{ext}"
        except Exception:
            pass

    if "thetvdb.com" in source_str:
        try:
            filename_with_ext = source_str.split('/')[-1]
            image_id = filename_with_ext.split('.')[0]
            ext = filename_with_ext.split('.')[1]
            return f"tvdb_{image_id}.{ext}"
        except Exception:
            pass

    if "steamgriddb" in source_str:
        try:
            filename_with_ext = source_str.split('/')[-1]
            image_id = filename_with_ext.split('.')[0]
            ext = filename_with_ext.split('.')[1]
            return f"steamgriddb_{image_id}.{ext}"
        except Exception:
            pass

    if "steamstatic.com" in source_str:
        try:
            parts = source_str.split('/')
            app_id = parts[-2]
            filename_with_ext = parts[-1]
            image_name = filename_with_ext.split('.')[0]
            ext = filename_with_ext.split('.')[-1].split('?')[0]
            return f"steam_{app_id}_{image_name}.{ext}"
        except Exception:
            pass

    # Generic case / local files / IGDB / Open Library: hash of the string
    ext = ".jpg"
    if "." in source_str:
        possible_ext = source_str.split(".")[-1].split("?")[0]
        if len(possible_ext) <= 4:
            ext = "." + possible_ext

    hash_object = hashlib.md5(source_str.encode())
    return f"img_{hash_object.hexdigest()}{ext}"

# Filenames already in one of our canonical forms (produced by a previous
# migration run) are reused as-is instead of re-hashed, so re-running the
# migration on an already-migrated local image is a no-op rename-wise.
ALREADY_MIGRATED_NAME = re.compile(r'^(tmdb|tvdb|steamgriddb|steam|img)_')

def resolve_local_image(source_str):
    """
    Resolves an Obsidian local wikilink (e.g. "[[cover.jpg]]") to an
    existing file on disk, searching the same locations the plugin/vault
    would use. Returns a Path or None.
    """
    raw_path = re.search(r'\[\[(.*?)(\|.*)?\]\]', source_str)
    if not raw_path:
        return None
    clean_path = raw_path.group(1)

    for candidate in (
        BASE_DIR / clean_path,
        SOURCE_COVERS_DIR / os.path.basename(clean_path),
        SOURCE_ROOT / clean_path,
    ):
        if candidate.exists():
            return candidate
    return None

def process_image(source_str, note_dest_dir, type="cover"):
    """
    Downloads URL or copies local file.
    1. Checks/saves to CACHE_DIR.
    2. Copies from CACHE_DIR to the note's page-bundle directory.
    Returns the relative path for Hugo frontmatter.
    """
    if not source_str:
        return None

    is_local_image = "[[" in source_str
    local_file = resolve_local_image(source_str) if is_local_image else None

    if local_file and ALREADY_MIGRATED_NAME.match(local_file.name):
        filename = local_file.name
    else:
        filename = get_image_filename(source_str)

    cache_path = DEST_CONFIG["cache_dir"] / filename

    if type in ("content", "cover", "banner"):
        if note_dest_dir:
            dest_dir = note_dest_dir  # e.g. content/movies/avatar/
            dest_path = dest_dir / filename
            return_path = filename
        else:
            dest_dir = COVERS_DIR
            dest_path = dest_dir / filename
            return_path = f"/images/covers/{filename}"
    else:
        dest_path = DEST_CONFIG["static_images_dir"] / "misc" / filename
        return_path = f"/images/misc/{filename}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if not cache_path.exists():
        if str(source_str).startswith("http"):
            try:
                print(f"  [Downloading] {source_str} -> {filename}")
                headers = {'User-Agent': 'Mozilla/5.0'}
                response = requests.get(source_str, stream=True, timeout=10, headers=headers)
                if response.status_code == 200:
                    with open(cache_path, 'wb') as f:
                        shutil.copyfileobj(response.raw, f)
            except Exception as e:
                print(f"  [Error] Failed to download {source_str}: {e}")
                return None

        elif is_local_image:
            if local_file:
                print(f"  [Caching] {local_file.name}")
                shutil.copy(local_file, cache_path)
            else:
                print(f"  [Warning] Local image not found for: {source_str}")
                return None

    if cache_path.exists():
        if not dest_path.exists():
            shutil.copy(cache_path, dest_path)
        return return_path

    return None

def convert_youtube_links(text):
    """
    Converts YouTube links in the content to Hugo shortcodes.
    """
    def replacer(match):
        url = match.group(0)
        video_id = None

        if "youtube.com/watch?v=" in url:
            video_id = url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]

        if video_id:
            return f'{{{{< youtube {video_id} >}}}}'
        return url

    youtube_pattern = r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+|https?://youtu\.be/[\w-]+)'
    return re.sub(youtube_pattern, replacer, text)

# ==========================================
# MAIN MIGRATION LOGIC
# ==========================================

def migrate():
    print("--- STARTING MIGRATION ---")

    # 0. PRE-SCAN: Gather all valid files to validate WikiLinks
    known_files = set()
    for _, source_dir in SOURCE_DIRS.items():
        if source_dir.exists():
            for f in source_dir.glob("*.md"):
                known_files.add(f.stem)

    for obsidian_type, source_dir in SOURCE_DIRS.items():
        if not source_dir.exists():
            print(f"Skipping {obsidian_type}: Directory not found ({source_dir})")
            continue

        hugo_section = DEST_CONFIG["section_map"].get(obsidian_type, "others")
        target_dir = DEST_CONFIG["content_dir"] / hugo_section

        # Clean destination section (Danger: removes existing files!)
        shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nProcessing section: {obsidian_type.upper()} -> {hugo_section}/")

        for file_path in source_dir.glob("*.md"):
            try:
                post = frontmatter.load(file_path)

                if post.get('type') != obsidian_type:
                    print(f"  [Warning] Type mismatch: {file_path.name} (Expected {obsidian_type}, got {post.get('type')})")

                print(f"Processing: {file_path.name}")

                # 0. NORMALIZE STATUS to canonical keys
                if post.get('status') in STATUS_MAP:
                    post['status'] = STATUS_MAP[post['status']]

                # 1. PROCESS RELATIONS (WikiLinks)
                for key in FRONTMATTER_LINKS:
                    if post.get(key):
                        if isinstance(post[key], list):
                            post[key] = [clean_wikilink(item) for item in post[key]]
                        else:
                            post[key] = clean_wikilink(post[key])

                # 2. DETECT CONTENT IMAGES
                content_images = []
                if post.content:
                    content_images = re.findall(r'!\[\[(.*?)\]\]', post.content)

                # 3. PREPARE DESTINATION (Force Leaf Bundle)
                slug = file_path.stem
                post_dir = target_dir / slug
                post_dir.mkdir(parents=True, exist_ok=True)
                destination_file = post_dir / "index.md"
                image_target_dir = post_dir

                # 4. PROCESS IMAGES (Cover & Banner)
                if post.get('cover'):
                    new_cover = process_image(post['cover'], image_target_dir, type="cover")
                    if new_cover:
                        post['image'] = new_cover
                    del post['cover']

                if post.get('banner'):
                    new_banner = process_image(post['banner'], image_target_dir, type="banner")
                    if new_banner:
                        post['banner_image'] = new_banner
                    del post['banner']

                # 5. PROCESS CONTENT
                if post.content:
                    if content_images:
                        for image in content_images:
                            new_image = process_image(f"[[{image}]]", image_target_dir, type="content")
                            if new_image:
                                post.content = post.content.replace(f'![[{image}]]', f'![{os.path.basename(image)}]({new_image})')

                    post.content = convert_wikilinks(post.content, known_files)
                    post.content = convert_youtube_links(post.content)

                # 6. WRITE FILE
                with open(destination_file, 'w', encoding='utf-8') as f:
                    f.write(frontmatter.dumps(post))

            except Exception as e:
                print(f"ERROR processing {file_path.name}: {e}")

    print("\n--- MIGRATION FINISHED ---")

if __name__ == "__main__":
    migrate()
