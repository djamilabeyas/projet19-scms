"""Tâche batch ML / NLP (étape `ml_batch` de l'ETL, ou planifiée séparément : python -m ml.batch).

Les modèles sont entraînés en Python (scikit-learn, spaCy) HORS de l'outil de visualisation ; leurs résultats
(prévisions, scores, classes, clauses extraites) et leurs métriques d'évaluation sont écrits dans le schéma `ml`.

  ML 1  Prédiction du coût de fret et du délai d'une expédition (régression)      -> page Expéditions
  ML 2  Score de risque fournisseur (classification)                               -> page Fournisseurs
  ML 3  Détection d'anomalies de prix unitaires / surfacturation (Isolation Forest) -> page Coûts et fret
  NLP 1 Extraction des clauses, pénalités et échéances des contrats (spaCy + règles) -> page Fournisseurs
  NLP 2 Classification des incidents de transport par cause (TF-IDF + régression logistique) -> page Douanes et risques
"""
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest, RandomForestClassifier
from sklearn.metrics import (mean_absolute_error, mean_squared_error, r2_score, precision_score, recall_score, f1_score,
                             roc_auc_score, accuracy_score)
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_predict

import config
from etl import bdd
from etl.journal import log
from ml import nlp_contrats, nlp_incidents

VERSION = "v1"


def _lire(sql):
    return pd.read_sql(sql, bdd.moteur("dwh"))


def _ecrire(table, df, cx):
    with cx.cursor() as c:
        c.execute(f"TRUNCATE {table}")
    if len(df):
        bdd.copier_df_pg(df, table, cx)


def _metriques(cx, modele, d, jeu="test"):
    with cx.cursor() as c:
        c.executemany("INSERT INTO ml.metrique_modele(modele, metrique, valeur, jeu, version_modele) VALUES (%s,%s,%s,%s,%s)",
                      [(modele, k, float(v), jeu, VERSION) for k, v in d.items()])


# ============================================================ ML 1 · coût et délai d'expédition
def ml_cout_delai(cx, maintenant):
    df = _lire("""SELECT e.asn_dn, e.mode_transport, e.iso3, e.groupe_produit, e.circuit, e.incoterm, e.pays_origine_iso3,
                         e.poids_kg, e.valeur_usd, e.nb_lignes, e.brent_usd, e.fret_usd, e.fret_inclus_prix,
                         e.delai_livraison_j, (e.date_prevue - e.date_reference) delai_prevu_j,
                         extract(month FROM e.date_reference) mois, extract(year FROM e.date_reference) annee, r.lpi
                  FROM dwh.v_expedition e LEFT JOIN dwh.v_risque_pays r USING (pays_sk)""")
    cats = ["mode_transport", "iso3", "groupe_produit", "circuit", "incoterm", "pays_origine_iso3"]
    for c in cats:
        df[c] = df[c].fillna("NA").astype("category")
    df["log_poids"] = np.log1p(df["poids_kg"]); df["log_valeur"] = np.log1p(df["valeur_usd"])
    X_cols = cats + ["log_poids", "log_valeur", "nb_lignes", "brent_usd", "mois", "annee", "lpi"]
    res = df[["asn_dn"]].copy()
    met = {}
    # --- coût de fret (cible log), uniquement quand le fret est facturé et le poids connu
    m = (df["fret_usd"] > 0) & (~df["fret_inclus_prix"].fillna(False)) & df["poids_kg"].notna()
    d = df[m]
    Xtr, Xte, ytr, yte = train_test_split(d[X_cols], np.log1p(d["fret_usd"]), test_size=0.2, random_state=19)
    mc = HistGradientBoostingRegressor(categorical_features="from_dtype", max_iter=400, learning_rate=0.06, random_state=19)
    mc.fit(Xtr, ytr)
    p = np.expm1(mc.predict(Xte)); y = np.expm1(yte)
    met["cout"] = {"MAE_usd": mean_absolute_error(y, p), "RMSE_usd": mean_squared_error(y, p) ** 0.5,
                   "R2_log": r2_score(yte, np.log1p(p)), "MAPE_median_pct": float(np.median(np.abs(p - y) / y) * 100)}
    res["cout_fret_predit_usd"] = np.where(df["poids_kg"].notna(), np.expm1(mc.predict(df[X_cols])), np.nan)
    res["jeu"] = np.where(df.index.isin(Xte.index), "test", np.where(df.index.isin(Xtr.index), "train", "hors"))
    # --- délai de livraison (jours)
    Xd = X_cols + ["delai_prevu_j"]
    m2 = df["delai_livraison_j"].notna() & df["delai_prevu_j"].notna()
    d2 = df[m2]
    Xtr, Xte, ytr, yte = train_test_split(d2[Xd], d2["delai_livraison_j"], test_size=0.2, random_state=19)
    md = HistGradientBoostingRegressor(categorical_features="from_dtype", max_iter=300, learning_rate=0.06, random_state=19)
    md.fit(Xtr, ytr)
    p = md.predict(Xte)
    met["delai"] = {"MAE_jours": mean_absolute_error(yte, p), "RMSE_jours": mean_squared_error(yte, p) ** 0.5,
                    "R2": r2_score(yte, p)}
    res["delai_predit_j"] = np.where(m2, md.predict(df[Xd].fillna({"delai_prevu_j": 0})), np.nan)
    res["cout_fret_reel_usd"] = df["fret_usd"]; res["delai_reel_j"] = df["delai_livraison_j"]
    res["version_modele"] = VERSION; res["calcule_le"] = maintenant
    _ecrire("ml.prediction_expedition", res[["asn_dn", "cout_fret_predit_usd", "delai_predit_j", "cout_fret_reel_usd",
                                             "delai_reel_j", "jeu", "version_modele", "calcule_le"]].round(2), cx)
    _metriques(cx, "ML1_cout_fret", met["cout"]); _metriques(cx, "ML1_delai_livraison", met["delai"])
    joblib.dump({"cout": mc, "delai": md, "colonnes_cout": X_cols, "colonnes_delai": Xd,
                 "categories": {c: list(df[c].cat.categories) for c in cats}}, config.MODELES / "ml1_cout_delai.joblib")
    return met


# ============================================================ ML 2 · score de risque fournisseur
def ml_risque_fournisseur(cx, maintenant):
    """Panel fournisseur × année. Cible : le fournisseur est « à risque » l'année N+1
    (taux de conformité < 80 % : livraison en retard ou incident grave). Variables : performances de l'année N + fiche fournisseur."""
    fa = _lire("SELECT * FROM dwh.v_fournisseur_annee WHERE annee IS NOT NULL AND code_fournisseur <> 'INCONNU'")
    fo = _lire("""SELECT code_fournisseur, note_qualite, certification, categorie, categorie_risque, pays_origine_iso3
                  FROM dwh.dim_fournisseur WHERE est_courant""")
    fa = fa[fa["nb_expeditions"] >= 3].sort_values(["code_fournisseur", "annee"])
    fa["cible"] = fa.groupby("code_fournisseur")["taux_conformite"].shift(-1) < 0.80
    fa["a_suivant"] = fa.groupby("code_fournisseur")["annee"].shift(-1).notna()
    d = fa.merge(fo, on="code_fournisseur", how="left")
    d["tendance"] = d.groupby("code_fournisseur")["taux_a_temps"].diff().fillna(0)
    # historique cumulé (pondéré par le nombre d'expéditions) : plus stable que la seule année N
    g = d.groupby("code_fournisseur")
    n = d["nb_expeditions"]
    d["hist_conformite"] = (d["taux_conformite"] * n).groupby(d["code_fournisseur"]).cumsum() / n.groupby(d["code_fournisseur"]).cumsum()
    d["hist_a_temps"] = (d["taux_a_temps"] * n).groupby(d["code_fournisseur"]).cumsum() / n.groupby(d["code_fournisseur"]).cumsum()
    for c in ["certification", "categorie", "pays_origine_iso3"]:
        d[c] = d[c].fillna("NA")
    X = pd.get_dummies(d[["taux_a_temps", "ecart_moyen_j", "taux_conformite", "taux_incident", "nb_expeditions", "note_qualite",
                          "tendance", "hist_conformite", "hist_a_temps", "certification", "categorie"]], dtype=float).fillna(0)
    X["log_valeur"] = np.log1p(d["valeur_usd"])
    entr = d["a_suivant"]
    Xe, ye = X[entr], d.loc[entr, "cible"].astype(int)
    rf = RandomForestClassifier(n_estimators=400, min_samples_leaf=4, max_depth=6, class_weight="balanced", random_state=19)
    cv = StratifiedKFold(5, shuffle=True, random_state=19)
    proba_cv = cross_val_predict(rf, Xe, ye, cv=cv, method="predict_proba")[:, 1]
    pred_cv = proba_cv >= 0.5
    met = {"precision": precision_score(ye, pred_cv), "rappel": recall_score(ye, pred_cv), "F1": f1_score(ye, pred_cv),
           "AUC": roc_auc_score(ye, proba_cv), "taux_positifs_pct": ye.mean() * 100, "n_observations": len(ye)}
    rf.fit(Xe, ye)
    d["score_risque"] = rf.predict_proba(X)[:, 1]
    d.loc[entr, "score_risque"] = proba_cv  # score hors échantillon pour les années historiques
    out = pd.DataFrame({"code_fournisseur": d["code_fournisseur"], "annee": d["annee"].astype(int),
                        "score_risque": d["score_risque"].round(4), "classe_predite": d["score_risque"] >= 0.5,
                        "classe_reelle": np.where(entr, d["cible"], None), "version_modele": VERSION, "calcule_le": maintenant})
    _ecrire("ml.score_risque_fournisseur", out, cx)
    _metriques(cx, "ML2_risque_fournisseur", met, "validation_croisee_5")
    joblib.dump({"modele": rf, "colonnes": list(X.columns)}, config.MODELES / "ml2_risque_fournisseur.joblib")
    return met


# ============================================================ ML 3 · anomalies de prix unitaires
def ml_anomalies_prix(cx, maintenant):
    df = _lire("""SELECT f.id_ligne, f.produit_sk, f.fournisseur_sk, d.annee, f.prix_unitaire_usd, f.prix_pack_usd, f.quantite,
                         f.valeur_usd FROM dwh.fait_ligne_expedition f JOIN dwh.dim_date d ON d.date_sk = f.date_prevue_sk
                  WHERE f.prix_pack_usd > 0""")
    med_pa = df.groupby(["produit_sk", "annee"])["prix_pack_usd"].transform("median")
    med_p = df.groupby("produit_sk")["prix_pack_usd"].transform("median")
    df["ratio"] = np.log(df["prix_pack_usd"] / med_pa)
    df["ratio_global"] = np.log(df["prix_pack_usd"] / med_p)
    df["ratio_fourn"] = df["ratio"] - df.groupby(["fournisseur_sk", "produit_sk"])["ratio"].transform("median")
    df["log_qte"] = np.log1p(df["quantite"])
    X = df[["ratio", "ratio_global", "ratio_fourn", "log_qte"]].fillna(0)
    iso = IsolationForest(n_estimators=300, contamination=0.015, random_state=19).fit(X)
    score = -iso.score_samples(X)
    est = (iso.predict(X) == -1) & (df["ratio"] > 0)          # on ne retient que les prix anormalement ÉLEVÉS
    out = pd.DataFrame({"id_ligne": df["id_ligne"], "score_anomalie": score.round(5), "est_anomalie": est,
                        "ecart_mediane_pct": ((np.exp(df["ratio"]) - 1) * 100).round(2), "version_modele": VERSION,
                        "calcule_le": maintenant})
    _ecrire("ml.anomalie_prix", out, cx)
    met = {"nb_anomalies": int(est.sum()), "taux_anomalies_pct": est.mean() * 100}
    verite = config.VERITE / "anomalies_prix.csv"
    if verite.exists():
        vrai = df["id_ligne"].isin(pd.read_csv(verite)["ID"])
        met.update({"precision": precision_score(vrai, est), "rappel": recall_score(vrai, est), "F1": f1_score(vrai, est)})
    _metriques(cx, "ML3_anomalies_prix", met, "verite_terrain")
    joblib.dump(iso, config.MODELES / "ml3_isolation_forest.joblib")
    return met


# ============================================================ orchestration
def executer(rid=None):
    t0 = time.time()
    maintenant = pd.Timestamp.now().floor("s")
    cx = bdd.pg_connexion()
    with cx.cursor() as c:  # les modèles lisent la vue expédition : on la met à jour avant l'entraînement
        c.execute("REFRESH MATERIALIZED VIEW dwh.mv_expedition")
    cx.commit()
    resultats = {}
    try:
        for nom, f in [("ML1", ml_cout_delai), ("ML2", ml_risque_fournisseur), ("ML3", ml_anomalies_prix),
                       ("NLP1", nlp_contrats.executer), ("NLP2", nlp_incidents.executer)]:
            t = time.time()
            resultats[nom] = f(cx, maintenant) if nom.startswith("ML") else f(cx, maintenant, _ecrire, _metriques, VERSION)
            cx.commit()
            log.info(f"   {nom} terminé en {time.time() - t:.1f} s : " + ", ".join(
                f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in _aplatir(resultats[nom]).items()))
    finally:
        cx.close()
    return {}, f"5 modèles recalculés en {time.time() - t0:.0f} s"


def _aplatir(d, p=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_aplatir(v, f"{k}."))
        else:
            out[p + k] = v
    return out


if __name__ == "__main__":
    print(executer())
