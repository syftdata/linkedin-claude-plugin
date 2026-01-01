#!/usr/bin/env python3
import os
import csv
import glob
import zipfile
import tempfile
import sys
import subprocess
from pathlib import Path
from argparse import ArgumentParser

# Constants
WATCH_FOLDER = Path.home() / ".linkedin-exports"
DB_PATH = Path.home() / ".linkedin-search" / "data.db"


def find_or_create_venv():
    """Find or create virtual environment using Python's standard venv module"""
    script_dir = Path(__file__).parent
    venv_dir = script_dir / ".venv"
    venv_python = venv_dir / "bin" / "python"

    # If venv already exists and works, use it
    if venv_python.exists():
        try:
            result = subprocess.run(
                [str(venv_python), "-c", "import sys"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return str(venv_python)
        except Exception:
            pass  # Venv exists but is broken, try to recreate

    # Create venv using Python's standard library venv module
    print("🔧 Creating virtual environment (first-time setup)...")
    try:
        import venv
        venv.create(venv_dir, with_pip=True)
        if venv_python.exists():
            print("✓ Virtual environment created")
            return str(venv_python)
    except Exception as e:
        print(f"⚠️  Could not create venv: {e}")
        print("   Will install dependencies to user directory instead")

    return None


def is_venv():
    """Check if currently running in a virtual environment"""
    return hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )


def reexec_in_venv():
    """Re-execute script in venv if not already running in one"""
    if is_venv():
        return  # Already in venv, continue normally

    venv_python = find_or_create_venv()
    if venv_python and Path(venv_python).exists():
        # Re-execute this script with venv Python
        try:
            os.execv(venv_python, [venv_python] + sys.argv)
        except Exception as e:
            print(f"⚠️  Could not re-exec in venv: {e}")
            print("   Continuing with current Python")


# Re-exec in venv before importing dependencies
reexec_in_venv()


def ensure_dependencies():
    """Auto-install sqlite-utils if missing"""
    try:
        import sqlite_utils
        return sqlite_utils
    except ImportError:
        print("📦 Installing sqlite-utils...")

        # Try regular pip install first (works in venv or standard Python)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", "sqlite-utils"],
                timeout=60
            )
            import sqlite_utils
            print("✓ sqlite-utils installed")
            return sqlite_utils
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        # Fallback: pip install --user (works on externally-managed Python)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--user", "-q", "sqlite-utils"],
                timeout=60
            )
            import sqlite_utils
            print("✓ sqlite-utils installed to user directory")
            return sqlite_utils
        except Exception as e:
            print(f"❌ Could not install sqlite-utils: {e}")
            print("   Please install manually: pip install sqlite-utils")
            sys.exit(1)


# Auto-install on import
sqlite_utils = ensure_dependencies()


def ensure_folders_exist():
    """Create necessary folders if they don't exist"""
    WATCH_FOLDER.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def find_latest_export():
    """Find newest ZIP in watch folder by modification time"""
    exports = glob.glob(str(WATCH_FOLDER / "*.zip"))
    if not exports:
        return None
    return max(exports, key=os.path.getmtime)


def get_db_timestamp():
    """Get timestamp of last loaded export from metadata table"""
    if not DB_PATH.exists():
        return 0

    try:
        db = sqlite_utils.Database(DB_PATH)
        if "metadata" in db.table_names():
            result = db.execute(
                "SELECT value FROM metadata WHERE key = 'last_loaded_timestamp'"
            ).fetchone()
            if result:
                return float(result[0])
    except Exception:
        pass

    return 0


def load_shares_csv(csv_path, db):
    """Parse Shares.csv and insert into SQLite"""
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                db["shares"].insert_all(rows, replace=True)
    except FileNotFoundError:
        print(f"⚠️  Shares.csv not found, skipping...")
    except Exception as e:
        print(f"⚠️  Error loading Shares.csv: {e}")


def load_connections_csv(csv_path, db):
    """Parse Connections.csv (skip 3 header lines) and insert into SQLite"""
    try:
        with open(csv_path, encoding="utf-8") as f:
            # Skip the notes section at the beginning
            for _ in range(3):
                f.readline()
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                db["connections"].insert_all(rows, replace=True)
    except FileNotFoundError:
        print(f"⚠️  Connections.csv not found, skipping...")
    except Exception as e:
        print(f"⚠️  Error loading Connections.csv: {e}")


def load_comments_csv(csv_path, db):
    """Parse Comments.csv and insert into SQLite"""
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                db["comments"].insert_all(rows, replace=True)
    except FileNotFoundError:
        print(f"⚠️  Comments.csv not found, skipping...")
    except Exception as e:
        print(f"⚠️  Error loading Comments.csv: {e}")


def load_reactions_csv(csv_path, db):
    """Parse Reactions.csv and insert into SQLite"""
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                db["reactions"].insert_all(rows, replace=True)
    except FileNotFoundError:
        # Reactions file is optional
        pass
    except Exception as e:
        print(f"⚠️  Error loading Reactions.csv: {e}")


def load_export_to_sqlite(zip_path, db_path):
    """Extract ZIP, parse CSVs, load to SQLite, cleanup"""
    # Delete old DB
    if db_path.exists():
        db_path.unlink()

    try:
        # Extract to temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # Find the actual export folder inside
            export_folder = Path(temp_dir)
            subdirs = list(export_folder.glob("Complete_LinkedInDataExport_*"))
            if subdirs:
                export_folder = subdirs[0]

            # Load CSVs to SQLite
            db = sqlite_utils.Database(db_path)

            print("  📊 Loading shares...")
            load_shares_csv(export_folder / "Shares.csv", db)

            print("  👥 Loading connections...")
            load_connections_csv(export_folder / "Connections.csv", db)

            print("  💬 Loading comments...")
            load_comments_csv(export_folder / "Comments.csv", db)

            print("  👍 Loading reactions...")
            load_reactions_csv(export_folder / "Reactions.csv", db)

            # Create indexes for faster searches
            print("  ⚡ Creating indexes...")
            if "shares" in db.table_names():
                db["shares"].create_index(["ShareCommentary"], if_not_exists=True)
                db["shares"].create_index(["Date"], if_not_exists=True)

            if "connections" in db.table_names():
                db["connections"].create_index(["Position"], if_not_exists=True)
                db["connections"].create_index(["Company"], if_not_exists=True)

            if "comments" in db.table_names():
                db["comments"].create_index(["Comment"], if_not_exists=True)
                db["comments"].create_index(["Date"], if_not_exists=True)

            # Save metadata
            metadata_rows = [
                {"key": "last_loaded_zip", "value": str(zip_path)},
                {"key": "last_loaded_timestamp", "value": str(os.path.getmtime(zip_path))},
            ]
            db["metadata"].insert_all(metadata_rows, replace=True)

        # temp_dir auto-deleted with extracted CSVs

    except zipfile.BadZipFile:
        print(f"❌ Error: {zip_path} is not a valid ZIP file")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading export: {e}")
        sys.exit(1)


def prompt_for_export():
    """Prompt user to provide path to LinkedIn export"""
    print("📂 No LinkedIn exports found in ~/.linkedin-exports/")
    print("")
    print("Please provide the path to your LinkedIn export ZIP file.")
    print("(Download from: LinkedIn Settings → Data Privacy → Get a copy of your data)")
    print("")

    path = input("Path to LinkedIn export ZIP: ").strip()

    # Handle quoted paths and ~ expansion
    path = path.strip('"').strip("'")
    path = os.path.expanduser(path)

    if not path:
        print("❌ No path provided")
        sys.exit(1)

    if not os.path.exists(path):
        print(f"❌ File not found: {path}")
        sys.exit(1)

    if not path.endswith('.zip'):
        print("❌ File must be a ZIP archive")
        sys.exit(1)

    # Copy to watch folder
    import shutil
    dest = WATCH_FOLDER / Path(path).name
    print(f"📦 Copying to {dest}...")
    shutil.copy2(path, dest)
    print("✓ Export copied!")

    return str(dest)


def ensure_db_current():
    """Check if DB needs refresh, load latest export if needed"""
    ensure_folders_exist()

    # Find latest export
    latest_export = find_latest_export()
    if not latest_export:
        latest_export = prompt_for_export()

    latest_time = os.path.getmtime(latest_export)
    db_time = get_db_timestamp()

    if latest_time > db_time or not DB_PATH.exists():
        print(f"🔄 Loading {Path(latest_export).name}...")
        load_export_to_sqlite(latest_export, DB_PATH)
        print("✓ Database ready!\n")


def search_shares(query):
    """Search shares by keyword in commentary or shared_url"""
    db = sqlite_utils.Database(DB_PATH)

    if "shares" not in db.table_names():
        print("No posts found")
        return

    results = db.execute(
        """
        SELECT Date, ShareCommentary, ShareLink
        FROM shares
        WHERE (LOWER(ShareCommentary) LIKE ? OR LOWER(SharedUrl) LIKE ?)
        AND Date IS NOT NULL
        ORDER BY Date DESC
    """,
        (f"%{query.lower()}%", f"%{query.lower()}%"),
    ).fetchall()

    if not results:
        print(f"No posts found matching '{query}'")
        return

    print(f"\nFound {len(results)} post(s) matching '{query}':\n")
    for i, (date, commentary, link) in enumerate(results, 1):
        commentary = commentary or ""
        preview = commentary[:150]
        print(f"{i}. [{date}]")
        print(f"   {preview}{'...' if len(commentary) > 150 else ''}")
        print(f"   Link: {link}\n")


def find_connections(title, company):
    """Find connections by title and/or company"""
    db = sqlite_utils.Database(DB_PATH)

    if "connections" not in db.table_names():
        print("No connections found")
        return

    query = "SELECT [First Name], [Last Name], Position, Company FROM connections WHERE 1=1"
    params = []

    if title:
        query += " AND LOWER(Position) LIKE ?"
        params.append(f"%{title.lower()}%")

    if company:
        query += " AND LOWER(Company) LIKE ?"
        params.append(f"%{company.lower()}%")

    query += " ORDER BY Position"

    results = db.execute(query, params).fetchall()

    if not results:
        criteria = []
        if title:
            criteria.append(f"title '{title}'")
        if company:
            criteria.append(f"company '{company}'")
        print(f"No connections found matching {' and '.join(criteria)}")
        return

    print(f"\nFound {len(results)} connection(s):\n")
    for i, (first, last, pos, comp) in enumerate(results, 1):
        print(f"{i}. {first} {last}")
        print(f"   {pos} at {comp}\n")


def search_connections_keywords(keywords):
    """Find connections with all keywords in position/company"""
    db = sqlite_utils.Database(DB_PATH)

    if "connections" not in db.table_names():
        print("No connections found")
        return

    results = db.execute("SELECT [First Name], [Last Name], Position, Company FROM connections").fetchall()

    filtered = []
    for first, last, pos, comp in results:
        combined = (pos or "") + " " + (comp or "")
        combined_lower = combined.lower()

        # Check if all keywords match
        if all(kw.lower() in combined_lower for kw in keywords):
            filtered.append((first, last, pos, comp))

    if not filtered:
        print(f"No connections found with keywords: {', '.join(keywords)}")
        return

    print(f"\nFound {len(filtered)} connection(s) matching keywords {keywords}:\n")
    for i, (first, last, pos, comp) in enumerate(filtered, 1):
        print(f"{i}. {first} {last}")
        print(f"   {pos} at {comp}\n")


def search_comments(query):
    """Search comments by keyword"""
    db = sqlite_utils.Database(DB_PATH)

    if "comments" not in db.table_names():
        print("No comments found")
        return

    results = db.execute(
        """
        SELECT Date, Comment
        FROM comments
        WHERE LOWER(Comment) LIKE ?
        ORDER BY Date DESC
    """,
        (f"%{query.lower()}%",),
    ).fetchall()

    if not results:
        print(f"No comments found matching '{query}'")
        return

    print(f"\nFound {len(results)} comment(s) matching '{query}':\n")
    for i, (date, comment) in enumerate(results, 1):
        preview = comment[:150] if comment else ""
        print(f"{i}. [{date}]")
        print(f"   {preview}{'...' if len(comment or '') > 150 else ''}\n")


def get_stats():
    """Get LinkedIn statistics"""
    db = sqlite_utils.Database(DB_PATH)

    stats = {}

    for table_name in ["shares", "connections", "comments", "reactions"]:
        if table_name in db.table_names():
            count = db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            stats[table_name] = count
        else:
            stats[table_name] = 0

    print("\n=== LinkedIn Statistics ===\n")
    print(f"Posts/Shares: {stats.get('shares', 0)}")
    print(f"Connections: {stats.get('connections', 0)}")
    print(f"Comments: {stats.get('comments', 0)}")
    print(f"Reactions: {stats.get('reactions', 0)}\n")


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    search = subparsers.add_parser("search-shares")
    search.add_argument("--query", required=True)

    find = subparsers.add_parser("find-connections")
    find.add_argument("--title", default="")
    find.add_argument("--company", default="")

    comments = subparsers.add_parser("search-comments")
    comments.add_argument("--query", required=True)

    search_conn_kw = subparsers.add_parser("search-connections-keywords")
    search_conn_kw.add_argument("--keywords", nargs="+", required=True)

    stats = subparsers.add_parser("stats")

    args = parser.parse_args()

    # Ensure DB is current before running any command
    ensure_db_current()

    if args.command == "search-shares":
        search_shares(args.query)
    elif args.command == "find-connections":
        find_connections(args.title, args.company)
    elif args.command == "search-comments":
        search_comments(args.query)
    elif args.command == "search-connections-keywords":
        search_connections_keywords(args.keywords)
    elif args.command == "stats":
        get_stats()
    else:
        parser.print_help()
