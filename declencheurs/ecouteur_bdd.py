"""Déclencheur 3 · ÉVÉNEMENT BASE DE DONNÉES (trigger PostgreSQL + LISTEN/NOTIFY).

Le trigger `trg_fournisseur_notify` (sql/sources_postgres.sql) publie un message sur le canal `etl_fournisseurs`
à chaque INSERT / UPDATE / DELETE de la table fournisseur. Ce service écoute le canal et lance l'ETL incrémental
de la source pg_fournisseurs. Les rafales d'événements sont regroupées (anti-rebond de 5 s).

  python -m declencheurs.ecouteur_bdd
"""
import json
import select
import time

import config
from etl import bdd
from etl.journal import log

CANAL = "etl_fournisseurs"
ANTI_REBOND_S = 5


def main(duree_max=None):
    cx = bdd.pg_connexion(config.PG_DB_SOURCE, autocommit=True)
    with cx.cursor() as c:
        c.execute(f"LISTEN {CANAL}")
    log.info(f"Écoute du canal PostgreSQL « {CANAL} » sur {config.PG_DB_SOURCE} (Ctrl+C pour arrêter)")
    en_attente, premier, t0 = [], None, time.time()
    try:
        while duree_max is None or time.time() - t0 < duree_max:
            if select.select([cx], [], [], 1.0) != ([], [], []):
                cx.poll()
                while cx.notifies:
                    n = cx.notifies.pop(0)
                    en_attente.append(json.loads(n.payload))
                    premier = premier or time.time()
            if en_attente and time.time() - premier >= ANTI_REBOND_S:
                resume = ", ".join(f"{e['operation']} {e['cle']}" for e in en_attente[:10])
                log.info(f"[événement BDD] {len(en_attente)} modification(s) : {resume} -> ETL incrémental")
                from etl.pipeline import executer
                executer("INCREMENTAL", "evenement_bdd", resume[:500], filtre_sources=["pg_fournisseurs"])
                en_attente, premier = [], None
    except KeyboardInterrupt:
        pass
    finally:
        cx.close()


if __name__ == "__main__":
    main()
