"""Chargement incrémental : comparaison de hachages (I = nouvelle, U = modifiée, D = supprimée)."""
import pandas as pd

from etl import bdd


def hacher(df: pd.DataFrame, colonnes) -> pd.Series:
    return pd.util.hash_pandas_object(df[colonnes].astype(str), index=False).astype("int64")


def calculer(cx, source, df, ext, colonnes_hash):
    """Ajoute df['_op'] ∈ {I, U, =} et renvoie (df, cles_supprimees)."""
    df = df.copy()
    df["_hash"] = hacher(df, colonnes_hash)
    if "_fichier" not in df.columns:
        df["_fichier"] = None
    with cx.cursor() as c:
        c.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_cles (cle TEXT) ON COMMIT DROP")
        c.execute("TRUNCATE tmp_cles")
    cles = df[["cle"]]
    if ext.perimetre == "delta" and ext.suppressions:   # clés signalées supprimées par le CDC
        cles = pd.concat([cles, pd.DataFrame({"cle": [str(k) for k in ext.suppressions]})])
    bdd.copier_df_pg(cles, "tmp_cles", cx)
    fichiers = ext.fichiers_lus if ext.perimetre == "fichiers" else []
    with cx.cursor() as c:
        if ext.perimetre == "complet":
            c.execute("SELECT cle, hachage FROM etl.empreinte WHERE source = %s", (source,))
            connus = pd.DataFrame(c.fetchall(), columns=["cle", "hachage"])
            portee = set(connus["cle"])
        else:
            c.execute("""SELECT e.cle, e.hachage, e.fichier FROM etl.empreinte e
                         WHERE e.source = %s AND (e.cle IN (SELECT cle FROM tmp_cles) OR e.fichier = ANY(%s))""",
                      (source, fichiers))
            connus = pd.DataFrame(c.fetchall(), columns=["cle", "hachage", "fichier"])
            portee = set(connus.loc[connus["fichier"].isin(fichiers), "cle"]) if fichiers else set()
    h = dict(zip(connus["cle"], connus["hachage"]))
    anc = df["cle"].map(h)
    df["_op"] = "="
    df.loc[anc.isna(), "_op"] = "I"
    df.loc[anc.notna() & (anc != df["_hash"]), "_op"] = "U"
    presentes = set(df["cle"])
    if ext.perimetre == "delta":
        supprimees = sorted({str(k) for k in ext.suppressions if str(k) in h and str(k) not in presentes})
    else:
        supprimees = sorted(portee - presentes)
    return df, supprimees


def maj_empreintes(cx, source, df, supprimees):
    a_ecrire = df[df["_op"].isin(["I", "U"])][["cle", "_hash", "_fichier"]].copy()
    if len(a_ecrire):
        with cx.cursor() as c:
            c.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_emp (cle TEXT, hachage BIGINT, fichier TEXT) ON COMMIT DROP")
            c.execute("TRUNCATE tmp_emp")
        a_ecrire.columns = ["cle", "hachage", "fichier"]
        bdd.copier_df_pg(a_ecrire, "tmp_emp", cx)
        with cx.cursor() as c:
            c.execute("""INSERT INTO etl.empreinte(source, cle, hachage, fichier)
                         SELECT %s, cle, hachage, fichier FROM tmp_emp
                         ON CONFLICT (source, cle) DO UPDATE SET hachage = EXCLUDED.hachage, fichier = EXCLUDED.fichier""",
                      (source,))
    # les fichiers relus mais inchangés ligne à ligne changent quand même de propriétaire de clé
    if supprimees:
        with cx.cursor() as c:
            c.execute("DELETE FROM etl.empreinte WHERE source = %s AND cle = ANY(%s)", (source, list(supprimees)))
