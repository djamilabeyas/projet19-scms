"""EXTRACTION des 15 sources.

Chaque extracteur renvoie un objet Extraction :
  df              : données brutes (toutes colonnes)
  perimetre       : 'complet' (toutes les clés de la source sont présentes -> suppressions = clés absentes),
                    'fichiers' (seules les clés des fichiers relus sont comparées),
                    'delta'    (extraction partielle par filigrane, suppressions fournies par le CDC)
  suppressions    : clés supprimées signalées par la source (CDC)
  filigrane       : nouvelle valeur de filigrane à enregistrer si l'étape réussit
  fichiers        : [(chemin, md5, taille)] relus, à marquer comme traités
  origine         : 'api' | 'cache' | 'fichier' | 'postgres' | 'mysql'
"""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests
from lxml import etree

import config
from etl import bdd
from etl.journal import log, lire_filigrane, avec_relance
from generateurs.referentiel import PAYS, DEVISES


@dataclass
class Extraction:
    df: pd.DataFrame
    perimetre: str = "complet"
    suppressions: list = field(default_factory=list)
    filigrane: object = None
    fichiers: list = field(default_factory=list)
    fichiers_lus: list = field(default_factory=list)   # chemins relatifs des fichiers relus (périmètre 'fichiers')
    origine: str = "fichier"


# ------------------------------------------------------------------ utilitaires fichiers
def md5(chemin: Path) -> str:
    h = hashlib.md5()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def rel(p: Path) -> str:
    return p.relative_to(config.SOURCES).as_posix()


def fichiers_a_lire(cx, source, motif, mode):
    """Renvoie (fichiers à relire, infos md5, chemins disparus). En incrémental, un fichier inchangé est ignoré."""
    tous = sorted(config.SOURCES.glob(motif))
    with cx.cursor() as c:
        c.execute("SELECT chemin, hachage_fichier FROM etl.fichier_traite WHERE source = %s", (source,))
        connus = dict(c.fetchall())
    a_lire, infos = [], []
    for f in tous:
        h = md5(f)
        if mode == "COMPLET" or connus.get(rel(f)) != h:
            a_lire.append(f)
            infos.append((rel(f), h, f.stat().st_size))
    disparus = [c for c in connus if not (config.SOURCES / c).exists()]
    return a_lire, infos, disparus


# ------------------------------------------------------------------ API (avec repli sur instantané)
@avec_relance(essais=2, attente=1.0)
def _get(url, params=None, headers=None):
    r = requests.get(url, params=params, headers=headers, timeout=config.API_TIMEOUT)
    r.raise_for_status()
    return r.json()


def appel_api(nom, url, params=None, headers=None, cache=None, requis=None, forcer_cache=False, valider=None):
    """Appelle l'API ; en cas d'échec (réseau, clé manquante, quota, réponse au format inattendu)
    lit l'instantané local. `valider(js)` vérifie la structure de la réponse avant de l'utiliser."""
    if forcer_cache:
        return json.loads(cache.read_text(encoding="utf-8")), "cache"
    if not config.OFFLINE and (requis is None or requis):
        try:
            js = _get(url, params, headers)
            if valider is None or valider(js):
                return js, "api"
            log.warning(f"[{nom}] réponse au format inattendu ({str(js)[:150]}) -> repli sur l'instantané {cache.name}")
        except Exception as e:  # noqa
            log.warning(f"[{nom}] API injoignable ({type(e).__name__}) -> repli sur l'instantané {cache.name}")
    elif requis is not None and not requis:
        log.info(f"[{nom}] clé d'API absente -> instantané {cache.name}")
    return json.loads(cache.read_text(encoding="utf-8")), "cache"


def _debut_api(cx, source, mode, recul_j=7):
    """Filigrane date : on relit les `recul_j` derniers jours pour capter d'éventuelles révisions."""
    if mode == "COMPLET":
        return pd.Timestamp(config.DATE_DEBUT)
    wm = lire_filigrane(cx, source)
    return pd.Timestamp(wm) - pd.Timedelta(days=recul_j) if wm else pd.Timestamp(config.DATE_DEBUT)


def ext_api_brent(cx, mode):
    debut = _debut_api(cx, "api_brent", mode)
    js, orig = appel_api("EIA", "https://api.eia.gov/v2/petroleum/pri/spt/data/",
                         params={"api_key": config.EIA_API_KEY, "frequency": "daily", "data[0]": "value",
                                 "facets[series][]": "RBRTE", "start": debut.strftime("%Y-%m-%d"),
                                 "end": config.DATE_FIN, "length": 5000},
                         cache=config.CACHE_API / "eia_brent.json", requis=bool(config.EIA_API_KEY),
                         valider=lambda j: bool(j.get("response", {}).get("data")))
    df = pd.DataFrame(js["response"]["data"])
    df = df[pd.to_datetime(df["period"]) >= debut]
    return Extraction(df, perimetre="delta", filigrane=df["period"].max() if len(df) else None, origine=orig)


def ext_api_change(cx, mode):
    debut = _debut_api(cx, "api_change", mode)
    js, orig = appel_api("Frankfurter", f"https://api.frankfurter.app/{debut:%Y-%m-%d}..{config.DATE_FIN}",
                         params={"from": "USD", "to": ",".join(DEVISES)}, cache=config.CACHE_API / "frankfurter_usd.json",
                         valider=lambda j: isinstance(j, dict) and bool(j.get("rates")))
    lignes = [{"date": d, "devise": k, "taux": v} for d, r in js["rates"].items() if pd.Timestamp(d) >= debut
              for k, v in r.items()]
    df = pd.DataFrame(lignes)
    return Extraction(df, perimetre="delta", filigrane=df["date"].max() if len(df) else None, origine=orig)


def ext_api_meteo(cx, mode):
    """34 villes. Si une seule ville échoue (quota Open-Meteo : erreur 429), on reprend TOUTES les villes depuis
    l'instantané, pour ne pas mélanger météo réelle et météo de l'instantané dans le même chargement."""
    import time
    debut = _debut_api(cx, "api_meteo", mode)

    def lire(forcer):
        morceaux, origines = [], set()
        for p in PAYS:
            iso3, lat, lon = p[2], p[5], p[6]
            js, orig = appel_api("Open-Meteo", "https://archive-api.open-meteo.com/v1/archive", forcer_cache=forcer,
                                 params={"latitude": lat, "longitude": lon, "start_date": debut.strftime("%Y-%m-%d"),
                                         "end_date": config.DATE_FIN, "timezone": "GMT",
                                         "daily": "temperature_2m_max,precipitation_sum,wind_speed_10m_max"},
                                 cache=config.CACHE_API / "open_meteo" / f"{iso3}.json",
                                 valider=lambda j: isinstance(j, dict) and bool(j.get("daily", {}).get("time")))
            origines.add(orig)
            if orig == "cache" and not forcer:
                return None, origines
            d = pd.DataFrame(js["daily"]); d["iso3"] = iso3
            morceaux.append(d[pd.to_datetime(d["time"]) >= debut])
            if not forcer:
                time.sleep(1.0)  # ménage le quota de l'API gratuite
        return morceaux, origines

    morceaux, origines = lire(False)
    if morceaux is None:
        log.warning("[Open-Meteo] au moins une ville en échec -> toutes les villes depuis l'instantané (cohérence)")
        morceaux, origines = lire(True)
    df = pd.concat(morceaux, ignore_index=True)
    return Extraction(df, perimetre="delta", filigrane=df["time"].max() if len(df) else None, origine="/".join(sorted(origines)))


def ext_api_banque_mondiale(cx, mode):
    morceaux, origines = [], set()
    isos = ";".join(p[2] for p in PAYS)
    for code in ["NY.GDP.PCAP.CD", "SP.POP.TOTL", "PV.EST", "RQ.EST"]:
        js, orig = appel_api("Banque mondiale", f"https://api.worldbank.org/v2/country/{isos}/indicator/{code}",
                             forcer_cache="cache" in origines,
                             params={"format": "json", "date": "2006:2015", "per_page": 2000},
                             cache=config.CACHE_API / f"worldbank_{code.replace('.', '_')}.json",
                             valider=lambda j: isinstance(j, list) and len(j) > 1 and bool(j[1]))
        origines.add(orig)
        d = pd.json_normalize(js[1])
        morceaux.append(d[["countryiso3code", "date", "value", "indicator.id", "indicator.value"]])
    return Extraction(pd.concat(morceaux, ignore_index=True), perimetre="complet", origine="/".join(sorted(origines)))


def ext_api_comtrade(cx, mode):
    js, orig = appel_api("UN Comtrade", "https://comtradeapi.un.org/data/v1/get/C/A/HS",
                         params={"reporterCode": "", "period": ",".join(str(a) for a in range(2006, 2016)),
                                 "cmdCode": "3004", "flowCode": "M", "partnerCode": "0"},
                         headers={"Ocp-Apim-Subscription-Key": config.COMTRADE_API_KEY},
                         cache=config.CACHE_API / "comtrade_3004.json", requis=bool(config.COMTRADE_API_KEY),
                         valider=lambda j: isinstance(j, dict) and bool(j.get("data")))
    return Extraction(pd.DataFrame(js["data"]), perimetre="complet", origine=orig)


# ------------------------------------------------------------------ bases relationnelles (filigrane updated_at + CDC)
def _ext_bdd(cx, source, sql_complet, sql_delta, sql_suppr, moteur, mode):
    wm = lire_filigrane(cx, source)
    if mode == "COMPLET" or wm is None:
        df = pd.read_sql(sql_complet, bdd.moteur(moteur))
        perim, suppr = "complet", []
    else:
        df = pd.read_sql(sql_delta, bdd.moteur(moteur), params={"wm": wm})
        suppr = pd.read_sql(sql_suppr, bdd.moteur(moteur), params={"wm": wm})["cle"].astype(str).tolist()
        perim = "delta"
    nouveaux = [str(df["updated_at"].max())] if len(df) else []
    s = pd.read_sql("SELECT max(supprime_le) m FROM journal_suppressions", bdd.moteur(moteur))["m"].iloc[0]
    if s is not None and not pd.isna(s):
        nouveaux.append(str(s))
    fil = max(nouveaux + ([wm] if wm else [])) if (nouveaux or wm) else None
    return Extraction(df, perimetre=perim, suppressions=suppr, filigrane=fil, origine=moteur)


def ext_pg_fournisseurs(cx, mode):
    return _ext_bdd(cx, "pg_fournisseurs", "SELECT * FROM fournisseur",
                    "SELECT * FROM fournisseur WHERE updated_at > %(wm)s",
                    "SELECT cle FROM journal_suppressions WHERE table_source='fournisseur' AND supprime_le > %(wm)s",
                    "src_pg", mode)


def ext_mysql_entrepots(cx, mode):
    return _ext_bdd(cx, "mysql_entrepots", "SELECT * FROM entrepot", "SELECT * FROM entrepot WHERE updated_at > %(wm)s",
                    "SELECT cle FROM journal_suppressions WHERE table_source='entrepot' AND supprime_le > %(wm)s",
                    "src_mysql", mode)


def ext_mysql_mouvements(cx, mode):
    return _ext_bdd(cx, "mysql_mouvements", "SELECT * FROM mouvement_stock",
                    "SELECT * FROM mouvement_stock WHERE updated_at > %(wm)s",
                    "SELECT cle FROM journal_suppressions WHERE table_source='mouvement_stock' AND supprime_le > %(wm)s",
                    "src_mysql", mode)


# ------------------------------------------------------------------ fichiers
def _ext_fichiers(cx, source, motif, mode, lecteur):
    a_lire, infos, disparus = fichiers_a_lire(cx, source, motif, mode)
    morceaux = []
    for f in a_lire:
        d = lecteur(f)
        d["_fichier"] = rel(f)
        morceaux.append(d)
    df = pd.concat(morceaux, ignore_index=True) if morceaux else pd.DataFrame(columns=["_fichier"])
    return Extraction(df, perimetre="complet" if mode == "COMPLET" else "fichiers", fichiers=infos,
                      fichiers_lus=[i[0] for i in infos] + disparus, origine="fichier")


def ext_csv_scms(cx, mode):
    return _ext_fichiers(cx, "csv_scms", "scms/*.csv", mode, lambda f: pd.read_csv(f, dtype=str, keep_default_na=False))


def ext_csv_douane(cx, mode):
    return _ext_fichiers(cx, "csv_douane", "dedouanement*.csv", mode,
                         lambda f: pd.read_csv(f, sep=";", dtype=str, keep_default_na=False))


def ext_csv_incidents(cx, mode):
    return _ext_fichiers(cx, "csv_incidents", "incidents_transport*.csv", mode,
                         lambda f: pd.read_csv(f, dtype=str, keep_default_na=False))


def ext_excel_tarifs(cx, mode):
    return _ext_fichiers(cx, "excel_tarifs", "tarifs_fret*.xlsx", mode,
                         lambda f: pd.read_excel(f, sheet_name="Tarifs", dtype=str))


def ext_excel_polices(cx, mode):
    return _ext_fichiers(cx, "excel_polices", "assurance_cargo*.xlsx", mode,
                         lambda f: pd.read_excel(f, sheet_name="Polices", dtype=str))


def ext_excel_sinistres(cx, mode):
    return _ext_fichiers(cx, "excel_sinistres", "assurance_cargo*.xlsx", mode,
                         lambda f: pd.read_excel(f, sheet_name="Sinistres", dtype=str))


def _lire_lpi(f):
    feuilles = pd.read_excel(f, sheet_name=None, header=2, dtype=str)
    return pd.concat(feuilles.values(), ignore_index=True)


def ext_excel_lpi(cx, mode):
    return _ext_fichiers(cx, "excel_lpi", "International_LPI*.xlsx", mode, _lire_lpi)


def _lire_contrats(f):
    arbre = etree.parse(str(f))
    lignes = []
    for c in arbre.getroot().iter("contrat"):
        mp = c.find("montant_plafond")
        lignes.append({"id_contrat": c.get("id"), "fournisseur": c.findtext("fournisseur"),
                       "date_signature": c.findtext("date_signature"), "montant_plafond": mp.text if mp is not None else None,
                       "devise": mp.get("devise") if mp is not None else None, "statut": c.findtext("statut"),
                       "texte": c.findtext("texte")})
    return pd.DataFrame(lignes)


def ext_xml_contrats(cx, mode):
    return _ext_fichiers(cx, "xml_contrats", "contrats*.xml", mode, _lire_contrats)


def _lire_conteneurs(f):
    return pd.DataFrame(json.loads(f.read_text(encoding="utf-8"))["evenements"])


def ext_json_conteneurs(cx, mode):
    return _ext_fichiers(cx, "json_conteneurs", "conteneurs/*.json", mode, _lire_conteneurs)
