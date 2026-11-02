"""Source 1 · Supply Chain Shipment Pricing Data (USAID / SCMS) — CSV Kaggle.

Si le vrai fichier Kaggle est présent dans data/kaggle/SCMS_Delivery_History_Dataset.csv, il est
utilisé tel quel. Sinon on produit une réplique synthétique avec les mêmes 33 colonnes, les mêmes
domaines de valeurs et les mêmes défauts de qualité (dates « Pre-PQ Process », poids « See ASN-93
(ID#:1281) », fret « Freight Included in Commodity Cost », etc.) afin que l'ETL soit identique.
"""
import json
import shutil
import numpy as np
import pandas as pd

import config
from generateurs.referentiel import PAYS, FOURNISSEURS, ORIGINES, PRODUITS, POIDS_GROUPES, MODES, INCOTERMS, RDC

COLONNES = ["ID", "Project Code", "PQ #", "PO / SO #", "ASN/DN #", "Country", "Managed By", "Fulfill Via",
            "Vendor INCO Term", "Shipment Mode", "PQ First Sent to Client Date", "PO Sent to Vendor Date",
            "Scheduled Delivery Date", "Delivered to Client Date", "Delivery Recorded Date", "Product Group",
            "Sub Classification", "Vendor", "Item Description", "Molecule/Test Type", "Brand", "Dosage",
            "Dosage Form", "Unit of Measure (Per Pack)", "Line Item Quantity", "Line Item Value", "Pack Price",
            "Unit Price", "Manufacturing Site", "First Line Designation", "Weight (Kilograms)",
            "Freight Cost (USD)", "Line Item Insurance (USD)"]

TARIF_KM = {"Air": 0.00042, "Air Charter": 0.00075, "Truck": 0.00013, "Ocean": 0.000045, "": 0.0004}
DELAI_MODE = {"Air": (40, 95), "Air Charter": (25, 60), "Truck": (30, 75), "Ocean": (95, 160), "": (40, 95)}
SITES = {"IND": ["Aurobindo Unit III, India", "Hetero Unit III Hyderabad IN", "Cipla, Goa, India",
                 "Strides, Bangalore, India.", "Mylan (formerly Matrix) Nashik", "Ranbaxy, Paonta Shahib, India"],
         "ISR": ["Inverness Japan", "Orgenics, Yavne, Israel"], "IRL": ["Trinity Biotech, Plc", "Gilead(Nycomed) Oranienburg DE"],
         "ZAF": ["Aspen-OSD, Port Elizabeth, SA", "Pharmacy Direct, Johannesburg"], "USA": ["ABBVIE (Abbott) Logis. UK",
         "Chembio Diagnostics Sys. Inc."], "CHN": ["Standard Diagnostics, Korea", "Guilin OSD site, No 17, China"],
         "DEU": ["Boehringer Ing., Koropi, GR", "Bio-Rad Laboratories"], "CHE": ["Novartis Pharma AG, Switzerland",
         "MSD, Haarlem, NL"], "BEL": ["ABBVIE Ludwigshafen Germany", "IDA Foundation, Amsterdam"],
         "GBR": ["GSK Mississauga (Canada)", "Remedica, Limassol, Cyprus"], "KEN": ["KAS Medics, Nairobi"]}


def haversine(lat1, lon1, lat2, lon2):
    r = np.pi / 180
    a = np.sin((lat2 - lat1) * r / 2) ** 2 + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin((lon2 - lon1) * r / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def fdate(d):
    return f"{d.day}-{d.strftime('%b')}-{d.strftime('%y')}"


def charger_pluie():
    """Précipitations par pays (ISO3) issues de l'instantané Open-Meteo, pour corréler retards et météo."""
    pluie = {}
    for f in (config.CACHE_API / "open_meteo").glob("*.json"):
        d = json.loads(f.read_text())["daily"]
        pluie[f.stem] = pd.Series(d["precipitation_sum"], index=pd.to_datetime(d["time"]))
    return pluie


def generer(rng, brent: pd.Series):
    dest = config.SOURCES / "scms"
    dest.mkdir(parents=True, exist_ok=True)
    reel = config.DATA / "kaggle" / "SCMS_Delivery_History_Dataset.csv"
    if reel.exists():
        shutil.copy(reel, dest / "SCMS_Delivery_History_Dataset.csv")
        print("  -> fichier Kaggle réel utilisé")
        return

    pluie = charger_pluie()
    pays_noms = [p[0] for p in PAYS]
    pays_w = np.array([p[8] for p in PAYS], float); pays_w /= pays_w.sum()
    P = {p[0]: p for p in PAYS}
    four_hors_rdc = [f for f in FOURNISSEURS if f[0] != "SCMS from RDC"]
    fw = np.array([f[2] for f in four_hors_rdc], float); fw /= fw.sum()
    modes = list(MODES); mw = np.array(list(MODES.values()), float); mw /= mw.sum()
    incos = list(INCOTERMS); iw = np.array(list(INCOTERMS.values()), float); iw /= iw.sum()
    groupes = list(POIDS_GROUPES); gw = np.array(list(POIDS_GROUPES.values()), float); gw /= gw.sum()
    prod_par_groupe = {g: [p for p in PRODUITS if p[0] == g] for g in groupes}
    # facteur prix propre à chaque fournisseur (certains plus chers)
    fact_prix = {f[0]: float(rng.uniform(0.85, 1.25)) for f in FOURNISSEURS}
    # fiabilité latente propre à chaque fournisseur (+ dérive dans le temps) : alimente le score de risque fournisseur
    fiab = {f[0]: float(rng.choice([-0.04, -0.03, -0.01, 0.02, 0.06, 0.12, 0.20])) for f in FOURNISSEURS}
    derive = {f[0]: float(rng.normal(0, 0.012)) for f in FOURNISSEURS}
    fiab["SCMS from RDC"], derive["SCMS from RDC"] = 0.0, 0.0
    pd.DataFrame({"vendeur": list(fiab), "fiabilite": list(fiab.values()), "derive": [derive[k] for k in fiab]}).to_csv(
        config.VERITE / "fournisseurs_fiabilite.csv", index=False)

    n_exp = 7030
    jours_po = pd.date_range("2006-05-01", "2015-08-31", freq="D")
    poids_j = np.linspace(0.4, 1.6, len(jours_po)); poids_j /= poids_j.sum()

    lignes, latents, anomalies = [], [], []
    id_ligne = 0
    asn_n, dn_n = 1, 1
    for e in range(n_exp):
        pays = rng.choice(pays_noms, p=pays_w)
        pz = P[pays]
        rdc = rng.random() < 0.52
        if rdc:
            vendeur, origine = "SCMS from RDC", None
            inco = "N/A - From RDC"
            # RDC le plus proche
            rd = min(RDC, key=lambda r: haversine(r[4], r[5], pz[5], pz[6]))
            olat, olon = rd[4], rd[5]
            asn = f"DN-{dn_n}"; dn_n += 1
        else:
            fz = four_hors_rdc[rng.choice(len(four_hors_rdc), p=fw)]
            vendeur, origine = fz[0], fz[1]
            inco = rng.choice(incos, p=iw)
            olat, olon = ORIGINES[origine][1], ORIGINES[origine][2]
            asn = f"ASN-{asn_n}"; asn_n += 1
        dist = float(haversine(olat, olon, pz[5], pz[6])) + 150
        mode = rng.choice(modes, p=mw)
        if dist < 2500 and rng.random() < 0.65:
            mode = "Truck"
        if dist > 9000 and mode == "Truck":
            mode = "Air"
        d_ref = pd.Timestamp(rng.choice(jours_po, p=poids_j))
        lo, hi = DELAI_MODE[mode]
        prevu = d_ref + pd.Timedelta(days=int(rng.integers(lo, hi)))
        # --- probabilité de retard : LPI, mode, année, pluie avant la date prévue ---
        lpi = pz[9]
        p_ret = (0.06 + 0.10 * (3.2 - lpi) + (0.06 if mode == "Ocean" else 0) - 0.006 * (d_ref.year - 2006)
                 + fiab[vendeur] + derive[vendeur] * (d_ref.year - 2010))
        s_pluie = pluie.get(pz[2])
        pluie7 = float(s_pluie.loc[prevu - pd.Timedelta(days=7):prevu].sum()) if s_pluie is not None else 0
        if pluie7 > 90:
            p_ret += 0.18
        cause = None
        if rng.random() < max(p_ret, 0.02):
            retard = int(np.ceil(rng.gamma(1.6, 12 if mode != "Ocean" else 20)))
            causes = ["douane", "transport", "documentation", "fournisseur", "météo"]
            cw = np.array([0.34, 0.24, 0.16, 0.14 + 3 * max(fiab[vendeur], 0), 0.12 + (0.5 if pluie7 > 90 else 0)])
            cause = rng.choice(causes, p=cw / cw.sum())
        else:
            retard = -int(rng.choice([0, 0, 0, 0, 1, 2, 3, 5, 7, 10, 14, 21]))
        livre = prevu + pd.Timedelta(days=retard)
        enreg = livre + pd.Timedelta(days=int(rng.choice([0, 0, 1, 2, 3, 5, 9])))
        if rdc:
            pq = fdate(d_ref - pd.Timedelta(days=int(rng.integers(20, 120)))) if rng.random() < 0.7 else "Pre-PQ Process"
            po = "N/A - From RDC"
        else:
            pq = fdate(d_ref - pd.Timedelta(days=int(rng.integers(15, 150)))) if rng.random() < 0.85 else "Date Not Captured"
            po = fdate(d_ref) if rng.random() < 0.9 else "Date Not Captured"
            if pq not in ("Date Not Captured",) and po == "Date Not Captured":
                pass
        projet = f"{rng.choice([100, 102, 104, 106, 108, 110, 112, 114, 116])}-{pz[3]}-{rng.choice(['T01', 'L04', 'T30', 'B07', 'L03'])}"
        num_pq = "Pre-PQ Process" if pq == "Pre-PQ Process" else f"FPQ-{rng.integers(1, 16000)}"
        num_po = f"SO-{rng.integers(1, 52000)}" if rdc else f"SCMS-{rng.integers(1, 300000)}"
        managed = "PMO - US" if rng.random() < 0.995 else rng.choice(["South Africa Field Office", "Haiti Field Office", "Ethiopia Field Office"])
        nb_l = int(min(1 + rng.geometric(0.72) - 1, 8))
        groupe = rng.choice(groupes, p=gw)
        id_premier = None
        poids_total = 0.0
        lignes_exp = []
        for k in range(nb_l):
            id_ligne += 1
            pr = prod_par_groupe[groupe][rng.integers(len(prod_par_groupe[groupe]))]
            g, sous, mol, marque, dosage, forme, upp, pu, kgpp = pr
            tendance = 0.97 ** (d_ref.year - 2006)
            prix_pack = round(upp * pu * fact_prix[vendeur] * tendance * rng.normal(1, 0.06), 2)
            if rng.random() < 0.011:  # anomalie de prix / surfacturation injectée
                prix_pack = round(prix_pack * rng.uniform(2.5, 6), 2)
                anomalies.append(id_ligne)
            qte = int(max(1, rng.lognormal(7.4 if g == "ARV" else 6.6, 1.25)))
            valeur = round(qte * prix_pack, 2)
            kg = qte * kgpp * rng.normal(1, 0.08) + 2
            poids_total += kg
            desc = f"{mol} {dosage}, {forme.lower()}, {upp} {'Tabs' if 'Tablet' in forme else 'Tests' if 'Test' in forme else 'ml'}"
            site = rng.choice(SITES.get(origine or "ZAF"))
            lignes_exp.append([id_ligne, projet, num_pq, num_po, asn, pays, managed, "From RDC" if rdc else "Direct Drop",
                               inco, mode, pq, po, fdate(prevu), fdate(livre), fdate(enreg), g, sous, vendeur, desc, mol,
                               marque, dosage, forme, upp, qte, valeur, prix_pack, round(prix_pack / upp, 2), site,
                               "Yes" if (g == "ARV" and rng.random() < 0.7) else "No", None, None, None])
            if id_premier is None:
                id_premier = id_ligne
        # ---- poids et fret au niveau de l'expédition (portés par la 1re ligne) ----
        d_brent = brent.asof(d_ref) if d_ref >= brent.index[0] else brent.iloc[0]
        baf = max(0.0, (d_brent - 60.0) * 0.0015)
        fret = (poids_total * dist * TARIF_KM[mode] + rng.uniform(150, 900)) * (1 + baf) * rng.lognormal(0, 0.18)
        if mode == "Air Charter":
            fret += rng.uniform(8000, 25000)
        mode_poids = rng.random()
        mode_fret = rng.random()
        for k, l in enumerate(lignes_exp):
            if k == 0:
                l[30] = "Weight Captured Separately" if mode_poids < 0.13 else str(int(round(poids_total)))
                if mode_fret < 0.14:
                    l[31] = "Freight Included in Commodity Cost"
                elif mode_fret < 0.16:
                    l[31] = "Invoiced Separately"
                else:
                    l[31] = f"{fret:.2f}"
            else:
                l[30] = f"See {asn} (ID#:{id_premier})" if mode_poids >= 0.13 else "Weight Captured Separately"
                l[31] = f"See {asn} (ID#:{id_premier})" if mode_fret >= 0.16 else "Freight Included in Commodity Cost"
            l[32] = "" if (d_ref.year <= 2007 and rng.random() < 0.6) else round(l[25] * 0.0016 * rng.normal(1, 0.15), 2)
            lignes.append(l)
        latents.append({"asn_dn": asn, "pays": pays, "mode": mode, "date_ref": d_ref.date(), "date_prevue": prevu.date(),
                        "date_livree": livre.date(), "retard_j": retard, "cause_retard": cause, "pluie_7j": round(pluie7, 1),
                        "distance_km": round(dist), "vendeur": vendeur, "poids_kg": round(poids_total), "valeur": sum(x[25] for x in lignes_exp)})

    df = pd.DataFrame(lignes, columns=COLONNES)
    # quelques doublons exacts (contrôle qualité « doublons »)
    df = pd.concat([df, df.sample(12, random_state=1)]).sort_values("ID")
    df.to_csv(dest / "SCMS_Delivery_History_Dataset.csv", index=False, encoding="utf-8")
    pd.DataFrame(latents).to_csv(config.VERITE / "scms_latent.csv", index=False)
    pd.DataFrame({"ID": anomalies}).to_csv(config.VERITE / "anomalies_prix.csv", index=False)
    print(f"  -> SCMS : {len(df)} lignes, {n_exp} expéditions, {len(anomalies)} anomalies de prix injectées")
