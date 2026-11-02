"""Initialisation des dimensions de référence (date, pays, modes, causes, indicateurs) + membres « inconnu » (-1)."""
import pandas as pd

from etl.chargement import upsert
from generateurs.referentiel import PAYS, ORIGINES

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

MODES = [(-1, "Inconnu", "Non renseigné", "Inconnu"), (1, "Air", "Aérien", "Aérien"), (2, "Air Charter", "Aérien affrété", "Aérien"),
         (3, "Truck", "Routier", "Terrestre"), (4, "Ocean", "Maritime", "Maritime")]
CAUSES = [(-1, "Non déclarée", "Inconnue"), (1, "Douane", "Administratif"), (2, "Transport", "Opérationnel"),
          (3, "Météo", "Externe"), (4, "Documentation", "Administratif"), (5, "Fournisseur", "Opérationnel"),
          (6, "Avarie", "Marchandise"), (7, "Chaîne du froid", "Marchandise"), (8, "Vol", "Sûreté")]
INDICATEURS = [
    ("BRENT_USD_BBL", "Prix spot du Brent", "EIA", "USD/baril"),
    *[(f"USD_{d}", f"Taux de change USD → {d}", "BCE / frankfurter", d) for d in ["EUR", "ZAR", "INR", "CNY", "GBP", "CHF", "XAF"]],
    ("WB_NY.GDP.PCAP.CD", "PIB par habitant", "Banque mondiale", "USD"),
    ("WB_SP.POP.TOTL", "Population totale", "Banque mondiale", "habitants"),
    ("WB_PV.EST", "Stabilité politique et absence de violence", "Banque mondiale", "score -2,5 à 2,5"),
    ("WB_RQ.EST", "Qualité de la réglementation", "Banque mondiale", "score -2,5 à 2,5"),
    ("COMTRADE_IMP_3004_USD", "Importations de médicaments (SH 3004)", "UN Comtrade", "USD"),
    ("COMTRADE_IMP_3004_KG", "Importations de médicaments (SH 3004), poids", "UN Comtrade", "kg"),
    ("LPI_SCORE", "Indice de performance logistique (LPI)", "Banque mondiale", "1-5"),
    ("LPI_DOUANE", "LPI – efficacité des douanes", "Banque mondiale", "1-5"),
    ("LPI_INFRASTRUCTURE", "LPI – infrastructures", "Banque mondiale", "1-5"),
    ("LPI_EXPEDITIONS_INTL", "LPI – expéditions internationales", "Banque mondiale", "1-5"),
    ("LPI_COMPETENCE", "LPI – compétence logistique", "Banque mondiale", "1-5"),
    ("LPI_SUIVI", "LPI – suivi et traçabilité", "Banque mondiale", "1-5"),
    ("LPI_PONCTUALITE", "LPI – ponctualité", "Banque mondiale", "1-5"),
]


def initialiser(cx):
    jours = pd.date_range("2000-01-01", "2030-12-31")
    dd = pd.DataFrame({"date_sk": jours.strftime("%Y%m%d").astype(int), "date_jour": jours.date, "annee": jours.year,
                       "semestre": (jours.month - 1) // 6 + 1, "trimestre": jours.quarter, "mois": jours.month,
                       "nom_mois": [MOIS_FR[m - 1] for m in jours.month], "annee_mois": jours.strftime("%Y-%m"),
                       "semaine_iso": jours.isocalendar().week.values, "jour": jours.day, "jour_semaine": jours.dayofweek + 1,
                       "nom_jour": [JOURS_FR[d] for d in jours.dayofweek], "est_weekend": jours.dayofweek >= 5})
    inconnu = pd.DataFrame([{"date_sk": -1, "date_jour": None, "annee": None, "semestre": None, "trimestre": None, "mois": None,
                             "nom_mois": "inconnu", "annee_mois": None, "semaine_iso": None, "jour": None, "jour_semaine": None,
                             "nom_jour": None, "est_weekend": None}])
    dd = pd.concat([inconnu, dd])
    upsert(cx, "dwh.dim_date", dd, "date_sk", list(dd.columns))

    pays = [{"iso3": p[2], "iso2": p[3], "nom_source": p[0], "nom_fr": p[1], "capitale": p[4], "latitude": p[5],
             "longitude": p[6], "region": p[7], "est_destination": True} for p in PAYS]
    for iso, (nom, lat, lon, _) in ORIGINES.items():
        if iso not in {p[2] for p in PAYS}:
            pays.append({"iso3": iso, "iso2": None, "nom_source": None, "nom_fr": nom, "capitale": None, "latitude": lat,
                         "longitude": lon, "region": "Origine fournisseurs", "est_destination": False})
    pays.append({"iso3": "UNK", "iso2": None, "nom_source": None, "nom_fr": "Inconnu", "capitale": None, "latitude": None,
                 "longitude": None, "region": "Inconnu", "est_destination": False})
    dp = pd.DataFrame(pays)
    upsert(cx, "dwh.dim_pays", dp, "iso3", list(dp.columns))
    with cx.cursor() as c:
        c.execute("INSERT INTO dwh.dim_pays(pays_sk, iso3, nom_fr) VALUES (-1, 'N/A', 'Non renseigné') ON CONFLICT DO NOTHING")
        c.executemany("INSERT INTO dwh.dim_mode_transport VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", MODES)
        c.executemany("INSERT INTO dwh.dim_cause_incident VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", CAUSES)
        c.executemany("""INSERT INTO dwh.dim_indicateur(code, libelle, source, unite) VALUES (%s,%s,%s,%s)
                         ON CONFLICT (code) DO NOTHING""", INDICATEURS)
        c.execute("""INSERT INTO dwh.dim_fournisseur(fournisseur_sk, code_fournisseur, nom, version, date_debut_validite)
                     VALUES (-1, 'INCONNU', 'Fournisseur inconnu', 1, '1900-01-01') ON CONFLICT DO NOTHING""")
        c.execute("""INSERT INTO dwh.dim_produit(produit_sk, cle_produit, groupe_produit) VALUES (-1, 'INCONNU', 'N/A')
                     ON CONFLICT DO NOTHING""")
        c.execute("""INSERT INTO dwh.dim_entrepot(entrepot_sk, code_entrepot, nom) VALUES (-1, 'DIRECT', 'Livraison directe')
                     ON CONFLICT DO NOTHING""")
        c.execute("INSERT INTO dwh.dim_bureau_douane(bureau_sk, libelle) VALUES (-1, 'Inconnu') ON CONFLICT DO NOTHING")
