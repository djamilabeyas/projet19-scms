"""Déclencheur 2 · DÉPÔT DE FICHIER (surveillance du dossier data/depot avec watchdog).

  python -m declencheurs.surveillance_dossier

Quand un fichier est déposé (et que sa taille ne bouge plus), il est reconnu d'après son nom, déplacé vers la zone
des sources, archivé, puis l'ETL incrémental est lancé UNIQUEMENT pour la source concernée.
"""
import fnmatch
import shutil
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
from etl.journal import log

# motif du nom de fichier -> (sous-dossier dans data/sources, source ETL)
ROUTAGE = [
    ("incidents_transport*.csv", ".", "csv_incidents"),
    ("dedouanement*.csv", ".", "csv_douane"),
    ("SCMS*.csv", "scms", "csv_scms"),
    ("suivi_*.json", "conteneurs", "json_conteneurs"),
    ("contrats*.xml", ".", "xml_contrats"),
    ("tarifs_fret*.xlsx", ".", "excel_tarifs"),
    ("assurance_cargo*.xlsx", ".", "excel_polices,excel_sinistres"),
    ("International_LPI*.xlsx", ".", "excel_lpi"),
]
_verrou = threading.Lock()


def attendre_stabilite(p: Path, delai=2.0, essais=30):
    """Attend que le fichier ait fini d'être copié (taille stable)."""
    taille = -1
    for _ in range(essais):
        try:
            t = p.stat().st_size
        except FileNotFoundError:
            return False
        if t == taille and t > 0:
            return True
        taille = t
        time.sleep(delai)
    return False


def traiter(p: Path):
    if p.name.startswith(".") or p.suffix in (".tmp", ".part") or not p.is_file():
        return
    for motif, dossier, sources in ROUTAGE:
        if fnmatch.fnmatch(p.name, motif):
            break
    else:
        (config.DEPOT / "non_reconnus").mkdir(exist_ok=True)
        shutil.move(str(p), config.DEPOT / "non_reconnus" / p.name)
        log.warning(f"[dépôt] {p.name} : nom non reconnu, déplacé dans depot/non_reconnus")
        return
    if not attendre_stabilite(p):
        return
    with _verrou:
        dest = config.SOURCES / dossier / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, config.ARCHIVE / f"{time.strftime('%Y%m%d_%H%M%S')}_{p.name}")
        shutil.move(str(p), dest)
        log.info(f"[dépôt] {p.name} reconnu -> {dest.relative_to(config.RACINE)} ; lancement de l'ETL ({sources})")
        from etl.pipeline import executer
        executer("INCREMENTAL", "depot_fichier", p.name, filtre_sources=sources.split(","))


class Gestionnaire(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            threading.Thread(target=traiter, args=(Path(event.src_path),), daemon=True).start()

    def on_moved(self, event):
        if not event.is_directory and Path(event.dest_path).parent == config.DEPOT:
            threading.Thread(target=traiter, args=(Path(event.dest_path),), daemon=True).start()


def main():
    for f in config.DEPOT.iterdir():  # fichiers déposés pendant que le service était arrêté
        if f.is_file():
            traiter(f)
    obs = Observer()
    obs.schedule(Gestionnaire(), str(config.DEPOT), recursive=False)
    obs.start()
    log.info(f"Surveillance du dossier {config.DEPOT} (Ctrl+C pour arrêter)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()


if __name__ == "__main__":
    main()
