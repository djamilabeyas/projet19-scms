"""TRANSFORMATION (nettoyage + contrôles qualité) et CHARGEMENT de chaque source.

Pour chaque source :
  transformer(df_brut, cx) -> (df_propre avec colonne 'cle', liste de rejets)
  charger(cx, rid, df_IU, cles_supprimees, mode) -> None
  hash_cols : colonnes métier utilisées pour détecter les modifications
"""
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from etl import extraction as X
from etl.chargement import upsert, supprimer, cartes, mapper, date_sk, nn
from generateurs.referentiel import PAYS, ORIGINES, PARITE_XAF_EUR


# ====================================================================== contrôles qualité
class Qualite:
    """Collecte les rejets ; chaque règle retire les lignes fautives du DataFrame."""

    def __init__(self, df, cle):
        self.df = df.copy()
        self.cle = cle
        self.rejets = []

    def _rejeter(self, masque, regle, motif):
        bad = self.df[masque]
        for _, r in bad.iterrows():
            self.rejets.append({"cle": r.get(self.cle), "regle": regle, "motif": motif,
                                "donnees": {k: (None if pd.isna(v) else v) for k, v in r.items() if not k.startswith("_")}})
        self.df = self.df[~masque]

    def doublons_exacts(self):
        cols = [c for c in self.df.columns if not c.startswith("_")]
        self._rejeter(self.df.duplicated(subset=cols, keep="first"), "doublon", "Ligne en double (doublon exact)")
        return self

    def doublons_cle(self):
        self._rejeter(self.df.duplicated(subset=[self.cle], keep="first"), "doublon", f"Clé {self.cle} en double")
        return self

    def obligatoire(self, *cols):
        for c in cols:
            v = self.df[c]
            self._rejeter(v.isna() | (v.astype(str).str.strip() == ""), "valeur_manquante", f"{c} manquant")
        return self

    def regle(self, masque, regle, motif):
        self._rejeter(masque.reindex(self.df.index).fillna(False).astype(bool), regle, motif)
        return self


def num(s):
    return pd.to_numeric(s, errors="coerce")


def vide(s):
    return s.isna() | (s.astype(str).str.strip() == "")


@dataclass
class Source:
    nom: str
    extraire: Callable
    transformer: Callable
    charger: Callable
    hash_cols: list
    cible: str


PAYS_NOMS = {p[0] for p in PAYS}


# ====================================================================== API marchés : Brent + change
def t_brent(df, cx):
    d = pd.DataFrame({"date": pd.to_datetime(df["period"], errors="coerce"), "valeur": num(df["value"])})
    q = Qualite(d, "date").obligatoire("date", "valeur").regle(d["valeur"] <= 0, "format_invalide", "Prix négatif ou nul")
    d = q.df
    d["code"] = "BRENT_USD_BBL"
    d["cle"] = d["date"].dt.strftime("%Y-%m-%d") + "|" + d["code"]
    q2 = Qualite(d, "cle").doublons_cle()
    return q2.df, q.rejets + q2.rejets


def t_change(df, cx):
    d = pd.DataFrame({"date": pd.to_datetime(df["date"], errors="coerce"), "devise": df["devise"], "valeur": num(df["taux"])})
    q = Qualite(d, "date").obligatoire("date", "valeur")
    d = q.df
    xaf = d[d["devise"] == "EUR"].copy()          # FCFA dérivé de l'euro (parité fixe 655,957)
    xaf["devise"], xaf["valeur"] = "XAF", xaf["valeur"] * PARITE_XAF_EUR
    d = pd.concat([d, xaf])
    d["code"] = "USD_" + d["devise"]
    d["cle"] = d["date"].dt.strftime("%Y-%m-%d") + "|" + d["code"]
    return d, q.rejets


def c_marche(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(date_sk=date_sk(df["date"]), indicateur_sk=mapper(df["code"], k["indicateur"]), id_execution=rid)
    upsert(cx, "dwh.fait_marche_quotidien", df, ["date_sk", "indicateur_sk"], ["date_sk", "indicateur_sk", "valeur", "id_execution"])
    for cle in suppr:
        d, code = cle.split("|")
        with cx.cursor() as c:
            c.execute("DELETE FROM dwh.fait_marche_quotidien WHERE date_sk = %s AND indicateur_sk = %s",
                      (int(d.replace("-", "")), k["indicateur"].get(code, -1)))


# ====================================================================== API météo
def t_meteo(df, cx):
    d = pd.DataFrame({"date": pd.to_datetime(df["time"], errors="coerce"), "iso3": df["iso3"],
                      "temperature_max_c": num(df["temperature_2m_max"]), "precipitations_mm": num(df["precipitation_sum"]),
                      "vent_max_kmh": num(df["wind_speed_10m_max"])})
    q = Qualite(d, "date").obligatoire("date").regle((d["precipitations_mm"] < 0) | (d["temperature_max_c"].abs() > 60),
                                                     "format_invalide", "Valeur météo hors plage physique")
    d = q.df
    d["fortes_pluies"] = d["precipitations_mm"] >= 30
    d["cle"] = d["date"].dt.strftime("%Y-%m-%d") + "|" + d["iso3"]
    return d, q.rejets


def c_meteo(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(date_sk=date_sk(df["date"]), pays_sk=mapper(df["iso3"], k["pays_iso"]), id_execution=rid)
    upsert(cx, "dwh.fait_meteo_quotidienne", df, ["date_sk", "pays_sk"],
           ["date_sk", "pays_sk", "temperature_max_c", "precipitations_mm", "vent_max_kmh", "fortes_pluies", "id_execution"])


# ====================================================================== indicateurs pays (Banque mondiale, Comtrade, LPI)
def t_banque_mondiale(df, cx):
    d = pd.DataFrame({"iso3": df["countryiso3code"], "annee": num(df["date"]), "code": "WB_" + df["indicator.id"],
                      "valeur": num(df["value"])})
    q = Qualite(d, "iso3").obligatoire("iso3", "valeur")
    d = q.df
    d["cle"] = d["iso3"] + "|" + d["annee"].astype(int).astype(str) + "|" + d["code"]
    return d, q.rejets


def t_comtrade(df, cx):
    a = pd.DataFrame({"iso3": df["reporterISO"], "annee": num(df["refYear"]), "code": "COMTRADE_IMP_3004_USD",
                      "valeur": num(df["primaryValue"])})
    b = pd.DataFrame({"iso3": df["reporterISO"], "annee": num(df["refYear"]), "code": "COMTRADE_IMP_3004_KG",
                      "valeur": num(df["netWgt"])})
    d = pd.concat([a, b])
    q = Qualite(d, "iso3").obligatoire("iso3", "valeur")
    d = q.df
    d["cle"] = d["iso3"] + "|" + d["annee"].astype(int).astype(str) + "|" + d["code"]
    return d, q.rejets


LPI_COLS = {"LPI Score": "LPI_SCORE", "Customs": "LPI_DOUANE", "Infrastructure": "LPI_INFRASTRUCTURE",
            "International shipments": "LPI_EXPEDITIONS_INTL", "Logistics competence": "LPI_COMPETENCE",
            "Tracking & tracing": "LPI_SUIVI", "Timeliness": "LPI_PONCTUALITE"}


def t_lpi(df, cx):
    d = df.rename(columns={"Code": "iso3", "Year": "annee"})
    d = d.melt(id_vars=["iso3", "annee", "_fichier"], value_vars=list(LPI_COLS), var_name="col", value_name="valeur")
    d["code"] = d["col"].map(LPI_COLS)
    d["valeur"] = num(d["valeur"]); d["annee"] = num(d["annee"])
    q = Qualite(d, "iso3").obligatoire("iso3", "annee", "valeur").regle(~d["valeur"].between(1, 5), "format_invalide",
                                                                        "Score LPI hors de l'échelle 1-5")
    d = q.df
    d["cle"] = d["iso3"] + "|" + d["annee"].astype(int).astype(str) + "|" + d["code"]
    return d.drop(columns="col"), q.rejets


def c_indicateur(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(pays_sk=mapper(df["iso3"], k["pays_iso"]), indicateur_sk=mapper(df["code"], k["indicateur"]),
                   annee=df["annee"].astype(int), id_execution=rid)
    upsert(cx, "dwh.fait_indicateur_pays", df, ["pays_sk", "annee", "indicateur_sk"],
           ["pays_sk", "annee", "indicateur_sk", "valeur", "id_execution"])
    for cle in suppr:
        iso, an, code = cle.split("|")
        with cx.cursor() as c:
            c.execute("DELETE FROM dwh.fait_indicateur_pays WHERE pays_sk=%s AND annee=%s AND indicateur_sk=%s",
                      (k["pays_iso"].get(iso, -1), int(an), k["indicateur"].get(code, -1)))


# ====================================================================== fournisseurs (PostgreSQL) -> dim SCD2
SCD2_COLS = ["nom", "pays_origine_iso3", "ville", "categorie", "certification", "note_qualite", "categorie_risque",
             "delai_paiement_j", "devise_facturation"]


def t_fournisseurs(df, cx):
    d = df.copy()
    d["note_qualite"] = num(d["note_qualite"])
    q = (Qualite(d, "code_fournisseur").obligatoire("code_fournisseur", "nom").doublons_cle()
         .regle(~d["note_qualite"].between(1, 5), "format_invalide", "Note qualité hors de l'échelle 1-5"))
    d = q.df
    d["cle"] = d["code_fournisseur"]
    return d, q.rejets


def c_fournisseurs(cx, rid, df, suppr, mode):
    """SCD de type 2 : une modification d'un attribut suivi ferme la version courante et en ouvre une nouvelle."""
    from etl.delta import hacher
    debut = "1900-01-01" if mode == "COMPLET" else pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    with cx.cursor() as c:
        c.execute("SELECT code_fournisseur, fournisseur_sk, hachage_scd, version FROM dwh.dim_fournisseur WHERE est_courant")
        courant = {r[0]: r[1:] for r in c.fetchall()}
        if len(df):
            df = df.copy()
            df["hachage_scd"] = hacher(df, SCD2_COLS)
            for r in df.itertuples():
                vals = tuple(nn(v) for v in (r.nom, r.pays_origine_iso3, r.ville, r.categorie, r.certification, r.note_qualite,
                                             r.categorie_risque, r.delai_paiement_j, r.devise_facturation, r.commentaire_audit))
                vals = vals[:7] + ((int(vals[7]) if vals[7] is not None else None),) + vals[8:] + (int(r.hachage_scd),)
                cur = courant.get(r.code_fournisseur)
                if cur is None:
                    c.execute("""INSERT INTO dwh.dim_fournisseur(code_fournisseur, nom, pays_origine_iso3, ville, categorie,
                                 certification, note_qualite, categorie_risque, delai_paiement_j, devise_facturation,
                                 commentaire_audit, hachage_scd, version, date_debut_validite)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)""", (r.code_fournisseur, *vals, debut))
                elif cur[1] != int(r.hachage_scd):  # changement d'un attribut historisé -> nouvelle version
                    c.execute("""UPDATE dwh.dim_fournisseur SET est_courant = FALSE, date_fin_validite = %s
                                 WHERE fournisseur_sk = %s""", (debut, cur[0]))
                    c.execute("""INSERT INTO dwh.dim_fournisseur(code_fournisseur, nom, pays_origine_iso3, ville, categorie,
                                 certification, note_qualite, categorie_risque, delai_paiement_j, devise_facturation,
                                 commentaire_audit, hachage_scd, version, date_debut_validite)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (r.code_fournisseur, *vals, cur[2] + 1, debut))
                else:  # seul le commentaire d'audit a changé -> écrasement (type 1)
                    c.execute("UPDATE dwh.dim_fournisseur SET commentaire_audit = %s WHERE fournisseur_sk = %s",
                              (r.commentaire_audit, cur[0]))
        for code in suppr:  # supprimé à la source : on ferme la version, l'historique reste pour les faits
            c.execute("""UPDATE dwh.dim_fournisseur SET est_courant = FALSE, est_supprime_source = TRUE, date_fin_validite = %s
                         WHERE code_fournisseur = %s AND est_courant""", (debut, code))


# ====================================================================== entrepôts + mouvements (MySQL)
def t_entrepots(df, cx):
    q = Qualite(df, "code_entrepot").obligatoire("code_entrepot", "nom").doublons_cle()
    d = q.df.copy()
    d["temperature_controlee"] = d["temperature_controlee"].astype(int).astype(bool)
    d["cle"] = d["code_entrepot"]
    return d.drop(columns=["updated_at"]), q.rejets


def c_entrepots(cx, rid, df, suppr, mode):
    cols = ["code_entrepot", "nom", "type_entrepot", "pays_iso3", "ville", "latitude", "longitude", "capacite_palettes",
            "surface_m2", "temperature_controlee", "gestionnaire"]
    upsert(cx, "dwh.dim_entrepot", df, "code_entrepot", cols)
    with cx.cursor() as c:
        for code in suppr:
            c.execute("UPDATE dwh.dim_entrepot SET est_supprime_source = TRUE WHERE code_entrepot = %s", (code,))


def t_mouvements(df, cx):
    d = df.copy()
    d["quantite_palettes"] = num(d["quantite_palettes"])
    q = (Qualite(d, "id_mouvement").obligatoire("code_entrepot", "date_mouvement").doublons_cle()
         .regle(d["quantite_palettes"] < 0, "format_invalide", "Quantité négative"))
    d = q.df
    d["cle"] = d["id_mouvement"].astype(str)
    return d.drop(columns=["updated_at"]), q.rejets


def c_mouvements(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(entrepot_sk=mapper(df["code_entrepot"], k["entrepot"]), date_sk=date_sk(df["date_mouvement"]),
                   asn_dn=df["reference_asn_dn"], id_execution=rid)
    upsert(cx, "dwh.fait_mouvement_stock", df, "id_mouvement",
           ["id_mouvement", "entrepot_sk", "date_sk", "groupe_produit", "type_mouvement", "quantite_palettes", "asn_dn",
            "commentaire", "id_execution"])
    supprimer(cx, "dwh.fait_mouvement_stock", "id_mouvement", suppr)


# ====================================================================== contrats (XML) -> dim_contrat
def t_contrats(df, cx):
    d = df.copy()
    d["montant_plafond"] = num(d["montant_plafond"])
    q = Qualite(d, "id_contrat").obligatoire("id_contrat", "fournisseur", "texte").doublons_cle()
    d = q.df
    d["cle"] = d["id_contrat"]
    return d, q.rejets


def c_contrats(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(code_fournisseur=df["fournisseur"].map(k["fournisseur_code"]), nom_fournisseur=df["fournisseur"],
                   date_signature=pd.to_datetime(df["date_signature"], errors="coerce").dt.date)
    upsert(cx, "dwh.dim_contrat", df, "id_contrat", ["id_contrat", "code_fournisseur", "nom_fournisseur", "date_signature",
                                                     "montant_plafond", "devise", "statut", "texte"])
    supprimer(cx, "dwh.dim_contrat", "id_contrat", suppr)


# ====================================================================== tarifs de fret (Excel)
def t_tarifs(df, cx):
    d = df.copy()
    d["tarif_usd_kg"] = num(d["tarif_usd_kg"]); d["minimum_usd"] = num(d["minimum_usd"]); d["annee"] = num(d["annee_validite"])
    d["cle"] = (d["annee_validite"].astype(str) + "|" + d["origine"] + "|" + d["destination_iso3"] + "|" + d["mode_transport"])
    q = (Qualite(d, "cle").doublons_exacts().obligatoire("tarif_usd_kg").doublons_cle()
         .regle(d["tarif_usd_kg"] <= 0, "format_invalide", "Tarif négatif ou nul"))
    return q.df, q.rejets


def c_tarifs(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(cle_tarif=df["cle"], pays_sk=mapper(df["destination_iso3"], k["pays_iso"]),
                   mode_sk=mapper(df["mode_transport"], k["mode"]), id_execution=rid)
    upsert(cx, "dwh.fait_tarif_fret", df, "cle_tarif", ["cle_tarif", "annee", "origine", "pays_sk", "mode_sk", "tarif_usd_kg",
                                                       "minimum_usd", "transitaire", "id_execution"])
    supprimer(cx, "dwh.fait_tarif_fret", "cle_tarif", suppr)


# ====================================================================== SCMS (CSV Kaggle) -> dim_produit + fait_ligne_expedition
def _date_scms(s):
    return pd.to_datetime(s.where(~s.isin(["Pre-PQ Process", "Date Not Captured", "N/A - From RDC", ""])),
                          format="%d-%b-%y", errors="coerce")


def t_scms(df, cx):
    d = df.copy()
    q = Qualite(d, "ID").doublons_exacts().doublons_cle().obligatoire("ID", "ASN/DN #", "Country")
    q.regle(~q.df["Country"].isin(PAYS_NOMS), "reference_inconnue", "Pays absent du référentiel")
    v = num(q.df["Line Item Value"])
    q.regle(v.isna() | (v < 0), "format_invalide", "Valeur de ligne non numérique ou négative")
    d = q.df.copy()
    o = pd.DataFrame(index=d.index)
    o["id_ligne"] = d["ID"].astype(int)
    o["cle"] = d["ID"]
    o["asn_dn"] = d["ASN/DN #"]; o["code_projet"] = d["Project Code"]; o["num_pq"] = d["PQ #"]; o["num_po_so"] = d["PO / SO #"]
    o["pays"] = d["Country"]; o["gere_par"] = d["Managed By"]; o["circuit"] = d["Fulfill Via"]
    o["incoterm"] = d["Vendor INCO Term"]; o["mode"] = d["Shipment Mode"].replace("", "Inconnu").fillna("Inconnu")
    o["date_pq"] = _date_scms(d["PQ First Sent to Client Date"]); o["date_po"] = _date_scms(d["PO Sent to Vendor Date"])
    o["date_prevue"] = _date_scms(d["Scheduled Delivery Date"]); o["date_livraison"] = _date_scms(d["Delivered to Client Date"])
    o["date_enregistrement"] = _date_scms(d["Delivery Recorded Date"])
    o["date_reference"] = o["date_po"].fillna(o["date_pq"])
    o["fournisseur"] = d["Vendor"]; o["site_fabrication"] = d["Manufacturing Site"]
    o["premiere_ligne"] = d["First Line Designation"].eq("Yes")
    o["groupe_produit"] = d["Product Group"]; o["sous_classification"] = d["Sub Classification"]
    o["molecule"] = d["Molecule/Test Type"]; o["marque"] = d["Brand"]; o["dosage"] = d["Dosage"]; o["forme"] = d["Dosage Form"]
    o["unites_par_pack"] = num(d["Unit of Measure (Per Pack)"])
    o["cle_produit"] = (o["groupe_produit"] + "|" + o["molecule"] + "|" + o["marque"] + "|" + o["dosage"] + "|" + o["forme"]
                        + "|" + d["Unit of Measure (Per Pack)"])
    o["quantite"] = num(d["Line Item Quantity"]); o["valeur_usd"] = num(d["Line Item Value"])
    o["prix_pack_usd"] = num(d["Pack Price"]); o["prix_unitaire_usd"] = num(d["Unit Price"])
    o["assurance_usd"] = num(d["Line Item Insurance (USD)"])
    # --- poids et fret : texte -> numérique, puis ventilation sur les lignes de l'expédition au prorata de la valeur
    poids = num(d["Weight (Kilograms)"]); fret = num(d["Freight Cost (USD)"])
    o["poids_non_saisi"] = d["Weight (Kilograms)"].eq("Weight Captured Separately")
    o["fret_inclus_prix"] = d["Freight Cost (USD)"].eq("Freight Included in Commodity Cost")
    tot_p = poids.groupby(o["asn_dn"]).transform("sum").where(lambda s: s > 0)
    tot_f = fret.groupby(o["asn_dn"]).transform("sum").where(lambda s: s > 0)
    part = (o["valeur_usd"] / o.groupby("asn_dn")["valeur_usd"].transform("sum").replace(0, np.nan)).fillna(
        1 / o.groupby("asn_dn")["id_ligne"].transform("count"))
    o["poids_kg"] = (tot_p * part).round(2)
    o["fret_usd"] = np.where(o["fret_inclus_prix"], 0.0, (tot_f * part).round(2))
    # --- indicateurs de délai
    o["delai_livraison_j"] = (o["date_livraison"] - o["date_reference"]).dt.days
    o["ecart_contractuel_j"] = (o["date_livraison"] - o["date_prevue"]).dt.days
    o["a_temps"] = o["ecart_contractuel_j"] <= 0
    o["delai_reponse_j"] = (o["date_po"] - o["date_pq"]).dt.days
    q2 = Qualite(o, "cle").regle(o["delai_livraison_j"] < 0, "incoherence", "Livraison antérieure à la date de commande")
    o = q2.df.copy()
    o["_fichier"] = d.loc[o.index, "_fichier"]
    return o, q.rejets + q2.rejets


def c_scms(cx, rid, df, suppr, mode):
    prod = df[["cle_produit", "groupe_produit", "sous_classification", "molecule", "marque", "dosage", "forme",
               "unites_par_pack"]].drop_duplicates("cle_produit")
    upsert(cx, "dwh.dim_produit", prod, "cle_produit", list(prod.columns))
    k = cartes(cx)
    rdc = {"ZAF": "RDC-ZA", "KEN": "RDC-KE", "GHA": "RDC-GH"}
    df = df.assign(
        date_pq_sk=date_sk(df["date_pq"]), date_po_sk=date_sk(df["date_po"]), date_reference_sk=date_sk(df["date_reference"]),
        date_prevue_sk=date_sk(df["date_prevue"]), date_livraison_sk=date_sk(df["date_livraison"]),
        date_enregistrement_sk=date_sk(df["date_enregistrement"]), pays_sk=mapper(df["pays"], k["pays_nom"]),
        fournisseur_sk=mapper(df["fournisseur"], k["fournisseur"]), produit_sk=mapper(df["cle_produit"], k["produit"]),
        mode_sk=mapper(df["mode"], k["mode"]), id_execution=rid,
        entrepot_sk=np.where(df["circuit"].eq("From RDC"), -1, -2))
    # rattachement au centre régional le plus proche pour le circuit « From RDC »
    if (df["entrepot_sk"] == -1).any():
        from generateurs.referentiel import RDC
        from generateurs.gen_scms import haversine
        coords = {p[0]: (p[5], p[6]) for p in PAYS}
        def plus_proche(pays):
            la, lo = coords[pays]
            return min(RDC, key=lambda r: haversine(r[4], r[5], la, lo))[0]
        m = df["entrepot_sk"] == -1
        df.loc[m, "entrepot_sk"] = df.loc[m, "pays"].map(lambda p: k["entrepot"].get(plus_proche(p), -1))
    df["entrepot_sk"] = df["entrepot_sk"].replace(-2, -1)
    cols = ["id_ligne", "asn_dn", "code_projet", "num_pq", "num_po_so", "date_pq_sk", "date_po_sk", "date_reference_sk",
            "date_prevue_sk", "date_livraison_sk", "date_enregistrement_sk", "pays_sk", "fournisseur_sk", "produit_sk", "mode_sk",
            "entrepot_sk", "gere_par", "circuit", "incoterm", "site_fabrication", "premiere_ligne", "quantite", "valeur_usd",
            "prix_pack_usd", "prix_unitaire_usd", "poids_kg", "fret_usd", "assurance_usd", "fret_inclus_prix", "poids_non_saisi",
            "delai_livraison_j", "ecart_contractuel_j", "a_temps", "delai_reponse_j", "id_execution"]
    upsert(cx, "dwh.fait_ligne_expedition", df, "id_ligne", cols)
    supprimer(cx, "dwh.fait_ligne_expedition", "id_ligne", suppr)


# ====================================================================== dédouanement (CSV)
def t_douane(df, cx):
    d = df.copy()
    for c in ["date_arrivee", "date_depot_declaration", "date_mainlevee"]:
        d[c] = pd.to_datetime(d[c].replace("", None), errors="coerce")
    q = Qualite(d, "id_dedouanement").doublons_cle().obligatoire("id_dedouanement", "reference_asn_dn")
    q.regle(q.df["date_arrivee"].isna() | q.df["date_mainlevee"].isna(), "valeur_manquante", "Date d'arrivée ou de mainlevée manquante")
    q.regle(q.df["date_mainlevee"] < q.df["date_arrivee"], "incoherence", "Mainlevée antérieure à l'arrivée")
    d = q.df.copy()
    d["delai_dedouanement_j"] = (d["date_mainlevee"] - d["date_arrivee"]).dt.days
    d["delai_depot_j"] = (d["date_depot_declaration"] - d["date_arrivee"]).dt.days
    d["inspection_physique"] = d["inspection_physique"].eq("O")
    d["frais_usd"] = num(d["frais_usd"])
    d["cle"] = d["id_dedouanement"]
    return d, q.rejets


def c_douane(cx, rid, df, suppr, mode):
    iso = {p[0]: p[2] for p in PAYS}
    bur = df[["bureau_douane", "pays"]].drop_duplicates("bureau_douane").rename(columns={"bureau_douane": "libelle"})
    bur["type_bureau"] = bur["libelle"].str.split(" ").str[0]
    bur["pays_iso3"] = bur["pays"].map(iso)
    upsert(cx, "dwh.dim_bureau_douane", bur, "libelle", ["libelle", "type_bureau", "pays_iso3"])
    k = cartes(cx)
    df = df.assign(asn_dn=df["reference_asn_dn"], pays_sk=mapper(df["pays"], k["pays_nom"]),
                   bureau_sk=mapper(df["bureau_douane"], k["bureau"]), date_arrivee_sk=date_sk(df["date_arrivee"]),
                   date_depot_sk=date_sk(df["date_depot_declaration"]), date_mainlevee_sk=date_sk(df["date_mainlevee"]),
                   id_execution=rid)
    upsert(cx, "dwh.fait_dedouanement", df, "id_dedouanement",
           ["id_dedouanement", "asn_dn", "pays_sk", "bureau_sk", "date_arrivee_sk", "date_depot_sk", "date_mainlevee_sk",
            "regime", "inspection_physique", "delai_dedouanement_j", "delai_depot_j", "frais_usd", "commentaire", "id_execution"])
    supprimer(cx, "dwh.fait_dedouanement", "id_dedouanement", suppr)


# ====================================================================== incidents (CSV)
def t_incidents(df, cx):
    d = df.copy()
    d["horodatage"] = pd.to_datetime(d["date_incident"], format="%d/%m/%Y %H:%M", errors="coerce")
    q = (Qualite(d, "id_incident").doublons_cle().obligatoire("id_incident", "reference_asn_dn", "horodatage")
         .obligatoire("description"))
    d = q.df.copy()
    d["retard_heures"] = num(d["retard_heures"]); d["cout_estime_usd"] = num(d["cout_estime_usd"])
    d["cause_declaree"] = d["cause_declaree"].replace("", None)
    d["cle"] = d["id_incident"]
    return d, q.rejets


def c_incidents(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(asn_dn=df["reference_asn_dn"], date_sk=date_sk(df["horodatage"]), pays_sk=mapper(df["pays"], k["pays_nom"]),
                   mode_sk=mapper(df["mode_transport"].replace("", "Inconnu"), k["mode"]),
                   cause_declaree_sk=mapper(df["cause_declaree"], k["cause"]), id_execution=rid)
    upsert(cx, "dwh.fait_incident", df, "id_incident",
           ["id_incident", "asn_dn", "date_sk", "horodatage", "pays_sk", "mode_sk", "cause_declaree_sk", "gravite", "lieu",
            "retard_heures", "cout_estime_usd", "description", "id_execution"])
    supprimer(cx, "dwh.fait_incident", "id_incident", suppr)


# ====================================================================== suivi des conteneurs (JSON)
def t_conteneurs(df, cx):
    d = df.copy()
    if "temperature_c" not in d:
        d["temperature_c"] = np.nan
    if "commentaire" not in d:
        d["commentaire"] = None
    d["latitude"] = num(d["latitude"]); d["longitude"] = num(d["longitude"]); d["temperature_c"] = num(d["temperature_c"])
    d["horodatage"] = pd.to_datetime(d["horodatage"], errors="coerce").dt.tz_localize(None)
    q = (Qualite(d, "id_evenement").doublons_cle().obligatoire("reference_asn_dn", "horodatage")
         .regle(~d["latitude"].between(-90, 90) | ~d["longitude"].between(-180, 180), "format_invalide", "Coordonnées GPS invalides"))
    d = q.df
    d["alerte_temperature"] = d["temperature_c"] > 25
    d["cle"] = d["id_evenement"].astype(int).astype(str)
    return d, q.rejets


def c_conteneurs(cx, rid, df, suppr, mode):
    k = cartes(cx)
    df = df.assign(asn_dn=df["reference_asn_dn"], date_sk=date_sk(df["horodatage"]), mode_sk=mapper(df["mode"], k["mode"]),
                   id_evenement=df["id_evenement"].astype("int64"), id_execution=rid)
    upsert(cx, "dwh.fait_evenement_conteneur", df, "id_evenement",
           ["id_evenement", "numero_conteneur", "asn_dn", "date_sk", "horodatage", "mode_sk", "type_evenement", "latitude",
            "longitude", "temperature_c", "alerte_temperature", "commentaire", "id_execution"])
    supprimer(cx, "dwh.fait_evenement_conteneur", "id_evenement", suppr)


# ====================================================================== assurance cargo (Excel, 2 feuilles)
def t_polices(df, cx):
    d = df.copy()
    for c in ["valeur_assuree_usd", "taux_prime_pct", "prime_usd", "franchise_usd"]:
        d[c] = num(d[c])
    q = (Qualite(d, "numero_police").doublons_cle().obligatoire("numero_police", "reference_asn_dn")
         .regle(d["prime_usd"] < 0, "format_invalide", "Prime négative"))
    d = q.df
    d["cle"] = d["numero_police"]
    return d, q.rejets


def c_polices(cx, rid, df, suppr, mode):
    df = df.assign(asn_dn=df["reference_asn_dn"], date_effet_sk=date_sk(df["date_effet"]), id_execution=rid)
    upsert(cx, "dwh.fait_police_assurance", df, "numero_police",
           ["numero_police", "asn_dn", "date_effet_sk", "assureur", "valeur_assuree_usd", "taux_prime_pct", "prime_usd",
            "franchise_usd", "id_execution"])
    supprimer(cx, "dwh.fait_police_assurance", "numero_police", suppr)


def t_sinistres(df, cx):
    d = df.copy()
    for c in ["montant_reclame_usd", "montant_indemnise_usd"]:
        d[c] = num(d[c])
    q = (Qualite(d, "numero_sinistre").doublons_cle().obligatoire("numero_sinistre", "numero_police")
         .regle(d["montant_indemnise_usd"] > d["montant_reclame_usd"], "incoherence", "Indemnité supérieure au montant réclamé"))
    d = q.df
    d["cle"] = d["numero_sinistre"]
    return d, q.rejets


def c_sinistres(cx, rid, df, suppr, mode):
    df = df.assign(date_declaration_sk=date_sk(df["date_declaration"]), id_execution=rid, asn_dn=None)
    upsert(cx, "dwh.fait_sinistre", df, "numero_sinistre",
           ["numero_sinistre", "numero_police", "id_incident", "asn_dn", "date_declaration_sk", "nature", "statut",
            "montant_reclame_usd", "montant_indemnise_usd", "description", "id_execution"])
    with cx.cursor() as c:  # rattachement à l'expédition via la police
        c.execute("""UPDATE dwh.fait_sinistre s SET asn_dn = p.asn_dn FROM dwh.fait_police_assurance p
                     WHERE s.numero_police = p.numero_police AND s.asn_dn IS DISTINCT FROM p.asn_dn""")
    supprimer(cx, "dwh.fait_sinistre", "numero_sinistre", suppr)


# ====================================================================== registre (ordre d'exécution)
SOURCES = [
    Source("api_brent", X.ext_api_brent, t_brent, c_marche, ["valeur"], "fait_marche_quotidien"),
    Source("api_change", X.ext_api_change, t_change, c_marche, ["valeur"], "fait_marche_quotidien"),
    Source("api_meteo", X.ext_api_meteo, t_meteo, c_meteo, ["temperature_max_c", "precipitations_mm", "vent_max_kmh"],
           "fait_meteo_quotidienne"),
    Source("api_banque_mondiale", X.ext_api_banque_mondiale, t_banque_mondiale, c_indicateur, ["valeur"], "fait_indicateur_pays"),
    Source("api_comtrade", X.ext_api_comtrade, t_comtrade, c_indicateur, ["valeur"], "fait_indicateur_pays"),
    Source("excel_lpi", X.ext_excel_lpi, t_lpi, c_indicateur, ["valeur"], "fait_indicateur_pays"),
    Source("pg_fournisseurs", X.ext_pg_fournisseurs, t_fournisseurs, c_fournisseurs, SCD2_COLS + ["commentaire_audit"],
           "dim_fournisseur"),
    Source("mysql_entrepots", X.ext_mysql_entrepots, t_entrepots, c_entrepots,
           ["nom", "type_entrepot", "pays_iso3", "ville", "capacite_palettes", "surface_m2", "gestionnaire"], "dim_entrepot"),
    Source("mysql_mouvements", X.ext_mysql_mouvements, t_mouvements, c_mouvements,
           ["code_entrepot", "date_mouvement", "groupe_produit", "type_mouvement", "quantite_palettes", "reference_asn_dn"],
           "fait_mouvement_stock"),
    Source("xml_contrats", X.ext_xml_contrats, t_contrats, c_contrats, ["fournisseur", "montant_plafond", "statut", "texte"],
           "dim_contrat"),
    Source("excel_tarifs", X.ext_excel_tarifs, t_tarifs, c_tarifs, ["tarif_usd_kg", "minimum_usd", "transitaire"], "fait_tarif_fret"),
    Source("csv_scms", X.ext_csv_scms, t_scms, c_scms,
           ["asn_dn", "pays", "mode", "fournisseur", "date_prevue", "date_livraison", "quantite", "valeur_usd", "poids_kg",
            "fret_usd", "assurance_usd", "cle_produit"], "fait_ligne_expedition"),
    Source("csv_douane", X.ext_csv_douane, t_douane, c_douane,
           ["reference_asn_dn", "bureau_douane", "date_arrivee", "date_mainlevee", "frais_usd", "inspection_physique", "commentaire"],
           "fait_dedouanement"),
    Source("csv_incidents", X.ext_csv_incidents, t_incidents, c_incidents,
           ["reference_asn_dn", "horodatage", "gravite", "retard_heures", "cout_estime_usd", "description", "cause_declaree"],
           "fait_incident"),
    Source("json_conteneurs", X.ext_json_conteneurs, t_conteneurs, c_conteneurs,
           ["reference_asn_dn", "type_evenement", "horodatage", "latitude", "longitude", "temperature_c"], "fait_evenement_conteneur"),
    Source("excel_polices", X.ext_excel_polices, t_polices, c_polices, ["reference_asn_dn", "valeur_assuree_usd", "prime_usd"],
           "fait_police_assurance"),
    Source("excel_sinistres", X.ext_excel_sinistres, t_sinistres, c_sinistres,
           ["numero_police", "statut", "montant_reclame_usd", "montant_indemnise_usd"], "fait_sinistre"),
]
