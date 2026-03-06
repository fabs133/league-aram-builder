import requests
from pathlib import Path
from backend.static_data.loader import StaticData, DD_BASE_URL, CACHE_DIR


def check_and_update(static_data: StaticData) -> bool:
    """Returns True if data was refreshed."""
    try:
        r = requests.get(f"{DD_BASE_URL}/api/versions.json", timeout=5)
        r.raise_for_status()
        current_version = r.json()[0]
    except Exception:
        return False

    # Check if cache exists for current version
    aug_cache = CACHE_DIR / f"augments_{current_version}.json"
    item_cache = CACHE_DIR / f"items_{current_version}.json"

    if aug_cache.exists() and item_cache.exists():
        return False

    static_data.load()
    return True


def force_refresh(static_data: StaticData) -> dict:
    """Delete all cached data and reload from APIs.

    Returns:
        Dict with counts of loaded data.
    """
    # Remove all cached augment and item files
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("augments_*.json"):
            f.unlink()
        for f in CACHE_DIR.glob("items_*.json"):
            f.unlink()

    static_data.load()

    return {
        "champions": len(static_data._champions),
        "augments": len(static_data._augments),
        "items": len(static_data._items),
    }
