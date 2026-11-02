"""Connexions aux bases (PostgreSQL source + entrepôt, MySQL source) et utilitaires SQL."""
import io
import psycopg2
import pymysql
from sqlalchemy import create_engine

import config

_moteurs = {}


def moteur(nom: str):
    """nom ∈ {'dwh', 'src_pg', 'src_mysql'} -> moteur SQLAlchemy mis en cache."""
    if nom not in _moteurs:
        if nom == "dwh":
            url = config.url_pg(config.PG_DB_DWH)
        elif nom == "src_pg":
            url = config.url_pg(config.PG_DB_SOURCE)
        elif nom == "src_mysql":
            url = config.url_mysql()
        else:
            raise ValueError(nom)
        _moteurs[nom] = create_engine(url, pool_pre_ping=True)
    return _moteurs[nom]


def pg_connexion(db: str = None, autocommit=False):
    cx = psycopg2.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                          password=config.PG_PASSWORD, dbname=db or config.PG_DB_DWH)
    cx.autocommit = autocommit
    return cx


def mysql_connexion(db: str | None = config.MYSQL_DB):
    return pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                           password=config.MYSQL_PASSWORD, database=db, charset="utf8mb4", autocommit=True,
                           local_infile=True)


def creer_bases():
    cx = pg_connexion("postgres", autocommit=True)
    with cx.cursor() as c:
        for db in (config.PG_DB_SOURCE, config.PG_DB_DWH):
            c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db,))
            if not c.fetchone():
                c.execute(f'CREATE DATABASE "{db}" ENCODING \'UTF8\'')
    cx.close()
    m = mysql_connexion(None)
    with m.cursor() as c:
        try:
            c.execute(f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL_DB}` CHARACTER SET utf8mb4")
        except pymysql.err.OperationalError:
            pass  # base déjà créée par l'administrateur (ex. docker-compose) et droits limités à cette base
    m.close()


def executer_fichier_pg(chemin, db=None):
    cx = pg_connexion(db, autocommit=True)
    with cx.cursor() as c:
        c.execute(open(chemin, encoding="utf-8").read())
    cx.close()


def executer_fichier_mysql(chemin):
    m = mysql_connexion()
    with m.cursor() as c:
        for instr in open(chemin, encoding="utf-8").read().split(";\n"):
            lignes = [l for l in instr.splitlines() if not l.strip().startswith("--")]
            s = "\n".join(lignes).strip()
            if s:
                c.execute(s)
    m.close()


def copier_df_pg(df, table, cx, colonnes=None):
    """Insertion massive d'un DataFrame via COPY (beaucoup plus rapide qu'INSERT)."""
    colonnes = colonnes or list(df.columns)
    d = df[colonnes].copy()
    for col in d.columns:  # flottants entiers (3.0) -> entiers, sinon COPY refuse les colonnes INTEGER
        if d[col].dtype.kind == "f":
            v = d[col].dropna()
            if len(v) and (v % 1 == 0).all() and v.abs().max() < 9e15:
                d[col] = d[col].astype("Int64")
    buf = io.StringIO()
    d.to_csv(buf, index=False, header=False, sep="\t", na_rep="\\N")
    buf.seek(0)
    with cx.cursor() as c:
        cols = ",".join(f'"{x}"' for x in colonnes)
        c.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')", buf)
