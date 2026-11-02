"""Page 5 · Douanes et risques — indicateurs 21 à 25 + NLP 2 (classification des incidents par cause)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from commun import entete, exp_filtrees, kpi, nb, usd, pct, q, barres_h, bloc_ml, metriques, BLEU, GRIS, STATUT, SERIE

entete("Douanes et risques", "Dédouanement, incidents, sinistres, risque pays et météo")
e = exp_filtrees()
if e.empty:
    st.warning("Aucune expédition pour ces filtres."); st.stop()

inc = q("""SELECT i.id_incident, i.asn_dn, i.horodatage, i.gravite, i.retard_heures, i.cout_estime_usd, i.description,
                  c.cause_predite, c.probabilite, c.cause_declaree, c.cause_retenue, c.origine_cause
           FROM dwh.fait_incident i LEFT JOIN ml.classification_incident c USING (id_incident)""")
inc = inc[inc["asn_dn"].isin(e["asn_dn"])]
sin = q("SELECT * FROM dwh.fait_sinistre")
sin = sin[sin["asn_dn"].isin(e["asn_dn"])]
rp = q("SELECT * FROM dwh.v_risque_pays")
f = st.session_state["filtres"]
rp_f = rp[rp["pays"].isin(f["pays"])] if f.get("pays") else rp
retard_meteo = e[(~e["a_temps"].astype(bool)) & (e["nb_incidents_meteo"] > 0)]

c = st.columns(5)
kpi(c[0], 21, "Dédouanement", f"{nb(e['delai_dedouanement_j'].mean(), 1)} j", "Mainlevée − arrivée de la marchandise")
kpi(c[1], 22, "Incidents ‰ exp.", nb(len(inc) / len(e) * 1000), "Tous niveaux de gravité")
kpi(c[2], 23, "Sinistres cargo", nb(len(sin)), f"Montant réclamé : {usd(sin['montant_reclame_usd'].sum())}",
    usd(sin["montant_indemnise_usd"].sum()) + " indemnisés", "off")
moy = (rp_f["indice_risque"] * 1).mean()
kpi(c[3], 24, "Risque pays", f"{nb(moy, 1)} / 100",
    "40 % LPI (inversé) + 30 % stabilité politique (inversée) + 30 % délai de dédouanement normalisé ; moyenne des pays filtrés")
kpi(c[4], 25, "Retards météo", nb(len(retard_meteo)),
    "Expéditions livrées en retard avec au moins un incident « Météo » (cause déclarée ou prédite par NLP 2)",
    f"{pct(len(retard_meteo) / max((~e['a_temps'].astype(bool)).sum(), 1))} des retards", "off")

g1, g2 = st.columns(2)
dp = e.groupby("pays")["delai_dedouanement_j"].mean().sort_values(ascending=False).head(15).rename("d").reset_index()
g1.plotly_chart(barres_h(dp, "d", "pays", "21 · Délai moyen de dédouanement par pays (15 plus longs, jours)", fmt=lambda v: nb(v, 1)),
                use_container_width=True)
gr = inc.groupby([inc["horodatage"].dt.year.rename("annee"), "gravite"]).size().unstack(fill_value=0)
nexp = e.groupby("annee").size()
fig = go.Figure()
for i, g in enumerate(["mineure", "majeure", "critique"]):
    if g in gr:
        taux = (gr[g] / nexp.reindex(gr.index)).mul(1000)
        fig.add_trace(go.Bar(x=taux.index, y=taux.values, name=g, marker=dict(color=["#a9c8ef", STATUT["alerte"], STATUT["critique"]][i], cornerradius=2),
                             hovertemplate="%{x} · " + g + " : %{y:.0f} ‰<extra></extra>"))
fig.update_layout(barmode="stack", title="22 · Incidents pour 1 000 expéditions, par gravité", height=max(300, 26 * 15 + 70), bargap=.3)
g2.plotly_chart(fig, use_container_width=True)

g3, g4 = st.columns([3, 2])
fig = go.Figure(go.Choropleth(locations=rp_f["iso3"], z=rp_f["indice_risque"], text=rp_f["pays"], zmin=20, zmax=80,
                              colorscale=[[0, "#e8f0fb"], [0.5, "#7aa7e6"], [1, "#0d3f86"]], marker_line_color="white",
                              colorbar=dict(title="indice", thickness=10),
                              hovertemplate="<b>%{text}</b><br>indice de risque %{z:.1f}<extra></extra>"))
fig.update_geos(projection_type="natural earth", showcountries=True, countrycolor="#d6d5d0", landcolor="#f3f2ef",
                lataxis_range=[-40, 40], lonaxis_range=[-100, 120])
fig.update_layout(title="24 · Indice de risque pays (0 = faible, 100 = élevé)", height=380, margin=dict(l=0, r=0, t=36, b=0))
g3.plotly_chart(fig, use_container_width=True)
g4.dataframe(rp_f.sort_values("indice_risque", ascending=False)[["pays", "indice_risque", "lpi", "stabilite_politique",
                                                                  "delai_dedouanement_moyen"]],
             hide_index=True, use_container_width=True, height=380,
             column_config={"pays": "Pays", "indice_risque": st.column_config.ProgressColumn("Indice", min_value=0, max_value=100, format="%.0f"),
                            "lpi": st.column_config.NumberColumn("LPI", format="%.2f"),
                            "stabilite_politique": st.column_config.NumberColumn("Stabilité pol.", format="%.2f"),
                            "delai_dedouanement_moyen": st.column_config.NumberColumn("Douane (j)", format="%.1f")})

g5, g6 = st.columns(2)
s = sin.groupby("nature").agg(n=("numero_sinistre", "count"), m=("montant_reclame_usd", "sum")).reset_index()
g5.plotly_chart(barres_h(s, "m", "nature", "23 · Sinistres cargo : montant réclamé par nature", fmt=usd), use_container_width=True)
met = q("""SELECT d.annee_mois, avg(m.precipitations_mm) pluie FROM dwh.fait_meteo_quotidienne m
           JOIN dwh.dim_date d USING (date_sk) JOIN dwh.dim_pays p USING (pays_sk)""" +
        (f" WHERE p.nom_fr IN ({','.join(repr(x) for x in f['pays'])})" if f.get("pays") else "") + " GROUP BY 1")
rm = retard_meteo.groupby("annee_mois").size().rename("r").reset_index()
fig = go.Figure(go.Bar(x=rm["annee_mois"], y=rm["r"], marker=dict(color=SERIE[2], cornerradius=2),
                       hovertemplate="%{x} : %{y} retards météo<extra></extra>"))
fig.update_layout(title="25 · Retards dus à la météo par mois", height=300)
g6.plotly_chart(fig, use_container_width=True)
mm = met[met["annee_mois"].between(*(e["annee_mois"].min(), e["annee_mois"].max()))].sort_values("annee_mois")
fig = go.Figure(go.Scatter(x=mm["annee_mois"], y=mm["pluie"], mode="lines", line=dict(color=SERIE[0], width=2),
                           hovertemplate="%{x} : %{y:.1f} mm/jour<extra></extra>"))
fig.update_layout(title="25 · Précipitations moyennes dans les pays de destination (mm/jour, Open-Meteo)", height=260)
g6.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------ NLP 2
st.markdown("### Classification des incidents de transport par cause (NLP 2)")
m2, jeu, _ = metriques("NLP2_classification_incidents")
bloc_ml("TF-IDF (mots + caractères) et régression logistique sur la description libre de l'incident",
        "Entraîné sur les incidents dont la cause est déclarée ; il prédit la cause des incidents non déclarés (≈ 35 %).",
        m2, jeu, [("exactitude", "Exactitude", lambda v: pct(v)), ("precision_macro", "Précision (macro)", lambda v: nb(v, 3)),
                  ("rappel_macro", "Rappel (macro)", lambda v: nb(v, 3)), ("F1_macro", "F1 (macro)", lambda v: nb(v, 3)),
                  ("exactitude_non_declares", "Exactitude non déclarés", lambda v: pct(v))])
n1, n2 = st.columns([2, 3])
cc = inc.groupby(["cause_retenue", "origine_cause"]).size().unstack(fill_value=0).reindex(columns=["déclarée", "prédite"], fill_value=0)
cc = cc.loc[cc.sum(1).sort_values().index]
fig = go.Figure()
for col, coul in [("déclarée", BLEU), ("prédite", SERIE[1])]:
    fig.add_trace(go.Bar(y=cc.index, x=cc[col], orientation="h", name=f"cause {col}", marker=dict(color=coul, cornerradius=2),
                         hovertemplate="%{y} · " + col + " : %{x}<extra></extra>"))
fig.update_layout(barmode="stack", title="Incidents par cause retenue", height=380, bargap=.3)
n1.plotly_chart(fig, use_container_width=True)
pr = inc[inc["origine_cause"] == "prédite"].sort_values("horodatage", ascending=False)
n2.markdown("**Derniers incidents sans cause déclarée — cause prédite**")
n2.dataframe(pr[["horodatage", "asn_dn", "description", "cause_predite", "probabilite"]].head(50), hide_index=True,
             use_container_width=True, height=340,
             column_config={"horodatage": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY"), "asn_dn": "Expédition",
                            "description": st.column_config.TextColumn("Description", width="large"), "cause_predite": "Cause prédite",
                            "probabilite": st.column_config.ProgressColumn("Confiance", min_value=0, max_value=1, format="%.2f")})
