"""Démonstration de bout en bout (à montrer en soutenance) :

  1. chargement COMPLET initial
  2. simulation de modifications dans les sources (insertions, modifications, suppressions)
  3. 1er chargement INCRÉMENTAL  -> les I/U/D sont détectés, SCD2 crée de nouvelles versions
  4. 2e chargement INCRÉMENTAL sans changement -> rien n'est rechargé (fichiers inchangés ignorés)
  5. panne simulée sur une étape, puis REPRISE sur incident à partir de l'étape en échec

  python -m demo.demo_incremental
"""
import os
import subprocess
import sys

import pandas as pd

import config
from etl import bdd
from generateurs import generer_tout


def etl(*args, env=None):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run([sys.executable, "-m", "etl.pipeline", *args], cwd=config.RACINE, env=e, capture_output=True, text=True)
    return r.returncode


def bilan(titre, rid):
    df = pd.read_sql(f"""SELECT etape, statut, lignes_lues lues, lignes_inserees "I", lignes_maj "U", lignes_supprimees "D",
                                lignes_rejetees rejets FROM etl.journal_etape WHERE id_execution = {rid} ORDER BY id_etape""",
                     bdd.moteur("dwh"))
    print(f"\n{'=' * 100}\n{titre} (exécution {rid})\n{'=' * 100}")
    print(df.to_string(index=False))


def dernier_id():
    return int(pd.read_sql("SELECT max(id_execution) m FROM etl.journal_execution", bdd.moteur("dwh"))["m"].iloc[0])


def main():
    print("Régénération des sources (état initial)…")
    generer_tout.main()
    etl("--mode", "complet"); bilan("1. CHARGEMENT COMPLET", dernier_id())
    subprocess.run([sys.executable, "-m", "demo.simuler_modifications"], cwd=config.RACINE, check=True)
    etl("--mode", "incremental"); bilan("3. CHARGEMENT INCRÉMENTAL après modifications", dernier_id())
    scd = pd.read_sql("""SELECT code_fournisseur, version, note_qualite, categorie_risque, est_courant, est_supprime_source,
                                date_debut_validite::date debut, date_fin_validite::date fin
                         FROM dwh.dim_fournisseur WHERE code_fournisseur IN ('F0004','F0009','F0011','F0036','F0100')
                         ORDER BY 1, 2""", bdd.moteur("dwh"))
    print("\nHistorique SCD2 de dim_fournisseur :\n" + scd.to_string(index=False))
    etl("--mode", "incremental"); bilan("4. CHARGEMENT INCRÉMENTAL sans modification", dernier_id())
    # de nouveaux incidents arrivent, mais l'étape csv_incidents tombe en panne pendant le chargement
    inc = pd.read_csv(config.SOURCES / "incidents_transport_2015_12.csv", dtype=str)
    inc["id_incident"] = inc["id_incident"].str.replace("INC-9", "INC-8")
    inc.to_csv(config.SOURCES / "incidents_transport_2015_12_b.csv", index=False)
    etl("--mode", "incremental", env={"ETL_PANNE": "csv_incidents"}); bilan("5a. PANNE SIMULÉE sur csv_incidents", dernier_id())
    etl("--reprise"); bilan("5b. REPRISE SUR INCIDENT", dernier_id())
    print("\n" + pd.read_sql("""SELECT id_execution, mode, declencheur, statut, reprise_de, lignes_inserees, lignes_maj,
                                       lignes_supprimees, lignes_rejetees, debut::timestamp(0), fin::timestamp(0)
                                FROM etl.journal_execution ORDER BY 1 DESC LIMIT 5""", bdd.moteur("dwh")).to_string(index=False))


if __name__ == "__main__":
    main()
