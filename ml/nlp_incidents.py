"""NLP 2 · Classification des incidents de transport par cause à partir de leur description (texte libre FR/EN).

35 % des incidents arrivent sans cause déclarée. On entraîne un classifieur sur les incidents déclarés
(TF-IDF mots 1-2 grammes + caractères 3-5 grammes, régression logistique), on l'évalue sur un jeu de test
stratifié, puis on prédit la cause des incidents non déclarés. La « cause retenue » = cause déclarée, sinon prédite.
"""
import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline, make_union

import config
from etl import bdd


def construire():
    vect = make_union(TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents="unicode"),
                      TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True))
    return make_pipeline(vect, LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced"))


def executer(cx, maintenant, ecrire, metriques, version):
    df = pd.read_sql("""SELECT i.id_incident, i.description, c.libelle cause_declaree FROM dwh.fait_incident i
                        LEFT JOIN dwh.dim_cause_incident c ON c.cause_sk = i.cause_declaree_sk AND c.cause_sk > 0""",
                     bdd.moteur("dwh"))
    lab = df[df["cause_declaree"].notna()]
    Xtr, Xte, ytr, yte = train_test_split(lab["description"], lab["cause_declaree"], test_size=0.2, random_state=19,
                                          stratify=lab["cause_declaree"])
    m = construire().fit(Xtr, ytr)
    p = m.predict(Xte)
    pr, rc, f1, _ = precision_recall_fscore_support(yte, p, average="macro", zero_division=0)
    met = {"exactitude": accuracy_score(yte, p), "precision_macro": pr, "rappel_macro": rc, "F1_macro": f1,
           "n_entrainement": len(Xtr), "n_test": len(Xte)}
    m = construire().fit(lab["description"], lab["cause_declaree"])  # modèle final sur toutes les données étiquetées
    proba = m.predict_proba(df["description"])
    classes = m.classes_
    df["cause_predite"] = classes[proba.argmax(1)]
    df["probabilite"] = proba.max(1).round(4)
    df["cause_retenue"] = df["cause_declaree"].fillna(df["cause_predite"])
    df["origine_cause"] = np.where(df["cause_declaree"].notna(), "déclarée", "prédite")
    f = config.VERITE / "incidents_causes.csv"
    if f.exists():  # évaluation sur les incidents NON déclarés (jamais vus à l'entraînement)
        v = df.merge(pd.read_csv(f), on="id_incident")
        nd = v[v["cause_declaree"].isna()]
        met["exactitude_non_declares"] = accuracy_score(nd["cause_reelle"], nd["cause_predite"])
    df["version_modele"] = version; df["calcule_le"] = maintenant
    ecrire("ml.classification_incident", df[["id_incident", "cause_predite", "probabilite", "cause_declaree", "cause_retenue",
                                              "origine_cause", "version_modele", "calcule_le"]], cx)
    metriques(cx, "NLP2_classification_incidents", met, "test_stratifie_20pct")
    rapport = classification_report(yte, p, zero_division=0, output_dict=True)
    with cx.cursor() as c:
        c.executemany("INSERT INTO ml.metrique_modele(modele, metrique, valeur, jeu, version_modele) VALUES (%s,%s,%s,%s,%s)",
                      [("NLP2_classification_incidents", f"F1_{k}", float(v["f1-score"]), "test_stratifie_20pct", version)
                       for k, v in rapport.items() if isinstance(v, dict) and k not in ("macro avg", "weighted avg")])
    joblib.dump(m, config.MODELES / "nlp2_incidents.joblib")
    return met
