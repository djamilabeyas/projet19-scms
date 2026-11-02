"""Orchestrateur ETL du projet 19.

Exemples :
  python -m etl.pipeline --mode complet                 # premier chargement complet
  python -m etl.pipeline --mode incremental             # chargement incrémental (filigranes + hachages + CDC)
  python -m etl.pipeline --reprise                      # reprise sur incident : relance la dernière exécution en échec
  python -m etl.pipeline --mode incremental --sources csv_incidents --declencheur depot_fichier
"""
import argparse
import os
import sys
import time

import pandas as pd

import config
from etl import bdd, delta, referentiels
from etl.journal import (log, VERROU_ETL, ouvrir_execution, fermer_execution, debut_etape, fin_etape, etapes_reussies,
                         derniere_execution_echouee, ecrire_rejets, ecrire_filigrane)
from etl.sources import SOURCES


def initialiser_entrepot():
    bdd.creer_bases()
    bdd.executer_fichier_pg(config.RACINE / "sql" / "entrepot_ddl.sql")
    cx = bdd.pg_connexion()
    with cx.cursor() as c:
        c.execute("SELECT 1 FROM pg_matviews WHERE matviewname = 'mv_expedition'")
        existe = c.fetchone()
    cx.close()
    if not existe:
        bdd.executer_fichier_pg(config.RACINE / "sql" / "vues_indicateurs.sql")


def reinitialiser(cx):
    """Mode COMPLET : on vide l'entrepôt et l'état incrémental (le journal et les rejets sont conservés)."""
    with cx.cursor() as c:
        c.execute("""SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname IN ('dwh', 'ml')""")
        tables = [r[0] for r in c.fetchall()]
        c.execute(f"TRUNCATE {', '.join(tables)}, etl.empreinte, etl.fichier_traite, etl.filigrane RESTART IDENTITY CASCADE")
    cx.commit()


def ecrire_staging(cx, nom, df, rid):
    """Zone de staging : copie brute (texte) de ce qui a été extrait, pour traçabilité et rejeu."""
    table = f"staging.stg_{nom}"
    cols = [c for c in df.columns]
    with cx.cursor() as c:
        c.execute(f"DROP TABLE IF EXISTS {table}")
        defs = ", ".join(f'"{x}" TEXT' for x in cols)
        c.execute(f"CREATE TABLE {table} ({defs}{', ' if defs else ''}_id_execution INTEGER, _extrait_le TIMESTAMP DEFAULT now())")
    if len(df):
        d = df.astype(str).where(df.notna(), None)
        d["_id_execution"] = rid
        bdd.copier_df_pg(d, table, cx, cols + ["_id_execution"])


def traiter_source(cx, rid, src, mode):
    ext = src.extraire(cx, mode)
    brut = ext.df
    ecrire_staging(cx, src.nom, brut, rid)
    k = {"lues": len(brut), "I": 0, "U": 0, "D": 0, "rejets": 0}
    if len(brut) == 0 and not ext.suppressions and not ext.fichiers_lus:
        return k, f"aucune donnée nouvelle ({ext.origine})"
    propre, rejets = src.transformer(brut, cx) if len(brut) else (pd.DataFrame(columns=["cle"] + src.hash_cols), [])
    ecrire_rejets(cx, rid, src.nom, rejets)
    k["rejets"] = len(rejets)
    propre["cle"] = propre["cle"].astype(str)
    d, supprimees = delta.calculer(cx, src.nom, propre, ext, src.hash_cols)
    a_charger = d[d["_op"].isin(["I", "U"])]
    src.charger(cx, rid, a_charger, supprimees, mode)
    delta.maj_empreintes(cx, src.nom, d, supprimees)
    with cx.cursor() as c:
        for chemin, h, taille in ext.fichiers:
            c.execute("""INSERT INTO etl.fichier_traite(source, chemin, hachage_fichier, taille) VALUES (%s,%s,%s,%s)
                         ON CONFLICT (source, chemin) DO UPDATE SET hachage_fichier = EXCLUDED.hachage_fichier,
                         taille = EXCLUDED.taille, traite_le = now()""", (src.nom, chemin, h, taille))
        disparus = [f for f in ext.fichiers_lus if not (config.SOURCES / f).exists()]
        if disparus:
            c.execute("DELETE FROM etl.fichier_traite WHERE source = %s AND chemin = ANY(%s)", (src.nom, disparus))
    ecrire_filigrane(cx, src.nom, ext.filigrane)
    k["I"] = int((d["_op"] == "I").sum()); k["U"] = int((d["_op"] == "U").sum()); k["D"] = len(supprimees)
    return k, f"origine={ext.origine}; périmètre={ext.perimetre}"


def executer(mode="INCREMENTAL", declencheur="manuel", detail=None, reprise=False, filtre_sources=None, avec_ml=True,
             attente_verrou_s=900):
    """Un seul ETL à la fois (verrou consultatif PostgreSQL) : un déclenchement concurrent attend son tour."""
    initialiser_entrepot()
    cx = bdd.pg_connexion()
    t_att = time.time()
    while True:
        with cx.cursor() as c:
            c.execute("SELECT pg_try_advisory_lock(%s)", (VERROU_ETL,))
            if c.fetchone()[0]:
                break
        if time.time() - t_att > attente_verrou_s:
            log.warning(f"Une exécution ETL est en cours depuis plus de {attente_verrou_s} s : déclenchement abandonné.")
            cx.close()
            return None
        if time.time() - t_att < 3:
            log.info("Une exécution ETL est déjà en cours : ce déclenchement attend son tour…")
        time.sleep(3)
    deja, reprise_de = set(), None
    if reprise:
        r = derniere_execution_echouee(cx)
        if not r:
            log.info("Aucune exécution en échec à reprendre.")
            return None
        reprise_de, mode = r
        deja = etapes_reussies(cx, reprise_de)
        log.info(f"Reprise de l'exécution {reprise_de} ({mode}) : {len(deja)} étapes déjà réussies seront ignorées")
    rid = ouvrir_execution(cx, mode, declencheur if not reprise else "reprise", detail, reprise_de)
    log.info(f"=== Exécution {rid} · mode {mode} · déclencheur {declencheur} ===")
    t0 = time.time()
    try:
        if mode == "COMPLET" and not reprise:
            reinitialiser(cx)
        etapes = [("referentiels", None)] + [(s.nom, s) for s in SOURCES
                                             if not filtre_sources or s.nom in filtre_sources]
        if avec_ml:
            etapes.append(("ml_batch", None))
        etapes.append(("controles_finaux", None))
        for nom, src in etapes:
            eid = debut_etape(cx, rid, nom)
            if nom in deja:
                fin_etape(cx, eid, "IGNOREE", message=f"déjà réussie dans l'exécution {reprise_de}")
                continue
            t = time.time()
            try:
                if os.getenv("ETL_PANNE") == nom and not reprise:
                    raise RuntimeError(f"Panne simulée sur l'étape {nom} (variable ETL_PANNE)")
                if nom == "referentiels":
                    referentiels.initialiser(cx); k, msg = {}, "dimensions de référence"
                elif nom == "ml_batch":
                    cx.commit()
                    from ml import batch
                    k, msg = batch.executer(rid)
                elif nom == "controles_finaux":
                    k, msg = controles_finaux(cx)
                else:
                    k, msg = traiter_source(cx, rid, src, mode)
                cx.commit()
                fin_etape(cx, eid, "SUCCES", k, msg)
                log.info(f"[{nom:<20}] OK {time.time() - t:6.1f}s  lues={k.get('lues', 0):>7} I={k.get('I', 0):>7} "
                         f"U={k.get('U', 0):>5} D={k.get('D', 0):>5} rejets={k.get('rejets', 0):>4}  {msg}")
            except Exception as e:
                cx.rollback()
                fin_etape(cx, eid, "ECHEC", message=f"{type(e).__name__}: {e}")
                raise
        fermer_execution(cx, rid, "SUCCES", f"durée {time.time() - t0:.0f} s")
        log.info(f"=== Exécution {rid} terminée avec succès en {time.time() - t0:.0f} s ===")
        return rid
    except Exception as e:
        log.exception(f"Échec de l'exécution {rid} : {e}")
        fermer_execution(cx, rid, "ECHEC", f"{type(e).__name__}: {e}")
        log.error("Relancer avec --reprise pour reprendre à l'étape en échec.")
        return rid
    finally:
        with cx.cursor() as c:
            c.execute("SELECT pg_advisory_unlock(%s)", (VERROU_ETL,))
        cx.commit(); cx.close()


def controles_finaux(cx):
    """Contrôles d'intégrité après chargement + rafraîchissement des vues du tableau de bord."""
    bdd.executer_fichier_pg(config.RACINE / "sql" / "vues_indicateurs.sql")
    anomalies = []
    with cx.cursor() as c:
        for sql, libelle in [
            ("SELECT count(*) FROM dwh.fait_ligne_expedition WHERE pays_sk = -1", "lignes sans pays"),
            ("SELECT count(*) FROM dwh.fait_ligne_expedition WHERE fournisseur_sk = -1", "lignes sans fournisseur"),
            ("SELECT count(*) FROM dwh.dim_fournisseur WHERE est_courant GROUP BY code_fournisseur HAVING count(*) > 1",
             "fournisseurs avec plusieurs versions courantes"),
            ("""SELECT count(*) FROM dwh.fait_dedouanement d LEFT JOIN (SELECT DISTINCT asn_dn FROM dwh.fait_ligne_expedition) e
                USING (asn_dn) WHERE e.asn_dn IS NULL""", "dossiers de douane orphelins")]:
            c.execute(sql)
            r = c.fetchone()
            if r and r[0]:
                anomalies.append(f"{r[0]} {libelle}")
        c.execute("REFRESH MATERIALIZED VIEW dwh.mv_expedition")
        c.execute("ANALYZE")
    return {}, ("RAS" if not anomalies else "; ".join(anomalies))


def main(argv=None):
    p = argparse.ArgumentParser(description="ETL projet 19 – SCMS")
    p.add_argument("--mode", choices=["complet", "incremental"], default="incremental")
    p.add_argument("--declencheur", default="manuel")
    p.add_argument("--detail", default=None)
    p.add_argument("--reprise", action="store_true", help="reprend la dernière exécution en échec")
    p.add_argument("--sources", default=None, help="liste de sources séparées par des virgules")
    p.add_argument("--sans-ml", action="store_true")
    a = p.parse_args(argv)
    rid = executer(a.mode.upper(), a.declencheur, a.detail, a.reprise,
                   a.sources.split(",") if a.sources else None, not a.sans_ml)
    cx = bdd.pg_connexion()
    with cx.cursor() as c:
        c.execute("SELECT statut FROM etl.journal_execution WHERE id_execution = %s", (rid,))
        r = c.fetchone()
    sys.exit(0 if (r is None or r[0] == "SUCCES") else 1)


if __name__ == "__main__":
    main()
