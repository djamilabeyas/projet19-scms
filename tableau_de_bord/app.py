"""Tableau de bord du projet 19 · Expéditions internationales et approvisionnement (USAID / SCMS).

  streamlit run tableau_de_bord/app.py

5 pages (1 synthèse + 4 domaines), filtres communs dans la barre latérale, navigation, indicateur d'actualité.
"""
import pandas as pd
import streamlit as st

from commun import expeditions, fraicheur

st.set_page_config(page_title="Projet 19 · Approvisionnement SCMS", page_icon="🚢", layout="wide")
st.markdown("""<style>
  [data-testid="stMetricValue"] {font-size: 1.65rem;}
  [data-testid="stMetricLabel"] p {font-size: .82rem; color: #52514e; white-space: normal;}
  [data-testid="stMetricLabel"] div {overflow: visible; white-space: normal;}
  .block-container {padding-top: 2rem;}
</style>""", unsafe_allow_html=True)

pages = [
    st.Page("vues/synthese.py", title="Synthèse", icon="🏠", default=True),
    st.Page("vues/expeditions.py", title="Expéditions", icon="📦"),
    st.Page("vues/fournisseurs.py", title="Fournisseurs", icon="🏭"),
    st.Page("vues/couts.py", title="Coûts et fret", icon="💲"),
    st.Page("vues/douanes_risques.py", title="Douanes et risques", icon="🛃"),
]
nav = st.navigation(pages, position="sidebar")

# ------------------------------------------------------------ filtres communs à toutes les pages
e = expeditions()
with st.sidebar:
    st.markdown("### Filtres communs")
    amin, amax = int(e["annee"].min()), int(e["annee"].max())
    annees = st.slider("Période (année de livraison)", amin, amax, (amin, amax), key="f_annees")
    pays = st.multiselect("Pays de destination", sorted(e["pays"].dropna().unique()), key="f_pays", placeholder="Tous")
    modes = st.multiselect("Mode de transport", sorted(e["mode_transport"].dropna().unique()), key="f_modes", placeholder="Tous")
    groupes = st.multiselect("Groupe de produits", sorted(e["groupe_produit"].dropna().unique()), key="f_groupes",
                             placeholder="Tous", help="ARV : antirétroviraux · HRDT : tests VIH · ACT/ANTM : antipaludiques · MRDT : tests paludisme")
    st.session_state["filtres"] = {"annees": annees, "pays": pays, "modes": modes, "groupes": groupes}
    st.divider()
    fr = fraicheur()
    if fr["dernier_chargement"] is not None:
        d = pd.Timestamp(fr["dernier_chargement"])
        st.markdown(f"**🕒 Dernier chargement**  \n{d:%d/%m/%Y %H:%M}  \n"
                    f"<small>{str(fr['dernier_mode']).lower()} · {fr['dernier_declencheur']} · {int(fr['nb_executions'])} exécutions</small>",
                    unsafe_allow_html=True)
    if st.button("↻ Actualiser les données", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("Sources : USAID SCMS (Kaggle), Banque mondiale, EIA, BCE, Open-Meteo, UN Comtrade + 9 sources internes.")

nav.run()
