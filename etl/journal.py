"""Journalisation des exécutions, des étapes, des rejets + filigranes, verrou et relance sur erreur."""
import functools
import json
import logging
import time

import config
from etl import bdd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(config.LOGS / "etl.log", encoding="utf-8")])
log = logging.getLogger("etl")

VERROU_ETL = 190019  # pg_advisory_lock : empêche deux exécutions simultanées


def ouvrir_execution(cx, mode, declencheur, detail=None, reprise_de=None):
    with cx.cursor() as c:
        c.execute("""INSERT INTO etl.journal_execution(mode, declencheur, detail_declencheur, reprise_de)
                     VALUES (%s,%s,%s,%s) RETURNING id_execution""", (mode, declencheur, detail, reprise_de))
        rid = c.fetchone()[0]
    cx.commit()
    return rid


def fermer_execution(cx, rid, statut, message=None):
    with cx.cursor() as c:
        c.execute("""UPDATE etl.journal_execution e SET fin = now(), statut = %s, message = %s,
                       lignes_lues = s.l, lignes_inserees = s.i, lignes_maj = s.u, lignes_supprimees = s.d, lignes_rejetees = s.r
                     FROM (SELECT COALESCE(sum(lignes_lues),0) l, COALESCE(sum(lignes_inserees),0) i, COALESCE(sum(lignes_maj),0) u,
                                  COALESCE(sum(lignes_supprimees),0) d, COALESCE(sum(lignes_rejetees),0) r
                           FROM etl.journal_etape WHERE id_execution = %s AND statut = 'SUCCES') s
                     WHERE e.id_execution = %s""", (statut, message, rid, rid))
    cx.commit()


def debut_etape(cx, rid, etape):
    with cx.cursor() as c:
        c.execute("INSERT INTO etl.journal_etape(id_execution, etape, statut) VALUES (%s,%s,'EN_COURS') RETURNING id_etape",
                  (rid, etape))
        eid = c.fetchone()[0]
    cx.commit()
    return eid


def fin_etape(cx, eid, statut, compteurs=None, message=None):
    k = compteurs or {}
    with cx.cursor() as c:
        c.execute("""UPDATE etl.journal_etape SET fin = now(), statut = %s, lignes_lues = %s, lignes_inserees = %s,
                     lignes_maj = %s, lignes_supprimees = %s, lignes_rejetees = %s, message = %s WHERE id_etape = %s""",
                  (statut, k.get("lues", 0), k.get("I", 0), k.get("U", 0), k.get("D", 0), k.get("rejets", 0), message, eid))
    cx.commit()


def etapes_reussies(cx, rid):
    with cx.cursor() as c:
        c.execute("SELECT etape FROM etl.journal_etape WHERE id_execution = %s AND statut = 'SUCCES'", (rid,))
        return {r[0] for r in c.fetchall()}


def derniere_execution_echouee(cx):
    with cx.cursor() as c:
        c.execute("SELECT id_execution, mode FROM etl.journal_execution WHERE statut = 'ECHEC' ORDER BY id_execution DESC LIMIT 1")
        return c.fetchone()


def ecrire_rejets(cx, rid, source, rejets):
    """rejets : liste de dict {cle, regle, motif, donnees}"""
    if not rejets:
        return
    with cx.cursor() as c:
        c.executemany("INSERT INTO etl.rejet(id_execution, source, cle, regle, motif, donnees) VALUES (%s,%s,%s,%s,%s,%s)",
                      [(rid, source, str(r["cle"]), r["regle"], r["motif"], json.dumps(r["donnees"], default=str, ensure_ascii=False))
                       for r in rejets])


def lire_filigrane(cx, source, defaut=None):
    with cx.cursor() as c:
        c.execute("SELECT valeur FROM etl.filigrane WHERE source = %s", (source,))
        r = c.fetchone()
    return r[0] if r else defaut


def ecrire_filigrane(cx, source, valeur):
    if valeur is None:
        return
    with cx.cursor() as c:
        c.execute("""INSERT INTO etl.filigrane(source, valeur, maj_le) VALUES (%s,%s,now())
                     ON CONFLICT (source) DO UPDATE SET valeur = EXCLUDED.valeur, maj_le = now()""", (source, str(valeur)))


def avec_relance(essais=3, attente=2.0, exceptions=(Exception,)):
    """Décorateur : relance une fonction (appel d'API, connexion) avec attente exponentielle."""
    def deco(f):
        @functools.wraps(f)
        def wrap(*a, **kw):
            for n in range(1, essais + 1):
                try:
                    return f(*a, **kw)
                except exceptions as e:
                    if n == essais:
                        raise
                    log.warning(f"{f.__name__} : tentative {n}/{essais} échouée ({e}), nouvelle tentative dans {attente * n:.0f} s")
                    time.sleep(attente * n)
        return wrap
    return deco
