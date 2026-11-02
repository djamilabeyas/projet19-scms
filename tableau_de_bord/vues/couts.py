"""Page 4 · Coûts et fret — indicateurs 16 à 20 + ML 3 (anomalies de prix / surfacturation)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from commun import entete, exp_filtrees, kpi, nb, usd, pct, q, barres_h, bloc_ml, metriques, COULEUR_MODE, BLEU, GRIS, STATUT

entete("Coûts et fret", "Coût au kilo, fret par mode, carburant, change et assurance")
e = exp_filtrees()
if e.empty:
    st.warning("Aucune expédition pour ces filtres."); st.stop()

fact = e[(e["fret_usd"] > 0) & e["poids_kg"].notna()]
c = st.columns(5)
kpi(c[0], 16, "Coût par kg", f"{nb(fact['fret_usd'].sum() / fact['poids_kg'].sum(), 2)} $/kg",
    "Fret facturé / poids, expéditions dont le fret est facturé à part et le poids connu")
pm = e.groupby("mode_transport")["fret_usd"].sum()
kpi(c[1], 17, "Fret total", usd(e["fret_usd"].sum()), "Répartition par mode : graphique ci-dessous")
kpi(c[2], 18, "Surcoût carburant", usd(e["surcout_carburant_usd"].sum()),
    "Part BAF du fret : max(0 ; (Brent − 60) × 0,15 %) au cours du Brent du jour de commande", f"{pct(e['surcout_carburant_usd'].sum() / e['fret_usd'].sum())} du fret", "off")
eff = e["effet_change_eur"].sum()
kpi(c[3], 19, "Effet de change", f"{nb(eff / 1e3)} k€",
    "Coût logistique converti en EUR au taux du jour − au taux budgété (moyenne de l'année précédente). Positif = surcoût en euros.",
    f"{nb(eff * 655.957 / 1e6)} M FCFA", "inverse")
kpi(c[4], 20, "Assurance", usd(e["cout_assurance_usd"].sum()), "Primes des polices cargo (à défaut, assurance SCMS)",
    f"{pct(e['cout_assurance_usd'].sum() / e['valeur_usd'].sum(), 2)} de la valeur", "off")

g1, g2 = st.columns(2)
k = fact.groupby("mode_transport").apply(lambda d: d["fret_usd"].sum() / d["poids_kg"].sum(), include_groups=False).reset_index(name="ck")
g1.plotly_chart(barres_h(k, "ck", "mode_transport", "16 · Coût de fret par kilogramme et par mode ($/kg)", fmt=lambda v: nb(v, 2),
                         couleurs=[COULEUR_MODE.get(x, GRIS) for x in k.sort_values("ck")["mode_transport"]]), use_container_width=True)
pmd = pm.rename("fret").reset_index()
g2.plotly_chart(barres_h(pmd, "fret", "mode_transport", "17 · Coût de fret total par mode", fmt=usd,
                         couleurs=[COULEUR_MODE.get(x, GRIS) for x in pmd.sort_values("fret")["mode_transport"]]), use_container_width=True)

g3, g4 = st.columns(2)
mm = e.groupby("annee_mois").agg(s=("surcout_carburant_usd", "sum"), b=("brent_usd", "mean")).reset_index()
fig = go.Figure(go.Bar(x=mm["annee_mois"], y=mm["s"], marker=dict(color=BLEU, cornerradius=2), name="surcoût",
                       hovertemplate="%{x} : %{y:,.0f} $<extra></extra>"))
fig.update_layout(title="18 · Surcoût carburant par mois (USD)", height=300)
g3.plotly_chart(fig, use_container_width=True)
fig = go.Figure(go.Scatter(x=mm["annee_mois"], y=mm["b"], mode="lines", line=dict(color="#eb6834", width=2),
                           hovertemplate="%{x} : %{y:.0f} $/baril<extra></extra>"))
fig.add_hline(y=60, line=dict(color=GRIS, dash="dot"), annotation_text="seuil BAF 60 $")
fig.update_layout(title="18 · Prix moyen du Brent au moment des commandes (USD/baril)", height=300)
g4.plotly_chart(fig, use_container_width=True)

g5, g6 = st.columns(2)
ex = e.groupby("annee").agg(eff=("effet_change_eur", "sum"), t=("taux_usd_eur", "mean")).reset_index()
fig = go.Figure(go.Bar(x=ex["annee"], y=ex["eff"] / 1e3, marker=dict(color=[STATUT["critique"] if v > 0 else STATUT["bon"] for v in ex["eff"]],
                                                                      cornerradius=4), hovertemplate="%{x} : %{y:,.0f} k€<extra></extra>"))
fig.update_layout(title="19 · Effet du taux de change par année (k€, rouge = surcoût)", height=300)
g5.plotly_chart(fig, use_container_width=True)
ass = e.groupby("annee").agg(p=("cout_assurance_usd", "sum"), v=("valeur_usd", "sum")).reset_index()
fig = go.Figure(go.Bar(x=ass["annee"], y=ass["p"], marker=dict(color=BLEU, cornerradius=4), customdata=ass["p"] / ass["v"] * 100,
                       hovertemplate="%{x} : %{y:,.0f} $ (%{customdata:.2f} % de la valeur)<extra></extra>"))
fig.update_layout(title="20 · Coût d'assurance cargo par année (USD)", height=300)
g6.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------ ML 3
st.markdown("### Détection d'anomalies de prix unitaires et de surfacturation (ML 3)")
m3, jeu, _ = metriques("ML3_anomalies_prix")
bloc_ml("Isolation Forest sur l'écart au prix médian du produit (même année, même fournisseur)",
        "Une ligne est signalée quand son prix par conditionnement s'écarte anormalement à la hausse de la référence du marché.",
        m3, jeu, [("nb_anomalies", "Lignes signalées", lambda v: nb(v)), ("precision", "Précision", lambda v: nb(v, 3)),
                  ("rappel", "Rappel", lambda v: nb(v, 3)), ("F1", "F1", lambda v: nb(v, 3))])
an = q("""SELECT a.id_ligne, a.score_anomalie, a.est_anomalie, a.ecart_mediane_pct, f.asn_dn, f.valeur_usd, f.prix_pack_usd,
                 p.molecule, p.groupe_produit, d.nom fournisseur
          FROM ml.anomalie_prix a JOIN dwh.fait_ligne_expedition f USING (id_ligne) JOIN dwh.dim_produit p USING (produit_sk)
          JOIN dwh.dim_fournisseur d USING (fournisseur_sk)""")
an = an[an["asn_dn"].isin(e["asn_dn"])]
a1, a2 = st.columns([3, 2])
fig = go.Figure()
for est, nom, coul in [(False, "normal", "#a9c8ef"), (True, "anomalie", STATUT["critique"])]:
    d = an[an["est_anomalie"] == est]
    fig.add_trace(go.Scattergl(x=d["ecart_mediane_pct"].clip(-90, 800), y=d["score_anomalie"], mode="markers", name=nom,
                               marker=dict(size=8, color=coul, opacity=.6 if est else .35, line=dict(color="white", width=1)),
                               text=d["molecule"], hovertemplate="%{text}<br>écart %{x:.0f} %<br>score %{y:.3f}<extra>" + nom + "</extra>"))
fig.update_layout(title="Score d'anomalie vs écart au prix médian (%)", height=360, xaxis_title="écart au prix médian (%)",
                  yaxis_title="score d'anomalie")
a1.plotly_chart(fig, use_container_width=True)
sur = an[an["est_anomalie"]]
surc = (sur["valeur_usd"] * (1 - 1 / (1 + sur["ecart_mediane_pct"] / 100))).sum()
a2.metric("Surfacturation potentielle", usd(surc), help="Valeur des lignes signalées au-delà du prix médian du produit")
a2.metric("Lignes à contrôler", nb(len(sur)))
a2.dataframe(sur.sort_values("ecart_mediane_pct", ascending=False)[["asn_dn", "molecule", "fournisseur", "ecart_mediane_pct"]].head(12),
             hide_index=True, use_container_width=True,
             column_config={"asn_dn": "Expédition", "molecule": "Produit", "fournisseur": "Fournisseur",
                            "ecart_mediane_pct": st.column_config.NumberColumn("Écart %", format="%.0f")})
