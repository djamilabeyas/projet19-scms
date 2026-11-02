"""Page 2 · Expéditions — indicateurs 6 à 10 + ML 1 (prédiction du coût et du délai)."""
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from commun import (entete, exp_filtrees, kpi, nb, usd, barres_h, bloc_ml, metriques, q, COULEUR_MODE, BLEU, GRIS)

entete("Expéditions", "Volumes par mode, pays et produit, poids et respect des délais contractuels")
e = exp_filtrees()
if e.empty:
    st.warning("Aucune expédition pour ces filtres."); st.stop()

c = st.columns(5)
modes = e["mode_transport"].value_counts()
kpi(c[0], 6, "Mode principal", f"{modes.index[0]} ({nb(modes.iloc[0] / len(e) * 100)} %)", "Détail : graphique ci-dessous")
pays = e["pays"].value_counts()
kpi(c[1], 7, "Pays n°1", pays.index[0], "Expéditions par pays : graphique ci-dessous",
    f"{nb(pays.iloc[0])} expéditions", "off")
prod = e["groupe_produit"].value_counts()
kpi(c[2], 8, "Produit n°1", f"{prod.index[0]} ({nb(prod.iloc[0] / len(e) * 100)} %)")
kpi(c[3], 9, "Poids moyen", f"{nb(e['poids_kg'].mean())} kg", "Expéditions dont le poids est saisi")
kpi(c[4], 10, "Écart vs contrat", f"{nb(e['ecart_contractuel_j'].mean(), 1)} j",
    "Moyenne (date de livraison − date de livraison prévue) ; négatif = en avance")

g1, g2, g3 = st.columns(3)
m = modes.rename_axis("mode").reset_index(name="n")
g1.plotly_chart(barres_h(m, "n", "mode", "6 · Expéditions par mode de transport", fmt=nb,
                         couleurs=[COULEUR_MODE.get(x, GRIS) for x in m.sort_values("n")["mode"]]), use_container_width=True)
p = pays.head(15).rename_axis("pays").reset_index(name="n")
g2.plotly_chart(barres_h(p, "n", "pays", "7 · Expéditions par pays (15 premiers)", fmt=nb), use_container_width=True)
pr = prod.rename_axis("groupe").reset_index(name="n")
g3.plotly_chart(barres_h(pr, "n", "groupe", "8 · Expéditions par groupe de produits", fmt=nb), use_container_width=True)

g4, g5 = st.columns(2)
pm = e.groupby("mode_transport")["poids_kg"].mean().rename("poids").reset_index()
g4.plotly_chart(barres_h(pm, "poids", "mode_transport", "9 · Poids moyen par expédition et par mode (kg)", fmt=nb,
                         couleurs=[COULEUR_MODE.get(x, GRIS) for x in pm.sort_values("poids")["mode_transport"]]),
                use_container_width=True)
ec = e["ecart_contractuel_j"].clip(-30, 60)
fig = go.Figure(go.Histogram(x=ec, xbins=dict(size=3), marker=dict(color=BLEU, line=dict(color="white", width=1)),
                             hovertemplate="écart %{x} j : %{y} expéditions<extra></extra>"))
fig.add_vline(x=0, line=dict(color=GRIS, dash="dot"), annotation_text="date prévue")
fig.update_layout(title="10 · Distribution de l'écart réel − contractuel (jours, borné à [−30 ; 60])", height=320)
g5.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------ ML 1
st.markdown("### Prédiction du coût et du délai d'une expédition (ML 1)")
mc, jeu, _ = metriques("ML1_cout_fret")
md, _, _ = metriques("ML1_delai_livraison")
b1, b2 = st.columns(2)
with b1:
    bloc_ml("Coût de fret (régression Gradient Boosting)", "Variables : mode, pays, origine, produit, poids, valeur, Brent, LPI, mois.",
            mc, jeu, [("R2_log", "R² (log)", lambda v: nb(v, 3)), ("MAE_usd", "Erreur absolue moy.", usd),
                      ("MAPE_median_pct", "Erreur relative médiane", lambda v: f"{nb(v, 1)} %")])
with b2:
    bloc_ml("Délai de livraison (régression Gradient Boosting)", "Mêmes variables + délai contractuel prévu à la commande.",
            md, jeu, [("R2", "R²", lambda v: nb(v, 3)), ("MAE_jours", "Erreur absolue moy.", lambda v: f"{nb(v, 1)} j"),
                      ("RMSE_jours", "RMSE", lambda v: f"{nb(v, 1)} j")])
t = e[e["cout_fret_predit_usd"].notna() & (e["fret_usd"] > 0)]
s1, s2 = st.columns(2)
fig = go.Figure()
for i, (mo, d) in enumerate(t.groupby("mode_transport")):
    fig.add_trace(go.Scattergl(x=d["fret_usd"], y=d["cout_fret_predit_usd"], mode="markers", name=mo,
                               marker=dict(size=8, color=COULEUR_MODE.get(mo, GRIS), opacity=.55, line=dict(color="white", width=1)),
                               hovertemplate="réel %{x:,.0f} $ · prédit %{y:,.0f} $<extra>" + mo + "</extra>"))
lim = [t["fret_usd"].quantile(.005), t["fret_usd"].quantile(.995)]
fig.add_trace(go.Scatter(x=lim, y=lim, mode="lines", line=dict(color=GRIS, dash="dot", width=1), name="prédiction parfaite"))
fig.update_layout(title="Coût de fret : prédit vs réel (USD, échelle log)", height=380, xaxis=dict(type="log", title="réel"),
                  yaxis=dict(type="log", title="prédit"))
s1.plotly_chart(fig, use_container_width=True)
dd = e[e["delai_predit_j"].notna()]
fig = go.Figure(go.Scattergl(x=dd["delai_livraison_j"], y=dd["delai_predit_j"], mode="markers",
                             marker=dict(size=8, color=BLEU, opacity=.35, line=dict(color="white", width=1)),
                             hovertemplate="réel %{x} j · prédit %{y:.0f} j<extra></extra>"))
fig.add_trace(go.Scatter(x=[0, 250], y=[0, 250], mode="lines", line=dict(color=GRIS, dash="dot", width=1), showlegend=False))
fig.update_layout(title="Délai de livraison : prédit vs réel (jours)", height=380, xaxis=dict(range=[0, 250], title="réel"),
                  yaxis=dict(range=[0, 250], title="prédit"), showlegend=False)
s2.plotly_chart(fig, use_container_width=True)


# simulateur : estimation d'une nouvelle expédition avec le modèle entraîné
@st.cache_resource
def charger_modele():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import config
    f = config.MODELES / "ml1_cout_delai.joblib"
    return joblib.load(f) if f.exists() else None


mod = charger_modele()
if mod and "categories" in mod:
    with st.expander("🧮 Simulateur : estimer le coût et le délai d'une nouvelle expédition", expanded=False):
        libelles = {"Air": "Aérien", "Truck": "Routier", "Air Charter": "Aérien affrété", "Ocean": "Maritime"}
        isos = [x for x in mod["categories"]["iso3"] if x != "NA"]
        a, b, c3, d4, e5 = st.columns(5)
        mode = a.selectbox("Mode", list(libelles), format_func=libelles.get)
        iso = b.selectbox("Pays (ISO3)", isos, index=isos.index("CMR") if "CMR" in isos else 0)
        grp = c3.selectbox("Produit", ["ARV", "HRDT", "ACT", "ANTM", "MRDT"])
        poids = d4.number_input("Poids (kg)", 10, 50000, 1500, step=100)
        valeur = e5.number_input("Valeur (USD)", 1000, 5_000_000, 150_000, step=10_000)
        f1, f2, f3 = st.columns(3)
        origine = f1.selectbox("Origine du fournisseur", [x for x in mod["categories"]["pays_origine_iso3"] if x != "NA"])
        brent = f2.slider("Prix du Brent (USD/baril)", 30, 140, 60)
        prevu = f3.slider("Délai contractuel prévu (jours)", 20, 160, 60)
        lpi = q(f"SELECT lpi FROM dwh.v_risque_pays WHERE iso3 = '{iso}'")
        x = pd.DataFrame([{"mode_transport": libelles[mode], "iso3": iso, "groupe_produit": grp, "circuit": "Direct Drop",
                           "incoterm": "EXW", "pays_origine_iso3": origine, "log_poids": np.log1p(poids),
                           "log_valeur": np.log1p(valeur), "nb_lignes": 1, "brent_usd": brent, "mois": 6, "annee": 2015,
                           "lpi": float(lpi["lpi"].iloc[0]) if len(lpi) else 2.6, "delai_prevu_j": prevu}])
        for col, cat in mod["categories"].items():
            x[col] = pd.Categorical(x[col], categories=cat)
        cout = float(np.expm1(mod["cout"].predict(x[mod["colonnes_cout"]]))[0])
        delai = float(mod["delai"].predict(x[mod["colonnes_delai"]])[0])
        r1, r2 = st.columns(2)
        r1.metric("Coût de fret estimé", usd(cout), help="Prédiction du modèle ML 1 (coût)")
        r2.metric("Délai de livraison estimé", f"{nb(delai)} jours", help="Prédiction du modèle ML 1 (délai)")
