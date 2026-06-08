from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "data" / "optical_cache"


def source_status():
    example_path = BASE_DIR / "data" / "optical_observations_example.csv"
    return {
        "label": "Cache local",
        "available": CACHE_DIR.exists() or example_path.exists(),
        "configured": True,
        "detail": str(CACHE_DIR),
    }


def find_cached_observations(center_id, include_example=False):
    if not center_id:
        return None
    candidates = [
        CACHE_DIR / f"{center_id}.csv",
        CACHE_DIR / f"{center_id.lower()}.csv",
    ]
    if include_example:
        candidates.append(BASE_DIR / "data" / "optical_observations_example.csv")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
