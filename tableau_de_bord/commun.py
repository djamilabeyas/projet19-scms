"""Fonctions partagées du tableau de bord : accès aux données (mis en cache), filtres communs, mise en forme, graphiques."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from etl import bdd  # noqa: E402

# ---------------------------------------------------------------- palette (catégorielle en ordre fixe, statut réservé)
SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLEU, BLEU_CLAIR = "#2a78d6", "#a9c8ef"
STATUT = {"bon": "#1f8a4c", "alerte": "#c98500", "critique": "#c43d3c"}
GRIS = "#8a8984"
ENCRE, ENCRE_2 = "#0b0b0b", "#52514e"
# couleur fixe par entité : un filtre ne repeint jamais les séries restantes
COULEUR_MODE = {"Aérien": SERIE[0], "Routier": SERIE[1], "Aérien affrété": SERIE[2], "Maritime": SERIE[3], "Non renseigné": GRIS}

pio.templates["scms"] = go.layout.Template(layout=dict(
    font=dict(family="Inter, Segoe UI, sans-serif", size=13, color=ENCRE_2),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=SERIE,
    margin=dict(l=8, r=8, t=40, b=8), hoverlabel=dict(bgcolor="white", font_size=13),
    xaxis=dict(showgrid=False, linecolor="#d6d5d0", ticks=""), yaxis=dict(gridcolor="#ecebe7", zeroline=False),
    legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, title_text=""), title=dict(font=dict(size=15, color=ENCRE), x=0)))
pio.templates.default = "plotly_white+scms"


# ---------------------------------------------------------------- formatage à la française
def nb(x, dec=0):
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def usd(x):
    if x is None or pd.isna(x):
        return "–"
    for seuil, suf in [(1e9, " Md"), (1e6, " M"), (1e3, " k")]:
        if abs(x) >= seuil:
            return f"{nb(x / seuil, 1)}{suf} $"
    return f"{nb(x)} $"


def pct(x, dec=1):
    return "–" if x is None or pd.isna(x) else f"{nb(x * 100, dec)} %"


# ---------------------------------------------------------------- données (cache 5 min : la page reflète le dernier chargement)
@st.cache_data(ttl=300, show_spinner=False)
def q(sql):
    return pd.read_sql(sql, bdd.moteur("dwh"))


def expeditions():
    return q("SELECT * FROM dwh.v_expedition")


def fraicheur():
    return q("SELECT * FROM etl.v_fraicheur").iloc[0]


def metriques(modele):
    d = q(f"""SELECT DISTINCT ON (metrique) metrique, valeur, jeu, calcule_le FROM ml.metrique_modele
              WHERE modele = '{modele}' ORDER BY metrique, calcule_le DESC""")
    return dict(zip(d["metrique"], d["valeur"].astype(float))), (d["jeu"].iloc[0] if len(d) else ""), (
        d["calcule_le"].max() if len(d) else None)


# ---------------------------------------------------------------- filtres communs (définis une fois dans app.py)
def filtres():
    return st.session_state.get("filtres", {})


def annees_completes(df, col="annee", mini=100):
    """Années avec un volume suffisant (exclut l'année partielle de fin de série)."""
    n = df.groupby(col).size()
    return n[n >= mini].index


def filtrer(df, col_annee="annee"):
    f = filtres()
    if not f:
        return df
    m = pd.Series(True, index=df.index)
    if col_annee in df and f.get("annees"):
        m &= df[col_annee].between(*f["annees"])
    if "pays" in df and f.get("pays"):
        m &= df["pays"].isin(f["pays"])
    if "mode_transport" in df and f.get("modes"):
        m &= df["mode_transport"].isin(f["modes"])
    if "groupe_produit" in df and f.get("groupes"):
        m &= df["groupe_produit"].isin(f["groupes"])
    return df[m]


def exp_filtrees():
    return filtrer(expeditions())


# ---------------------------------------------------------------- composants
def entete(titre, sous_titre):
    fr = fraicheur()
    d = pd.Timestamp(fr["dernier_chargement"]) if fr["dernier_chargement"] is not None else None
    st.markdown(f"## {titre}")
    st.caption(f"{sous_titre}  ·  🕒 Données chargées le **{d:%d/%m/%Y à %H:%M}** "
               f"({str(fr['dernier_mode']).lower()}, déclencheur : {fr['dernier_declencheur']})" if d else sous_titre)


def kpi(col, numero, libelle, valeur, aide=None, delta=None, delta_color="normal"):
    """Carte d'indicateur : le numéro renvoie à la liste des 25 indicateurs de l'énoncé."""
    col.metric(f"#{numero} {libelle}", valeur, delta=delta, delta_color=delta_color,
               help=(aide or libelle), border=True)


def bloc_ml(titre, description, met, jeu, cles):
    """Encadré d'une fonctionnalité ML/NLP avec ses métriques d'évaluation."""
    with st.container(border=True):
        st.markdown(f"**🤖 {titre}**")
        st.caption(description)
        cols = st.columns(len(cles))
        for c, (k, lib, fmt) in zip(cols, cles):
            v = met.get(k)
            c.metric(lib, "–" if v is None else fmt(v))
        st.caption(f"Évaluation : {jeu.replace('_', ' ')} · modèle entraîné en Python, résultats écrits dans le schéma `ml` par la tâche batch.")


def barres_h(df, x, y, titre, couleur=BLEU, fmt=None, hauteur=None, couleurs=None):
    d = df.sort_values(x)
    fig = go.Figure(go.Bar(x=d[x], y=d[y], orientation="h",
                           marker=dict(color=couleurs if couleurs is not None else couleur, cornerradius=4),
                           text=[fmt(v) for v in d[x]] if fmt else None, textposition="outside", cliponaxis=False,
                           hovertemplate="%{y} : %{x:,.2f}<extra></extra>"))
    fig.update_layout(title=titre, height=hauteur or max(260, 26 * len(d) + 70),
                      xaxis=dict(showticklabels=False, showgrid=False, range=[0, float(d[x].max()) * 1.22]),
                      yaxis=dict(gridcolor="rgba(0,0,0,0)"), bargap=0.25)
    return fig
