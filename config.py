"""Configuration centrale du projet 19 (lue depuis les variables d'environnement / fichier .env)."""
import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent


def _charger_env():
    f = RACINE / ".env"
    if f.exists():
        for ligne in f.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#") and "=" in ligne:
                k, v = ligne.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_charger_env()

# --- PostgreSQL : base source "fournisseurs" + entrepôt de données ---
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DB_SOURCE = os.getenv("PG_DB_SOURCE", "src_fournisseurs")
PG_DB_DWH = os.getenv("PG_DB_DWH", "dwh_scms")

# --- MySQL / MariaDB : base source "entrepôts régionaux" ---
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "scms")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "scms")
MYSQL_DB = os.getenv("MYSQL_DB", "src_entrepots")

# --- Dossiers ---
DATA = Path(os.getenv("DATA_DIR", RACINE / "data"))
SOURCES = DATA / "sources"          # fichiers sources (CSV, Excel, XML, JSON)
CACHE_API = DATA / "api_cache"      # instantanés de secours des API
DEPOT = DATA / "depot"              # dossier surveillé (déclenchement par dépôt de fichier)
ARCHIVE = DATA / "archive"          # fichiers déposés déjà traités
VERITE = DATA / "verite_terrain"    # vérité terrain pour évaluer ML/NLP (pas une source ETL)
MODELES = DATA / "modeles"
LOGS = DATA / "logs"

for d in (SOURCES, CACHE_API, DEPOT, ARCHIVE, VERITE, MODELES, LOGS):
    d.mkdir(parents=True, exist_ok=True)

# --- API ---
# OFFLINE=1 : on n'appelle pas les API et on lit directement les instantanés de data/api_cache
OFFLINE = os.getenv("OFFLINE", "0") == "1"
EIA_API_KEY = os.getenv("EIA_API_KEY", "")            # clé gratuite : https://www.eia.gov/opendata/
COMTRADE_API_KEY = os.getenv("COMTRADE_API_KEY", "")  # clé gratuite : https://comtradedeveloper.un.org/
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "20"))

# --- Génération ---
ECHELLE = float(os.getenv("ECHELLE", "1.0"))   # facteur de montée en charge des sources générées
GRAINE = int(os.getenv("GRAINE", "19"))
DATE_DEBUT = "2006-01-01"
DATE_FIN = "2015-12-31"


def url_pg(db: str) -> str:
    return f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db}"


def url_mysql() -> str:
    return f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
