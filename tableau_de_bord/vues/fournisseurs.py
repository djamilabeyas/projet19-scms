"""Page 3 · Fournisseurs — indicateurs 11 à 15 + ML 2 (score de risque) + NLP 1 (clauses des contrats)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from commun import entete, exp_filtrees, kpi, nb, usd, pct, q, barres_h, bloc_ml, metriques, annees_completes, BLEU, STATUT, GRIS

entete("Fournisseurs", "Performance, conformité, parts de marché, risque et clauses contractuelles")
e = exp_filtrees()
if e.empty:
    st.warning("Aucune expédition pour ces filtres."); st.stop()

e = e.assign(conforme=e["a_temps"] & (e["nb_incidents_graves"] == 0))
f = e.groupby(["code_fournisseur", "fournisseur"]).agg(
    n=("asn_dn", "count"), valeur=("valeur_usd", "sum"), a_temps=("a_temps", "mean"), conformite=("conforme", "mean"),
    ecart=("ecart_contractuel_j", "mean"), reponse=("delai_reponse_j", "mean")).reset_index()
f["part"] = f["valeur"] / f["valeur"].sum()
f["court"] = f["fournisseur"].str.replace(r"\s*\(.*\)", "", regex=True).str.slice(0, 32)
directs = f[f["code_fournisseur"] != "F0001"]          # hors centres régionaux SCMS (stock interne)

annee_max = int(q("SELECT max(annee) a FROM ml.score_risque_fournisseur")["a"].iloc[0])
sc = q(f"""SELECT DISTINCT ON (s.code_fournisseur) s.code_fournisseur, s.annee, s.score_risque, s.classe_predite,
                  d.nom, d.note_qualite, d.categorie_risque, d.certification
           FROM ml.score_risque_fournisseur s JOIN dwh.dim_fournisseur d ON d.code_fournisseur = s.code_fournisseur AND d.est_courant
           ORDER BY s.code_fournisseur, s.annee DESC""")

c = st.columns(5)
kpi(c[0], 11, "Performance moyenne", pct(directs["a_temps"].mean()), "Moyenne des taux de livraison à temps par fournisseur")
kpi(c[1], 12, "Conformité", pct(e["conforme"].mean()), "Expéditions à temps ET sans incident majeur ou critique")
top = directs.sort_values("part", ascending=False).iloc[0] if len(directs) else None
kpi(c[2], 13, "Part du n°1", pct(top["valeur"] / f["valeur"].sum()) if top is not None else "–",
    f"{top['fournisseur']} (en valeur, hors stock des centres régionaux)" if top is not None else None)
kpi(c[3], 14, "Délai de réponse", f"{nb(e['delai_reponse_j'].mean(), 1)} j",
    "Délai entre la 1re demande de cotation et l'envoi du bon de commande au fournisseur")
kpi(c[4], 15, "À risque (ML)", nb(int(sc["classe_predite"].sum())),
    "Score de risque ML 2 ≥ 0,5 (dernière année connue de chaque fournisseur)")

g1, g2 = st.columns(2)
perf = directs[directs["n"] >= 10].copy()
perf["coul"] = perf["a_temps"].map(lambda v: STATUT["bon"] if v >= .9 else STATUT["alerte"] if v >= .8 else STATUT["critique"])
fig = barres_h(perf, "a_temps", "court", "11 · Taux de livraison à temps par fournisseur (≥ 10 expéditions)",
               fmt=lambda v: pct(v, 0), couleurs=list(perf.sort_values("a_temps")["coul"]))
g1.plotly_chart(fig, use_container_width=True)
g1.caption("🟢 ≥ 90 %  ·  🟠 80-90 %  ·  🔴 < 80 %")
pm = f.sort_values("part", ascending=False).head(10)
autres = pd.DataFrame([{"court": "Autres", "part": 1 - pm["part"].sum()}])
pm = pd.concat([pm[["court", "part"]], autres])
g2.plotly_chart(barres_h(pm, "part", "court", "13 · Part de marché des fournisseurs (en valeur)", fmt=lambda v: pct(v, 1)),
                use_container_width=True)

g3, g4 = st.columns(2)
cf = directs[directs["n"] >= 10]
fig = go.Figure(go.Scatter(x=cf["reponse"], y=cf["conformite"] * 100, mode="markers", text=cf["court"],
                           marker=dict(size=(cf["n"] ** .5) * 2 + 6, color=BLEU, opacity=.7, line=dict(color="white", width=2)),
                           hovertemplate="<b>%{text}</b><br>délai de réponse %{x:.0f} j<br>conformité %{y:.1f} %<extra></extra>"))
fig.update_layout(title="12 & 14 · Conformité vs délai de réponse (taille = nb d'expéditions)", height=380,
                  xaxis_title="délai de réponse (j)", yaxis_title="taux de conformité (%)")
g3.plotly_chart(fig, use_container_width=True)
ev = q("SELECT * FROM dwh.v_fournisseur_annee WHERE code_fournisseur <> 'INCONNU'")
ev = ev[ev["annee"].between(*st.session_state["filtres"]["annees"])]
ev = ev[ev["annee"].isin(annees_completes(e))]
glob = ev.groupby("annee").apply(lambda d: (d["taux_conformite"] * d["nb_expeditions"]).sum() / d["nb_expeditions"].sum(),
                                 include_groups=False).reset_index(name="t")
fig = go.Figure(go.Scatter(x=glob["annee"], y=glob["t"] * 100, mode="lines+markers", line=dict(color=BLEU, width=2), marker=dict(size=8),
                           hovertemplate="%{x} : %{y:.1f} %<extra></extra>"))
fig.update_layout(title="12 · Taux de conformité par année (%)", height=380)
g4.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------ ML 2
st.markdown("### Score de risque fournisseur (ML 2)")
m2, jeu, _ = metriques("ML2_risque_fournisseur")
bloc_ml("Classification Random Forest : le fournisseur sera-t-il « à risque » l'année suivante ?",
        "Cible : taux de conformité de l'année N+1 < 80 %. Variables : performances de l'année N, historique cumulé, note "
        "qualité, certification, catégorie. Scores historiques hors échantillon (validation croisée).",
        m2, jeu, [("AUC", "AUC", lambda v: nb(v, 3)), ("precision", "Précision", lambda v: nb(v, 3)),
                  ("rappel", "Rappel", lambda v: nb(v, 3)), ("F1", "F1", lambda v: nb(v, 3)),
                  ("n_observations", "Observations", lambda v: nb(v))])
t = sc.sort_values("score_risque", ascending=False)
st.dataframe(t.assign(niveau=t["score_risque"].map(lambda s: "🔴 élevé" if s >= .5 else "🟠 modéré" if s >= .3 else "🟢 faible"))[
    ["nom", "annee", "score_risque", "niveau", "note_qualite", "categorie_risque", "certification"]],
    hide_index=True, use_container_width=True, height=300,
    column_config={"nom": "Fournisseur", "annee": st.column_config.NumberColumn("Année", format="%d"),
                   "score_risque": st.column_config.ProgressColumn("Score de risque", min_value=0, max_value=1, format="%.2f"),
                   "niveau": "Niveau", "note_qualite": "Note qualité (source)", "categorie_risque": "Risque (source)",
                   "certification": "Certification"})

# ------------------------------------------------------------------ NLP 1
st.markdown("### Clauses, pénalités et échéances des contrats (NLP 1)")
m1, jeu, _ = metriques("NLP1_clauses_contrats")
bloc_ml("Extraction d'information dans le texte des contrats (spaCy + règles)",
        "Pénalités de retard (taux, unité, plafond), délais de livraison et de paiement, dates d'effet et d'échéance, "
        "Incoterm, clause de force majeure. Robuste aux variantes de rédaction (chiffres en lettres, dates en toutes lettres).",
        m1, jeu, [("precision", "Précision", lambda v: nb(v, 3)), ("rappel", "Rappel", lambda v: nb(v, 3)),
                  ("F1", "F1", lambda v: nb(v, 3)), ("exactitude_penalite_pct", "Exactitude taux pénalité", lambda v: pct(v, 0)),
                  ("nb_contrats", "Contrats analysés", lambda v: nb(v))])
cl = q("""SELECT c.id_contrat, k.nom_fournisseur, c.penalite_pct, c.unite_penalite, c.plafond_pct, c.delai_livraison_j,
                 c.delai_paiement_j, c.date_debut, c.date_echeance, c.incoterm, c.force_majeure, c.extrait_penalite, k.statut
          FROM ml.clause_contrat c JOIN dwh.dim_contrat k USING (id_contrat) ORDER BY c.date_echeance DESC""")
if st.session_state["filtres"]["annees"]:
    a0, a1 = st.session_state["filtres"]["annees"]
    cl = cl[pd.to_datetime(cl["date_echeance"]).dt.year.between(a0, a1 + 3) | cl["date_echeance"].isna()]
n1, n2, n3 = st.columns(3)
n1.metric("Pénalité moyenne extraite", f"{nb(cl['penalite_pct'].mean(), 2)} % / période")
n2.metric("Contrats actifs", nb((cl["statut"] == "actif").sum()))
n3.metric("Contrats sans pénalité détectée", nb(cl["penalite_pct"].isna().sum()), help="À vérifier manuellement (texte mal numérisé)")
st.dataframe(cl.drop(columns=["statut"]), hide_index=True, use_container_width=True, height=320,
             column_config={"id_contrat": "Contrat", "nom_fournisseur": "Fournisseur",
                            "penalite_pct": st.column_config.NumberColumn("Pénalité %", format="%.2f"),
                            "unite_penalite": "par", "plafond_pct": st.column_config.NumberColumn("Plafond %", format="%.0f"),
                            "delai_livraison_j": "Délai livr. (j)", "delai_paiement_j": "Paiement (j)",
                            "date_debut": "Début", "date_echeance": "Échéance", "incoterm": "Incoterm",
                            "force_majeure": "Force majeure", "extrait_penalite": st.column_config.TextColumn("Extrait (clause)", width="large")})
