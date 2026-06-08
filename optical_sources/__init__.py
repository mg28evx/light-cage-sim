from .cache import find_cached_observations, source_status as cache_status
from .copernicus import fetch_observations as fetch_copernicus_observations
from .copernicus import source_status as copernicus_status
from .nasa_oceancolor import fetch_observations as fetch_nasa_observations
from .nasa_oceancolor import source_status as nasa_status
from .noaa_coastwatch import fetch_observations as fetch_noaa_observations
from .noaa_coastwatch import source_status as noaa_status
from .sentinel2 import fetch_observations as fetch_sentinel2_observations
from .sentinel2 import source_status as sentinel2_status


def get_source_status():
    return {
        "cache": cache_status(),
        "copernicus": copernicus_status(),
        "nasa_oceancolor": nasa_status(),
        "noaa_coastwatch": noaa_status(),
        "sentinel2": sentinel2_status(),
    }


def fetch_remote_observations(center, start_date=None, end_date=None, buffer_m=1000, source="auto"):
    source_map = {
        "copernicus": fetch_copernicus_observations,
        "noaa_coastwatch": fetch_noaa_observations,
        "nasa_oceancolor": fetch_nasa_observations,
        "sentinel2": fetch_sentinel2_observations,
    }
    if source == "auto":
        sources = [
            fetch_copernicus_observations,
            fetch_noaa_observations,
            fetch_nasa_observations,
            fetch_sentinel2_observations,
        ]
    else:
        sources = [source_map[source]] if source in source_map else []

    diagnostics = []
    for fetcher in sources:
        result = fetcher(center, start_date=start_date, end_date=end_date, buffer_m=buffer_m)
        observations = result.get("observations", [])
        diagnostics.append(result.get("diagnostic", {}))
        if observations:
            return observations, diagnostics
    return [], diagnostics
