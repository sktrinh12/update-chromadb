import sqlite3
import os
from datetime import datetime, timezone

CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma")
DB_PATH = os.path.join(CHROMA_DIR, "chroma.sqlite3")

def parse_mixed_date(value: str):
    """
    Parse various timestamp formats found in the metadata.
    Returns a UTC-aware datetime or None.
    """
    if not value:
        return None

    value = value.strip()

    # Try ISO 8601
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Already offset-aware
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Try "January 28, 2025 at 20:08 UTC" or similar
    try:
        # Remove comma, "at", and "UTC"
        cleaned = value.replace(",", "").replace(" at ", " ").replace(" UTC", "")
        dt = datetime.strptime(cleaned, "%B %d %Y %H:%M")
        # Make it UTC-aware
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    # If all parsing fails
    return None


def get_latest_modified_date():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Chroma database not found at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT string_value FROM embedding_metadata
        WHERE key IN ('changedDate', 'modifiedDate', 'createdDate')
    """)
    rows = cursor.fetchall()
    conn.close()

    latest = None
    for (value,) in rows:
        dt = parse_mixed_date(value)
        if dt and (latest is None or dt > latest):
            latest = dt

    if latest:
        # Always print UTC ISO format
        print(latest.isoformat().replace("+00:00", "Z"))
    else:
        print("1970-01-01T00:00:00Z")  # fallback if none found


if __name__ == "__main__":
    get_latest_modified_date()
