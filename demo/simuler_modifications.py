"""Simule une journée d'activité dans les systèmes sources : nouvelles lignes, lignes modifiées, lignes supprimées.

  python -m demo.simuler_modifications            # modifie les sources en place
  python -m demo.simuler_modifications --depot    # dépose en plus un nouveau fichier d'incidents dans data/depot/

Après exécution, `python -m etl.pipeline --mode incremental` doit détecter :
  PostgreSQL fournisseurs : 2 insertions, 4 modifications (dont 3 => nouvelle version SCD2), 1 suppression (CDC)
  MySQL mouvements        : 1 500 insertions, 200 modifications, 100 suppressions (CDC)
  CSV SCMS                : nouvelles lignes (nouveau fichier mensuel), 20 lignes modifiées, 10 supprimées
  CSV dédouanement        : nouveaux dossiers + 15 modifiés
  JSON conteneurs         : 1 nouveau fichier mensuel ; les 119 autres fichiers inchangés ne sont pas relus
"""
import argparse
import json

import numpy as np
import pandas as pd

import config
from etl import bdd
from generateurs import textes


def fournisseurs(rng):
    cx = bdd.pg_connexion(config.PG_DB_SOURCE)
    with cx.cursor() as c:
        # 3 réévaluations -> SCD2 (note et catégorie de risque sont des attributs historisés)
        c.execute("""UPDATE fournisseur SET note_qualite = 2.1, categorie_risque = 'élevé',
                     commentaire_audit = 'Audit de suivi défavorable : retards répétés sur le dernier trimestre.'
                     WHERE code_fournisseur IN ('F0004', 'F0009')""")
        c.execute("UPDATE fournisseur SET certification = 'OMS-PQ', note_qualite = 4.6, categorie_risque = 'faible' "
                  "WHERE code_fournisseur = 'F0011'")
        # 1 modification d'un attribut non historisé -> SCD1 (écrasement)
        c.execute("UPDATE fournisseur SET commentaire_audit = 'Visite de site prévue au prochain semestre.' "
                  "WHERE code_fournisseur = 'F0002'")
        c.execute("""INSERT INTO fournisseur(code_fournisseur, nom, pays_origine_iso3, ville, categorie, certification,
                     note_qualite, categorie_risque, delai_paiement_j, devise_facturation, email_contact, commentaire_audit) VALUES
                     ('F0100', 'LABOREX CAMEROUN', 'ZAF', 'Douala', 'Distributeur', 'SRA', 3.4, 'moyen', 60, 'EUR',
                      'achats@laborex.cm', 'Nouveau distributeur régional, premier audit en cours.'),
                     ('F0101', 'SOPHARMA AFRIQUE', 'IND', 'Mumbai', 'Fabricant', 'OMS-PQ', 4.1, 'faible', 45, 'USD',
                      'export@sopharma.in', 'Fabricant préqualifié OMS, capacité confirmée.')""")
        c.execute("DELETE FROM fournisseur WHERE code_fournisseur = 'F0036'")
    cx.commit(); cx.close()


def mouvements(rng):
    m = bdd.mysql_connexion()
    with m.cursor() as c:
        c.execute("SELECT code_entrepot FROM entrepot")
        codes = [r[0] for r in c.fetchall()]
        lignes = [(rng.choice(codes), f"2015-12-{int(rng.integers(1, 31)):02d}", rng.choice(["ARV", "HRDT"]),
                   rng.choice(["ENTREE", "SORTIE"]), round(float(rng.gamma(1.5, 3)), 2)) for _ in range(1500)]
        c.executemany("INSERT INTO mouvement_stock(code_entrepot, date_mouvement, groupe_produit, type_mouvement, quantite_palettes) "
                      "VALUES (%s,%s,%s,%s,%s)", lignes)
        c.execute("UPDATE mouvement_stock SET quantite_palettes = quantite_palettes + 1 ORDER BY id_mouvement LIMIT 200")
        c.execute("DELETE FROM mouvement_stock WHERE id_mouvement BETWEEN 1000 AND 1099")
    m.close()


def fichiers(rng, depot=False):
    src = config.SOURCES
    f = src / "scms" / "SCMS_Delivery_History_Dataset.csv"
    df = pd.read_csv(f, dtype=str, keep_default_na=False)
    # 20 lignes modifiées (date de livraison corrigée), 10 lignes supprimées
    idx = df.sample(20, random_state=7).index
    df.loc[idx, "Delivered to Client Date"] = df.loc[idx, "Scheduled Delivery Date"]
    df = df.drop(df[~df.index.isin(idx)].sample(10, random_state=8).index)
    df.to_csv(f, index=False)
    # nouvelles expéditions : nouveau fichier mensuel déposé par l'export SCMS
    base = df[df["Country"].isin(["Cameroon", "Nigeria", "Côte d'Ivoire", "South Africa"])].sample(60, random_state=9).copy()
    id0 = int(df["ID"].astype(int).max())
    base["ID"] = [str(id0 + i + 1) for i in range(len(base))]
    base["ASN/DN #"] = [f"ASN-9{i // 2:04d}" for i in range(len(base))]
    prevues = pd.to_datetime("2015-12-01") + pd.to_timedelta(rng.integers(0, 28, len(base)), unit="D")
    base["Scheduled Delivery Date"] = [f"{d.day}-{d:%b}-{d:%y}" for d in prevues]
    livrees = prevues + pd.to_timedelta(rng.choice([0, 0, 0, -2, 5, 12], len(base)), unit="D")
    base["Delivered to Client Date"] = [f"{d.day}-{d:%b}-{d:%y}" for d in livrees]
    base["Delivery Recorded Date"] = base["Delivered to Client Date"]
    base["PO Sent to Vendor Date"] = [f"{d.day}-{d:%b}-{d:%y}" for d in prevues - pd.Timedelta(days=60)]
    base.to_csv(src / "scms" / "SCMS_export_2015_12.csv", index=False)
    # dédouanement : nouveaux dossiers + 15 dossiers modifiés
    dd = pd.read_csv(src / "dedouanement.csv", sep=";", dtype=str, keep_default_na=False)
    i15 = dd[dd["date_mainlevee"] != ""].sample(15, random_state=10).index
    dd.loc[i15, "frais_usd"] = (pd.to_numeric(dd.loc[i15, "frais_usd"]) * 1.2).round(2).astype(str)
    dd.loc[i15, "commentaire"] = "Frais rectifiés après contrôle a posteriori."
    nouv = []
    for k, (asn, pays, liv) in enumerate(base.drop_duplicates("ASN/DN #")[["ASN/DN #", "Country", "Delivered to Client Date"]].values):
        l = pd.to_datetime(liv, format="%d-%b-%y")
        nouv.append({"id_dedouanement": f"DD-9{k:05d}", "reference_asn_dn": asn, "pays": pays, "bureau_douane": dd["bureau_douane"].iloc[k],
                     "date_arrivee": (l - pd.Timedelta(days=8)).strftime("%Y-%m-%d"),
                     "date_depot_declaration": (l - pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
                     "date_mainlevee": (l - pd.Timedelta(days=2)).strftime("%Y-%m-%d"), "regime": "Exonération ONG",
                     "inspection_physique": "N", "frais_usd": "310.5", "commentaire": "RAS."})
    pd.concat([dd, pd.DataFrame(nouv)]).to_csv(src / "dedouanement.csv", sep=";", index=False)
    # suivi des conteneurs : un nouveau fichier mensuel
    evts = [{"id_evenement": 9_000_000 + k, "numero_conteneur": f"AWB{9000 + k // 4}", "reference_asn_dn": n["reference_asn_dn"],
             "mode": "Air", "type_evenement": t, "horodatage": f"{n['date_arrivee']}T{8 + k % 4:02d}:00:00Z",
             "latitude": 4.05, "longitude": 9.70} for k, (n, t) in enumerate((n, t) for n in nouv for t in ["DEPART", "POSITION", "ARRIVEE", "LIVRE"])]
    (src / "conteneurs" / "suivi_2015_12_complement.json").write_text(
        json.dumps({"emetteur": "Plateforme de suivi transitaires", "periode": "2015_12", "evenements": evts}), encoding="utf-8")
    # nouveaux incidents : fichier complémentaire (dans sources/ ou dans le dossier surveillé)
    inc = [{"id_incident": f"INC-9{k:05d}", "date_incident": f"{n['date_arrivee'][8:10]}/{n['date_arrivee'][5:7]}/{n['date_arrivee'][:4]} 10:30",
            "reference_asn_dn": n["reference_asn_dn"], "pays": n["pays"], "mode_transport": "Air", "lieu": "Aéroport",
            "gravite": "majeure", "retard_heures": 48, "cout_estime_usd": 820.0,
            "description": textes.incident(rng, c, "Douala", "LABOREX CAMEROUN"), "cause_declaree": ""}
           for k, (n, c) in enumerate(zip(nouv, rng.choice(["Douane", "Météo", "Transport"], len(nouv))))]
    cible = (config.DEPOT if depot else src) / "incidents_transport_2015_12.csv"
    pd.DataFrame(inc).to_csv(cible, index=False)
    return len(base), len(nouv), len(evts), len(inc), cible


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--depot", action="store_true", help="dépose le fichier d'incidents dans le dossier surveillé")
    a = p.parse_args(argv)
    rng = np.random.default_rng(2015)
    fournisseurs(rng)
    mouvements(rng)
    n = fichiers(rng, a.depot)
    print(f"Sources modifiées : PostgreSQL (+2 / ~4 / -1), MySQL (+1500 / ~200 / -100), SCMS (+{n[0]} / ~20 / -10), "
          f"douane (+{n[1]} / ~15), conteneurs (+{n[2]}), incidents (+{n[3]} -> {n[4]})")


if __name__ == "__main__":
    main()
