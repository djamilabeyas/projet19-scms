"""Chargement dans l'entrepôt : upsert (INSERT … ON CONFLICT), suppression, recherche des clés de substitution."""
import numpy as np
import pandas as pd

from etl import bdd


def date_sk(serie) -> pd.Series:
    d = pd.to_datetime(serie, errors="coerce")
    return (d.dt.year * 10000 + d.dt.month * 100 + d.dt.day).fillna(-1).astype(int)


def upsert(cx, table, df, cle, colonnes):
    """Insère ou met à jour df[colonnes] dans table selon la clé (str ou liste)."""
    if df.empty:
        return
    cles = [cle] if isinstance(cle, str) else list(cle)
    tmp = "tmp_" + table.split(".")[-1]
    with cx.cursor() as c:
        c.execute(f"CREATE TEMP TABLE IF NOT EXISTS {tmp} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
        c.execute(f"TRUNCATE {tmp}")
    d = df[colonnes].copy()
    for col in d.columns:
        if d[col].dtype == object:
            d[col] = d[col].where(d[col].notna(), None)
    bdd.copier_df_pg(d, tmp, cx, colonnes)
    cols = ", ".join(colonnes)
    maj = ", ".join(f"{c} = EXCLUDED.{c}" for c in colonnes if c not in cles)
    with cx.cursor() as c:
        c.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {tmp} "
                  f"ON CONFLICT ({', '.join(cles)}) DO " + (f"UPDATE SET {maj}" if maj else "NOTHING"))


def supprimer(cx, table, cle, valeurs, type_cle="text"):
    if not valeurs:
        return
    with cx.cursor() as c:
        c.execute(f"DELETE FROM {table} WHERE {cle}::text = ANY(%s)", (list(map(str, valeurs)),))


def carte(cx, sql) -> dict:
    with cx.cursor() as c:
        c.execute(sql)
        return {k: v for k, v in c.fetchall()}


def cartes(cx):
    return {
        "pays_nom": carte(cx, "SELECT nom_source, pays_sk FROM dwh.dim_pays WHERE nom_source IS NOT NULL"),
        "pays_iso": carte(cx, "SELECT iso3, pays_sk FROM dwh.dim_pays"),
        "mode": carte(cx, "SELECT code_source, mode_sk FROM dwh.dim_mode_transport"),
        "fournisseur": carte(cx, """SELECT DISTINCT ON (nom) nom, fournisseur_sk FROM dwh.dim_fournisseur
                                    ORDER BY nom, est_courant DESC, version DESC"""),
        "fournisseur_code": carte(cx, "SELECT DISTINCT ON (nom) nom, code_fournisseur FROM dwh.dim_fournisseur ORDER BY nom, version DESC"),
        "produit": carte(cx, "SELECT cle_produit, produit_sk FROM dwh.dim_produit"),
        "entrepot": carte(cx, "SELECT code_entrepot, entrepot_sk FROM dwh.dim_entrepot"),
        "bureau": carte(cx, "SELECT libelle, bureau_sk FROM dwh.dim_bureau_douane"),
        "cause": carte(cx, "SELECT libelle, cause_sk FROM dwh.dim_cause_incident"),
        "indicateur": carte(cx, "SELECT code, indicateur_sk FROM dwh.dim_indicateur"),
    }


def mapper(serie, dico, defaut=-1):
    return serie.map(dico).fillna(defaut).astype(int)


def nn(x):
    """NaN -> None pour l'insertion."""
    return None if (x is None or (isinstance(x, float) and np.isnan(x))) else x
