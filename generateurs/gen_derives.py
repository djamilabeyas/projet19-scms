"""Sources générées 2, 5, 8 à 14 : dérivées des expéditions SCMS pour rester cohérentes.

Fonctionne aussi avec le vrai fichier Kaggle : on relit le CSV SCMS (et la vérité terrain
latente si elle existe) pour construire fournisseurs, contrats, douane, incidents, conteneurs,
assurance, tarifs de fret, entrepôts et LPI.
"""
import json
import numpy as np
import pandas as pd
from lxml import etree

import config
from etl import bdd
from generateurs import textes
from generateurs.referentiel import PAYS, FOURNISSEURS, ORIGINES, RDC, PRODUITS
from generateurs.gen_scms import haversine

P_SCMS = {p[0]: p for p in PAYS}
VILLES_DOUANE = {p[0]: (f"Aéroport de {p[4]}", f"Port de {p[4]}", f"Poste frontière de {p[4]}") for p in PAYS}


def lire_expeditions():
    df = pd.read_csv(config.SOURCES / "scms" / "SCMS_Delivery_History_Dataset.csv", dtype=str)
    df = df.drop_duplicates()
    for c in ["Scheduled Delivery Date", "Delivered to Client Date"]:
        df[c] = pd.to_datetime(df[c], format="%d-%b-%y", errors="coerce")
    df["poids"] = pd.to_numeric(df["Weight (Kilograms)"], errors="coerce")
    df["valeur"] = pd.to_numeric(df["Line Item Value"], errors="coerce")
    e = df.groupby("ASN/DN #").agg(pays=("Country", "first"), mode=("Shipment Mode", "first"), vendeur=("Vendor", "first"),
                                   prevu=("Scheduled Delivery Date", "first"), livre=("Delivered to Client Date", "first"),
                                   poids=("poids", "sum"), valeur=("valeur", "sum"), groupe=("Product Group", "first"),
                                   nb_lignes=("ID", "count")).reset_index().rename(columns={"ASN/DN #": "asn_dn"})
    e["mode"] = e["mode"].fillna("Air")
    e["retard_j"] = (e["livre"] - e["prevu"]).dt.days
    lat = config.VERITE / "scms_latent.csv"
    if lat.exists():
        l = pd.read_csv(lat)[["asn_dn", "cause_retard", "distance_km", "pluie_7j"]]
        e = e.merge(l, on="asn_dn", how="left")
    else:
        e["cause_retard"] = np.where(e["retard_j"] > 0, "transport", None)
        e["distance_km"] = 6000; e["pluie_7j"] = 0
    e["distance_km"] = e["distance_km"].fillna(6000)
    e["pluie_7j"] = e["pluie_7j"].fillna(0)
    e["poids"] = e["poids"].where(e["poids"] > 0, e["valeur"] / 60)
    return df, e


# ---------------------------------------------------------------- 8. fournisseurs (PostgreSQL)
def gen_fournisseurs(rng):
    bdd.executer_fichier_pg(config.RACINE / "sql" / "sources_postgres.sql", config.PG_DB_SOURCE)
    f_fiab = config.VERITE / "fournisseurs_fiabilite.csv"
    fiab = pd.read_csv(f_fiab).set_index("vendeur")["fiabilite"].to_dict() if f_fiab.exists() else {}
    lignes = []
    for i, (nom, orig, poids) in enumerate(FOURNISSEURS, start=1):
        if nom == "SCMS from RDC":
            cat, cert = "Centre régional", "SRA"
        else:
            cat = rng.choice(["Fabricant", "Fabricant", "Grossiste", "Distributeur", "Fondation"])
            cert = rng.choice(["OMS-PQ", "OMS-PQ", "FDA", "SRA", "Aucune"], p=[.35, .2, .2, .15, .1])
        note = round(float(np.clip(4.3 - 14 * fiab.get(nom, 0.03) + rng.normal(0, 0.45), 1, 5)), 1)
        risque = "faible" if note >= 4 else "moyen" if note >= 3 else "élevé"
        villes = {"IND": "Hyderabad", "ZAF": "Johannesburg", "USA": "New York", "DEU": "Francfort", "CHE": "Bâle",
                  "CHN": "Shanghai", "ISR": "Yavne", "IRL": "Dublin", "BEL": "Anvers", "GBR": "Londres", "KEN": "Nairobi"}
        lignes.append((f"F{i:04d}", nom, orig, villes[orig], cat, cert, note, risque, int(rng.choice([30, 45, 60, 90])),
                       ORIGINES[orig][3], f"achats{i}@{nom.split()[0].lower().strip(',.')}.com",
                       textes.commentaire_audit(rng, note)))
    cx = bdd.pg_connexion(config.PG_DB_SOURCE)
    with cx.cursor() as c:
        c.executemany("""INSERT INTO fournisseur(code_fournisseur, nom, pays_origine_iso3, ville, categorie, certification,
                         note_qualite, categorie_risque, delai_paiement_j, devise_facturation, email_contact, commentaire_audit,
                         created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'2015-12-31','2015-12-31')""", lignes)
    cx.commit(); cx.close()
    print(f"  -> PostgreSQL fournisseur : {len(lignes)} lignes")


# ---------------------------------------------------------------- 12. entrepôts (MySQL)
def gen_entrepots(rng, exp):
    bdd.executer_fichier_mysql(config.RACINE / "sql" / "sources_mysql.sql")
    ents = [(c, n, "Centre de distribution régional", iso, v, lat, lon, int(rng.integers(4000, 9000)),
             int(rng.integers(8000, 20000)), 1, "SCMS / Chemonics") for c, n, iso, v, lat, lon in RDC]
    top = exp["pays"].value_counts().index[:14]
    for p in top:
        pz = P_SCMS[p]
        ents.append((f"MC-{pz[2]}", f"Magasin central {pz[1]}", "Magasin central national", pz[2], pz[4], pz[5], pz[6],
                     int(rng.integers(800, 4000)), int(rng.integers(1500, 9000)), int(rng.random() < .6),
                     rng.choice(["Ministère de la Santé", "Centrale d'achat nationale", "Partenaire logistique privé"])))
    m = bdd.mysql_connexion()
    with m.cursor() as c:
        c.executemany("""INSERT INTO entrepot(code_entrepot, nom, type_entrepot, pays_iso3, ville, latitude, longitude,
                         capacite_palettes, surface_m2, temperature_controlee, gestionnaire, updated_at)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'2015-12-31 00:00:00')""", ents)
    # mouvements de stock journaliers (volume)
    n = int(350_000 * config.ECHELLE)
    codes = [e[0] for e in ents]
    jours = pd.date_range("2006-06-01", "2015-12-31").values
    groupes = np.array(["ARV", "ARV", "ARV", "HRDT", "ANTM", "ACT", "MRDT"])
    types = np.array(["ENTREE", "SORTIE", "SORTIE", "TRANSFERT", "AJUSTEMENT"])
    refs = exp["asn_dn"].values
    df = pd.DataFrame({
        "code_entrepot": rng.choice(codes, n),
        "date_mouvement": pd.to_datetime(rng.choice(jours, n)).strftime("%Y-%m-%d"),
        "groupe_produit": rng.choice(groupes, n),
        "type_mouvement": rng.choice(types, n, p=[.3, .3, .25, .1, .05]),
        "quantite_palettes": np.round(rng.gamma(1.5, 3, n), 2),
        "reference_asn_dn": np.where(rng.random(n) < .3, rng.choice(refs, n), None),
        "commentaire": np.where(rng.random(n) < .05, "Écart d'inventaire constaté", None),
    })
    f = config.DATA / "tmp_mvt.csv"
    df.to_csv(f, index=False, header=False, na_rep="\\N")
    with m.cursor() as c:
        c.execute(f"""LOAD DATA LOCAL INFILE '{f.as_posix()}' INTO TABLE mouvement_stock FIELDS TERMINATED BY ','
                      OPTIONALLY ENCLOSED BY '"' (code_entrepot, date_mouvement, groupe_produit, type_mouvement,
                      quantite_palettes, @ref, @com) SET reference_asn_dn = NULLIF(@ref,'\\\\N'),
                      commentaire = NULLIF(@com,'\\\\N'), updated_at='2015-12-31 00:00:00'""")
    m.close(); f.unlink()
    print(f"  -> MySQL entrepot : {len(ents)} lignes, mouvement_stock : {n} lignes")


# ---------------------------------------------------------------- 2. tarifs de fret (Excel)
def gen_tarifs(rng):
    base = {"Air": 4.2, "Air Charter": 7.5, "Truck": 0.55, "Ocean": 0.28}
    lignes = []
    origines = list(ORIGINES) + [r[0] for r in RDC]
    for annee in range(2006, 2016):
        for o in origines:
            if o.startswith("RDC"):
                olat, olon = [(r[4], r[5]) for r in RDC if r[0] == o][0]
            else:
                olat, olon = ORIGINES[o][1], ORIGINES[o][2]
            for p in PAYS:
                d = float(haversine(olat, olon, p[5], p[6]))
                for mode, b in base.items():
                    if mode == "Truck" and d > 5000:
                        continue
                    lignes.append({"annee_validite": annee, "date_debut": f"{annee}-01-01", "date_fin": f"{annee}-12-31",
                                   "origine": o, "destination_iso3": p[2], "destination": p[1], "mode_transport": mode,
                                   "tarif_usd_kg": round(b * (0.6 + d / 8000) * 0.98 ** (annee - 2006) * rng.normal(1, .07), 3),
                                   "minimum_usd": int(rng.choice([150, 250, 400, 600])), "devise": "USD",
                                   "transitaire": rng.choice(["Kuehne+Nagel", "DHL Global Forwarding", "Bolloré Logistics",
                                                              "Agility", "Panalpina", "Imperial Logistics"])})
    df = pd.DataFrame(lignes)
    # défauts : doublons et tarifs manquants
    df = pd.concat([df, df.sample(25, random_state=2)])
    df.loc[df.sample(40, random_state=3).index, "tarif_usd_kg"] = np.nan
    lisez = pd.DataFrame({"Information": [
        "Grille tarifaire des transitaires (USD par kg), une version par année de validité.",
        "Surcharge carburant (BAF) : max(0 ; (Brent − 60) × 0,15 %) du fret de base, Brent du jour d'expédition.",
        "Origine : code ISO3 du pays du fournisseur ou code du centre régional (RDC-ZA, RDC-KE, RDC-GH)."]})
    with pd.ExcelWriter(config.SOURCES / "tarifs_fret.xlsx", engine="openpyxl") as w:
        lisez.to_excel(w, sheet_name="Lisez-moi", index=False)
        df.to_excel(w, sheet_name="Tarifs", index=False)
    print(f"  -> tarifs_fret.xlsx : {len(df)} lignes")


# ---------------------------------------------------------------- 5. LPI (Excel Banque mondiale)
def gen_lpi(rng):
    with pd.ExcelWriter(config.SOURCES / "International_LPI_from_2007_to_2016.xlsx", engine="openpyxl") as w:
        for annee in (2007, 2010, 2012, 2014, 2016):
            rows = []
            for p in PAYS:
                s = float(np.clip(p[9] + 0.03 * (annee - 2007) + rng.normal(0, .12), 1.5, 4.5))
                comp = {k: round(float(np.clip(s + rng.normal(0, .2), 1, 5)), 2) for k in
                        ["Customs", "Infrastructure", "International shipments", "Logistics competence",
                         "Tracking & tracing", "Timeliness"]}
                rows.append({"Country": p[0], "Code": p[2], "Year": annee, "LPI Score": round(s, 2), **comp})
            df = pd.DataFrame(rows).sort_values("LPI Score", ascending=False)
            df.insert(4, "LPI Rank", range(1, len(df) + 1))
            df.to_excel(w, sheet_name=str(annee), index=False, startrow=2)
            ws = w.sheets[str(annee)]
            ws["A1"] = f"International LPI {annee} – The World Bank"
    print("  -> International_LPI_from_2007_to_2016.xlsx : 5 feuilles")


# ---------------------------------------------------------------- 9. contrats (XML)
def gen_contrats(rng):
    racine = etree.Element("contrats", source="Service achats SCMS", version="1.2")
    verite = []
    num = 1
    for nom, orig, poids in FOURNISSEURS:
        if nom == "SCMS from RDC":
            continue
        debut = pd.Timestamp("2005-10-01") + pd.Timedelta(days=int(rng.integers(0, 300)))
        while debut.year <= 2015:
            duree = int(rng.choice([12, 24, 36]))
            fin = debut + pd.DateOffset(months=duree) - pd.Timedelta(days=1)
            c = {"num": f"SCMS-CT-{debut.year}-{num:04d}", "fournisseur": nom, "date_debut": debut, "date_fin": fin,
                 "incoterm": str(rng.choice(["EXW", "FCA", "CIP", "DDP", "DAP"])),
                 "penalite_pct": float(rng.choice([0.1, 0.2, 0.25, 0.5, 1.0, 1.5, 2.0])),
                 "unite": str(rng.choice(["jour", "semaine"], p=[.6, .4])),
                 "plafond_pct": float(rng.choice([5, 8, 10, 15, 20])),
                 "delai_livraison_j": int(rng.choice([30, 45, 60, 90, 120])),
                 "delai_paiement_j": int(rng.choice([30, 45, 60, 90])), "force_majeure": bool(rng.random() < .8),
                 "montant": float(rng.integers(2, 80) * 250000), "devise": ORIGINES[orig][3] if rng.random() < .3 else "USD",
                 "produits": "antirétroviraux" if rng.random() < .7 else "tests de diagnostic rapide"}
            el = etree.SubElement(racine, "contrat", id=c["num"])
            etree.SubElement(el, "fournisseur").text = nom
            etree.SubElement(el, "date_signature").text = (debut - pd.Timedelta(days=int(rng.integers(10, 60)))).strftime("%Y-%m-%d")
            etree.SubElement(el, "montant_plafond", devise=c["devise"]).text = f"{c['montant']:.0f}"
            etree.SubElement(el, "statut").text = "actif" if fin.year >= 2015 else "clos"
            etree.SubElement(el, "texte").text = etree.CDATA(textes.contrat(rng, c))
            verite.append({"id_contrat": c["num"], "penalite_pct": c["penalite_pct"], "unite_penalite": c["unite"],
                           "plafond_pct": c["plafond_pct"], "delai_livraison_j": c["delai_livraison_j"],
                           "delai_paiement_j": c["delai_paiement_j"], "date_fin": fin.date(), "date_debut": debut.date(),
                           "incoterm": c["incoterm"], "force_majeure": c["force_majeure"]})
            num += 1
            debut = fin + pd.Timedelta(days=1)
    etree.ElementTree(racine).write(str(config.SOURCES / "contrats_fournisseurs.xml"), encoding="utf-8",
                                    xml_declaration=True, pretty_print=True)
    pd.DataFrame(verite).to_csv(config.VERITE / "contrats_clauses.csv", index=False)
    print(f"  -> contrats_fournisseurs.xml : {len(verite)} contrats")


# ---------------------------------------------------------------- 11. dédouanement (CSV)
def gen_douane(rng, exp):
    rows = []
    for i, e in enumerate(exp.itertuples(), start=1):
        if pd.isna(e.livre):
            continue
        long_ = (e.cause_retard == "douane")
        jours = int(rng.gamma(2.0, 2.2)) + (int(rng.integers(6, 25)) if long_ else 0)
        if e.mode == "Truck":
            bureau = VILLES_DOUANE[e.pays][2]
        elif e.mode == "Ocean":
            bureau = VILLES_DOUANE[e.pays][1]
        else:
            bureau = VILLES_DOUANE[e.pays][0]
        dernier_km = int(rng.integers(1, 6))
        mainlevee = e.livre - pd.Timedelta(days=dernier_km)
        arrivee = mainlevee - pd.Timedelta(days=jours)
        depot = arrivee + pd.Timedelta(days=int(min(jours, rng.integers(0, 3))))
        r = {"id_dedouanement": f"DD-{i:06d}", "reference_asn_dn": e.asn_dn, "pays": e.pays, "bureau_douane": bureau,
             "date_arrivee": arrivee.strftime("%Y-%m-%d"), "date_depot_declaration": depot.strftime("%Y-%m-%d"),
             "date_mainlevee": mainlevee.strftime("%Y-%m-%d"),
             "regime": rng.choice(["Exonération ONG", "IM4 – Mise à la consommation", "Admission temporaire"], p=[.7, .25, .05]),
             "inspection_physique": "O" if (long_ or rng.random() < .15) else "N",
             "frais_usd": round(float(rng.gamma(2, 120) + 0.004 * (e.valeur or 0)), 2),
             "commentaire": textes.commentaire_douane(rng, long_)}
        rows.append(r)
    df = pd.DataFrame(rows)
    # défauts : dates incohérentes / manquantes
    idx = df.sample(30, random_state=4).index
    df.loc[idx, "date_mainlevee"] = (pd.to_datetime(df.loc[idx, "date_arrivee"]) - pd.Timedelta(days=3)).dt.strftime("%Y-%m-%d")
    df.loc[df.sample(25, random_state=5).index, "date_arrivee"] = None
    df.to_csv(config.SOURCES / "dedouanement.csv", index=False, sep=";", encoding="utf-8")
    print(f"  -> dedouanement.csv : {len(df)} lignes")
    return df


# ---------------------------------------------------------------- 10. incidents (CSV)
CAUSE_MAP = {"douane": "Douane", "transport": "Transport", "météo": "Météo", "documentation": "Documentation",
             "fournisseur": "Fournisseur"}


def gen_incidents(rng, exp):
    rows, n = [], 0
    for e in exp.itertuples():
        if pd.isna(e.livre):
            continue
        late = isinstance(e.cause_retard, str)
        k = rng.poisson((0.30 + (1.6 if late else 0)) * config.ECHELLE)
        for _ in range(k):
            n += 1
            if late and rng.random() < .7:
                cause = CAUSE_MAP.get(e.cause_retard, "Transport")
            else:
                cause = rng.choice(list(textes.INCIDENTS), p=[.14, .2, .08, .14, .1, .14, .1, .1])
            d = e.livre - pd.Timedelta(days=int(rng.integers(1, 20)))
            gravite = rng.choice(["mineure", "majeure", "critique"], p=[.6, .3, .1] if late else [.8, .17, .03])
            pz = P_SCMS[e.pays]
            d = d + pd.Timedelta(minutes=int(rng.integers(0, 24 * 60)))
            rows.append({"id_incident": f"INC-{n:06d}", "date_incident": d.strftime("%d/%m/%Y %H:%M"),
                         "reference_asn_dn": e.asn_dn, "pays": e.pays, "mode_transport": e.mode,
                         "lieu": rng.choice([pz[4], "Hub de transit", "Entrepôt du transitaire", "Frontière"]),
                         "gravite": gravite, "retard_heures": int(rng.gamma(1.5, 30 if gravite != "mineure" else 8)),
                         "cout_estime_usd": round(float(rng.gamma(1.3, 900 if gravite == "critique" else 250)), 2),
                         "description": textes.incident(rng, cause, pz[4], e.vendeur), "cause_reelle": cause})
    df = pd.DataFrame(rows)
    df.to_csv(config.VERITE / "incidents_causes.csv", index=False, columns=["id_incident", "cause_reelle"])
    # 35 % des incidents n'ont pas de cause déclarée (à prédire par le NLP)
    df["cause_declaree"] = np.where(rng.random(len(df)) < .35, None, df["cause_reelle"])
    # erreurs de saisie humaines : 5 % des causes déclarées sont fausses
    err = df["cause_declaree"].notna() & (rng.random(len(df)) < .05)
    df.loc[err, "cause_declaree"] = rng.choice(list(textes.INCIDENTS), err.sum())
    df.loc[df.sample(15, random_state=6).index, "description"] = None
    df.drop(columns="cause_reelle").to_csv(config.SOURCES / "incidents_transport.csv", index=False, encoding="utf-8")
    print(f"  -> incidents_transport.csv : {len(df)} lignes")
    return df


# ---------------------------------------------------------------- 13. suivi des conteneurs (JSON mensuels)
def gen_conteneurs(rng, exp, douane):
    out = config.SOURCES / "conteneurs"
    out.mkdir(exist_ok=True)
    for f in out.glob("*.json"):
        f.unlink()
    arr = douane.set_index("reference_asn_dn")["date_arrivee"].to_dict()
    pas_h = {"Air": .5, "Air Charter": .5, "Truck": 1.0, "Ocean": 3.0}
    vitesse = {"Air": 650 * 24 / 3, "Air Charter": 650 * 24 / 2, "Truck": 450, "Ocean": 550}
    origine_coords = {f[0]: ORIGINES[f[1]][1:3] for f in FOURNISSEURS}
    par_mois, n = {}, 0
    for e in exp.itertuples():
        a = arr.get(e.asn_dn)
        if a is None or pd.isna(a):
            continue
        arrivee = pd.Timestamp(a) + pd.Timedelta(hours=int(rng.integers(6, 20)))
        transit_j = max(0.5, (e.distance_km or 3000) / vitesse[e.mode])
        depart = arrivee - pd.Timedelta(days=transit_j)
        if e.vendeur == "SCMS from RDC":
            pz = P_SCMS[e.pays]
            rd = min(RDC, key=lambda r: haversine(r[4], r[5], pz[5], pz[6]))
            olat, olon = rd[4], rd[5]
        else:
            olat, olon = origine_coords.get(e.vendeur, (19.08, 72.88))
        dlat, dlon = P_SCMS[e.pays][5], P_SCMS[e.pays][6]
        prefixe = {"Ocean": "MSCU", "Truck": "TRK", "Air": "AWB", "Air Charter": "CHR"}[e.mode]
        cont = f"{prefixe}{rng.integers(1_000_000, 9_999_999)}"
        frigo = e.groupe in ("HRDT", "MRDT")
        evts = [("RESERVATION", depart - pd.Timedelta(days=3), olat, olon), ("CHARGEMENT", depart - pd.Timedelta(hours=8), olat, olon),
                ("DEPART", depart, olat, olon)]
        nb = int(transit_j * 24 / pas_h[e.mode] * config.ECHELLE)
        for k in range(1, nb):
            f = k / nb
            evts.append(("POSITION", depart + (arrivee - depart) * f, olat + (dlat - olat) * f + rng.normal(0, .05),
                         olon + (dlon - olon) * f + rng.normal(0, .05)))
        evts += [("ARRIVEE", arrivee, dlat, dlon), ("DECHARGEMENT", arrivee + pd.Timedelta(hours=5), dlat, dlon)]
        if isinstance(e.cause_retard, str) and e.cause_retard == "douane":
            evts.append(("BLOCAGE_DOUANE", arrivee + pd.Timedelta(days=1), dlat, dlon))
        if not pd.isna(e.livre):
            evts.append(("LIVRE", pd.Timestamp(e.livre) + pd.Timedelta(hours=14), dlat, dlon))
        for typ, ts, la, lo in evts:
            n += 1
            ev = {"id_evenement": n, "numero_conteneur": cont, "reference_asn_dn": e.asn_dn, "mode": e.mode,
                  "type_evenement": typ, "horodatage": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "latitude": round(float(la), 4), "longitude": round(float(lo), 4)}
            if frigo:
                ev["temperature_c"] = round(float(rng.normal(6, 1.5) if rng.random() > .01 else rng.uniform(26, 38)), 1)
            if typ == "BLOCAGE_DOUANE":
                ev["commentaire"] = "Conteneur retenu par les douanes en attente de documents."
            par_mois.setdefault(ts.strftime("%Y_%m"), []).append(ev)
    for mois, evs in par_mois.items():
        (out / f"suivi_{mois}.json").write_text(json.dumps({"emetteur": "Plateforme de suivi transitaires",
                                                              "periode": mois, "evenements": evs}), encoding="utf-8")
    print(f"  -> conteneurs : {n} événements dans {len(par_mois)} fichiers JSON")


# ---------------------------------------------------------------- 14. assurance cargo (Excel)
def gen_assurance(rng, exp, inc):
    pol = []
    for i, e in enumerate(exp.itertuples(), start=1):
        if pd.isna(e.livre) or rng.random() < .08:
            continue
        taux = float(rng.choice([0.12, 0.15, 0.18, 0.25, 0.35]))
        val = round(float(e.valeur or 0) * 1.1, 2)
        pol.append({"numero_police": f"POL-{i:06d}", "reference_asn_dn": e.asn_dn,
                    "assureur": rng.choice(["AXA Corporate Solutions", "Allianz Global Corporate", "Chubb Marine", "Zurich Cargo"]),
                    "date_effet": (pd.Timestamp(e.prevu) - pd.Timedelta(days=40)).strftime("%Y-%m-%d"),
                    "valeur_assuree_usd": val, "taux_prime_pct": taux, "prime_usd": round(val * taux / 100, 2),
                    "franchise_usd": int(rng.choice([250, 500, 1000]))})
    polices = pd.DataFrame(pol)
    pmap = polices.set_index("reference_asn_dn")["numero_police"].to_dict()
    vmap = polices.set_index("reference_asn_dn")["valeur_assuree_usd"].to_dict()
    nat = {"Vol": "Vol", "Avarie": "Avarie", "Chaîne du froid": "Température", "Météo": "Mouille", "Transport": "Perte totale"}
    sin = []
    cand = inc[inc["cause_reelle"].isin(nat) & (inc["gravite"] != "mineure")]
    for j, r in enumerate(cand.itertuples(), start=1):
        if r.reference_asn_dn not in pmap or rng.random() < .35:
            continue
        nature = nat[r.cause_reelle]
        if nature == "Perte totale" and rng.random() < .85:
            nature = "Avarie"
        v = vmap[r.reference_asn_dn]
        recl = round(v * (rng.uniform(.6, 1) if nature == "Perte totale" else rng.uniform(.01, .2)), 2)
        statut = rng.choice(["Réglé", "En cours", "Refusé"], p=[.7, .15, .15])
        sin.append({"numero_sinistre": f"SIN-{j:05d}", "numero_police": pmap[r.reference_asn_dn],
                    "id_incident": r.id_incident,
                    "date_declaration": (pd.to_datetime(r.date_incident, dayfirst=True) + pd.Timedelta(days=int(rng.integers(1, 20)))).strftime("%Y-%m-%d"),
                    "nature": nature, "montant_reclame_usd": recl,
                    "montant_indemnise_usd": round(recl * rng.uniform(.5, .95), 2) if statut == "Réglé" else 0.0,
                    "statut": statut, "description": textes.description_sinistre(rng, nature)})
    with pd.ExcelWriter(config.SOURCES / "assurance_cargo.xlsx", engine="openpyxl") as w:
        polices.to_excel(w, sheet_name="Polices", index=False)
        pd.DataFrame(sin).to_excel(w, sheet_name="Sinistres", index=False)
    print(f"  -> assurance_cargo.xlsx : {len(polices)} polices, {len(sin)} sinistres")


def generer(rng):
    df, exp = lire_expeditions()
    gen_fournisseurs(rng)
    gen_entrepots(rng, exp)
    gen_tarifs(rng)
    gen_lpi(rng)
    gen_contrats(rng)
    douane = gen_douane(rng, exp)
    inc = gen_incidents(rng, exp)
    gen_conteneurs(rng, exp, douane)
    gen_assurance(rng, exp, inc)
