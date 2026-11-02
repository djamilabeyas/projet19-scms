"""NLP 1 · Extraction des clauses, pénalités et échéances des contrats fournisseurs (texte libre en français).

Approche : spaCy (modèle fr_core_news_sm, ou tokeniseur français vierge s'il n'est pas installé) pour découper le texte
en phrases et repérer les phrases-clés par lemmes (Matcher), puis expressions régulières pour lire les valeurs
(pourcentages, nombres de jours écrits en chiffres ou en lettres, dates au format JJ/MM/AAAA ou « 31 décembre 2012 »).
Évaluation : comparaison champ par champ avec la vérité terrain (précision, rappel, exactitude).
"""
import re

import pandas as pd
import spacy
from spacy.matcher import Matcher

import config
from etl import bdd

MOIS = {m: i + 1 for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                                        "septembre", "octobre", "novembre", "décembre"])}
NOMBRES = {"sept": 7, "dix": 10, "quatorze": 14, "quinze": 15, "vingt": 20, "trente": 30, "quarante-cinq": 45,
           "soixante": 60, "quatre-vingt-dix": 90, "cent vingt": 120}
RE_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|pour\s*cent)")
RE_JOURS = re.compile(r"(?:\((\d+)\)|(\d+))\s*jours")
RE_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})|(\d{1,2})\s+(" + "|".join(MOIS) + r")\s+(\d{4})", re.I)
RE_INCOTERM = re.compile(r"Incoterm\s+([A-Z]{3})")

_nlp = None


def modele():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("fr_core_news_sm", disable=["ner"])
        except OSError:
            _nlp = spacy.blank("fr"); _nlp.add_pipe("sentencizer")
    return _nlp


def _matcher(nlp):
    m = Matcher(nlp.vocab)
    m.add("PENALITE", [[{"LOWER": {"IN": ["pénalité", "pénalités"]}}]])
    m.add("LIVRAISON", [[{"LOWER": "délai"}, {"LOWER": "de"}, {"LOWER": "livraison"}]])
    m.add("PAIEMENT", [[{"LOWER": "factures"}], [{"LOWER": "paiement"}]])
    m.add("DUREE", [[{"LOWER": {"IN": ["effet", "expire", "échéance", "vigueur"]}}]])
    m.add("FORCE_MAJEURE", [[{"LOWER": "force"}, {"LOWER": "majeure"}]])
    return m


def _pct(txt):
    return [float(x.replace(",", ".")) for x in RE_PCT.findall(txt)]


def _jours(txt):
    for a, b in RE_JOURS.findall(txt):
        return int(a or b)
    for mot, n in sorted(NOMBRES.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{mot}\b\s+jours", txt):
            return n
    return None


def _dates(txt):
    out = []
    for m in RE_DATE.finditer(txt):
        if m.group(1):
            out.append(pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        else:
            out.append(pd.Timestamp(int(m.group(6)), MOIS[m.group(5).lower()], int(m.group(4))))
    return out


def extraire(texte, nlp=None, matcher=None):
    nlp = nlp or modele(); matcher = matcher or _matcher(nlp)
    r = {"penalite_pct": None, "unite_penalite": None, "plafond_pct": None, "delai_livraison_j": None, "delai_paiement_j": None,
         "date_debut": None, "date_echeance": None, "incoterm": None, "force_majeure": False, "extrait_penalite": None}
    m = RE_INCOTERM.search(texte)
    r["incoterm"] = m.group(1) if m else None
    # unité d'analyse = l'article (un paragraphe) : une clause peut contenir plusieurs phrases (« … appliquées ; leur montant … »)
    for paragraphe in nlp.pipe([l for l in texte.splitlines() if l.strip()]):
        labels = {nlp.vocab.strings[mid] for mid, s, e in matcher(paragraphe)}
        t = paragraphe.text
        if "PENALITE" in labels and r["penalite_pct"] is None:
            p = _pct(t)
            if p:
                r["penalite_pct"] = p[0]
                r["plafond_pct"] = p[1] if len(p) > 1 else None
                r["unite_penalite"] = "semaine" if re.search(r"par\s+semaine", t) else "jour" if re.search(r"par\s+jour", t) else None
                r["extrait_penalite"] = t.strip()[:300]
        if "LIVRAISON" in labels and r["delai_livraison_j"] is None:
            r["delai_livraison_j"] = _jours(t)
        if "PAIEMENT" in labels and "réglées" in t and r["delai_paiement_j"] is None:
            r["delai_paiement_j"] = _jours(t)
        if "DUREE" in labels and r["date_debut"] is None:
            ds = _dates(t)
            if len(ds) >= 2:
                r["date_debut"], r["date_echeance"] = ds[0].date(), ds[1].date()
        if "FORCE_MAJEURE" in labels:
            r["force_majeure"] = True
    return r


def executer(cx, maintenant, ecrire, metriques, version):
    df = pd.read_sql("SELECT id_contrat, texte FROM dwh.dim_contrat", bdd.moteur("dwh"))
    nlp = modele(); mt = _matcher(nlp)
    res = pd.DataFrame([{"id_contrat": i, **extraire(t, nlp, mt)} for i, t in zip(df["id_contrat"], df["texte"])])
    res["version_modele"] = version; res["calcule_le"] = maintenant
    ecrire("ml.clause_contrat", res, cx)
    met = {"nb_contrats": len(res)}
    f = config.VERITE / "contrats_clauses.csv"
    if f.exists():
        v = pd.read_csv(f).set_index("id_contrat").loc[res["id_contrat"]].reset_index()
        champs = {"penalite_pct": "penalite_pct", "unite_penalite": "unite_penalite", "plafond_pct": "plafond_pct",
                  "delai_livraison_j": "delai_livraison_j", "delai_paiement_j": "delai_paiement_j", "date_echeance": "date_fin",
                  "incoterm": "incoterm", "force_majeure": "force_majeure"}
        tp = fp = fn = 0
        def norm(x):
            try:
                return f"{float(x):g}"
            except (TypeError, ValueError):
                return str(x)
        for c, cv in champs.items():
            pred, vrai = res[c].map(norm), v[cv].map(norm)
            extrait = res[c].notna() & (res[c].astype(str) != "None")
            ok = extrait & (pred.values == vrai.values)
            if c == "force_majeure":
                ok = pred.values == vrai.values; extrait = pd.Series(True, index=res.index)
            met[f"exactitude_{c}"] = float(ok.mean())
            tp += int(ok.sum()); fp += int((extrait & ~ok).sum()); fn += int((~extrait).sum())
        met["precision"] = tp / max(tp + fp, 1)
        met["rappel"] = tp / max(tp + fn, 1)
        met["F1"] = 2 * met["precision"] * met["rappel"] / max(met["precision"] + met["rappel"], 1e-9)
    metriques(cx, "NLP1_clauses_contrats", met, "verite_terrain")
    return met
