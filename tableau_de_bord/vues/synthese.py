"""Page 1 · Synthèse — indicateurs 1 à 5 + état des modèles."""
import plotly.graph_objects as go
import streamlit as st

from commun import entete, exp_filtrees, kpi, nb, usd, pct, q, annees_completes, BLEU, STATUT

entete("Synthèse", "Vue d'ensemble des expéditions du programme d'approvisionnement")
e = exp_filtrees()
if e.empty:
    st.warning("Aucune expédition pour ces filtres."); st.stop()

c = st.columns(5)
kpi(c[0], 1, "Expéditions", nb(len(e)), "Nombre d'expéditions distinctes (ASN/DN)")
kpi(c[1], 2, "Coût total", usd(e["cout_total_usd"].sum()), "Fret + assurance + frais de douane")
kpi(c[2], 3, "Délai moyen", f"{nb(e['delai_livraison_j'].mean(), 1)} j",
    "Date de livraison − date d'envoi du bon de commande (à défaut, 1re demande de cotation)")
kpi(c[3], 4, "Livrées à temps", pct(e["a_temps"].mean()), "Livrée au plus tard à la date prévue")
kpi(c[4], 5, "Valeur transportée", usd(e["valeur_usd"].sum()), "Somme de la valeur des lignes de commande")

g1, g2 = st.columns([3, 2])
m = e.groupby("annee_mois").agg(n=("asn_dn", "count"), a_temps=("a_temps", "mean")).reset_index()
fig = go.Figure(go.Bar(x=m["annee_mois"], y=m["n"], marker=dict(color=BLEU, cornerradius=2),
                       hovertemplate="%{x} : %{y} expéditions<extra></extra>"))
fig.update_layout(title="Expéditions livrées par mois", height=320, bargap=0.15)
g1.plotly_chart(fig, use_container_width=True)

a = e.groupby("annee").agg(t=("a_temps", "mean")).reset_index()
a = a[a["annee"].isin(annees_completes(e))]
fig = go.Figure(go.Scatter(x=a["annee"], y=a["t"] * 100, mode="lines+markers", line=dict(color=BLEU, width=2),
                           marker=dict(size=8), hovertemplate="%{x} : %{y:.1f} %<extra></extra>"))
fig.add_hline(y=90, line=dict(color=STATUT["alerte"], dash="dot", width=1), annotation_text="objectif 90 %",
              annotation_position="bottom right")
fig.update_layout(title="Taux de livraison à temps par année (%)", height=320, yaxis=dict(range=[70, 100]))
g2.plotly_chart(fig, use_container_width=True)

p = e.groupby(["pays", "latitude", "longitude"]).agg(n=("asn_dn", "count"), v=("valeur_usd", "sum"),
                                                     t=("a_temps", "mean")).reset_index()
fig = go.Figure(go.Scattergeo(lat=p["latitude"], lon=p["longitude"], text=p["pays"], mode="markers",
                              marker=dict(size=(p["n"] ** 0.5) * 1.6 + 6, color=BLEU, opacity=0.75, line=dict(color="white", width=2)),
                              customdata=p[["n", "v", "t"]].values,
                              hovertemplate="<b>%{text}</b><br>%{customdata[0]} expéditions<br>valeur %{customdata[1]:,.0f} $"
                                            "<br>à temps %{customdata[2]:.1%}<extra></extra>"))
fig.update_geos(projection_type="natural earth", showcountries=True, countrycolor="#d6d5d0", landcolor="#f3f2ef",
                showocean=False, lataxis_range=[-40, 40], lonaxis_range=[-100, 120])
fig.update_layout(title="Destinations (taille = nombre d'expéditions)", height=380, margin=dict(l=0, r=0, t=36, b=0))
st.plotly_chart(fig, use_container_width=True)

st.markdown("#### Qualité des modèles ML et NLP (dernier calcul batch)")
mt = q("""SELECT DISTINCT ON (modele, metrique) modele, metrique, valeur, jeu FROM ml.metrique_modele
          ORDER BY modele, metrique, calcule_le DESC""")
choix = {"ML1_cout_fret": ["R2_log", "MAPE_median_pct"], "ML1_delai_livraison": ["R2", "MAE_jours"],
         "ML2_risque_fournisseur": ["AUC", "precision", "rappel"], "ML3_anomalies_prix": ["precision", "rappel", "F1"],
         "NLP1_clauses_contrats": ["precision", "rappel", "F1"], "NLP2_classification_incidents": ["exactitude", "F1_macro"]}
noms = {"ML1_cout_fret": "ML 1 · Coût de fret", "ML1_delai_livraison": "ML 1 · Délai de livraison",
        "ML2_risque_fournisseur": "ML 2 · Risque fournisseur", "ML3_anomalies_prix": "ML 3 · Anomalies de prix",
        "NLP1_clauses_contrats": "NLP 1 · Clauses de contrats", "NLP2_classification_incidents": "NLP 2 · Causes d'incidents"}
lignes = []
for mod, ms in choix.items():
    s = mt[(mt["modele"] == mod) & (mt["metrique"].isin(ms))]
    lignes.append({"Modèle": noms[mod], "Métriques": " · ".join(f"{r.metrique} = {nb(r.valeur, 2)}" for r in s.itertuples()),
                   "Jeu d'évaluation": s["jeu"].iloc[0].replace("_", " ") if len(s) else "", "Page": {
                       "ML1": "Expéditions", "ML2": "Fournisseurs", "ML3": "Coûts et fret", "NLP1": "Fournisseurs",
                       "NLP2": "Douanes et risques"}[mod.split("_")[0]]})
st.dataframe(lignes, hide_index=True, use_container_width=True)
