import importlib.util
import os


def source_status():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    return {
        "label": "Sentinel-2 / Earth Engine",
        "available": importlib.util.find_spec("ee") is not None,
        "configured": bool(project),
        "detail": "Configurar Earth Engine y GOOGLE_CLOUD_PROJECT para alta resolucion costera.",
    }


def fetch_observations(center, start_date=None, end_date=None, buffer_m=1000):
    status = source_status()
    diagnostic = {
        "source": "sentinel2",
        "status": "skipped",
        "detail": status["detail"],
    }
    if not status["available"]:
        diagnostic["detail"] = "Paquete earthengine-api no instalado."
        return {"observations": [], "diagnostic": diagnostic}
    if not status["configured"]:
        return {"observations": [], "diagnostic": diagnostic}

    diagnostic["status"] = "not_implemented"
    diagnostic["detail"] = "Conector listo; falta calibrar algoritmos S2 para TSS/Chl/CDOM locales."
    return {"observations": [], "diagnostic": diagnostic}
