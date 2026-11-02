# Projet 19 · Expéditions internationales et approvisionnement (USAID)

Projet de fin de module **BC05 · FM01, FM02, FM05** (RNCP39765) : processus décisionnels, architecture de données et ETL.
Chaîne complète : **15 sources → staging → entrepôt en constellation → 3 ML + 2 NLP → tableau de bord de 5 pages**,
avec chargement incrémental, reprise sur incident et 3 déclencheurs automatiques.

Le dossier de conception se trouve dans [`docs/dossier_conception.md`](docs/dossier_conception.md) (version Word : `docs/dossier_conception.docx`).

---

## 1. Installation (Windows, macOS ou Linux)

**Prérequis :** Python 3.10 ou plus récent, et Docker Desktop (le plus simple). Sans Docker, il faut installer
PostgreSQL 14+ et MySQL/MariaDB à la main.

```bash
# 1. Bases de données (PostgreSQL 16 + MariaDB 10.11)
docker compose up -d

# 2. Environnement Python
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux : source .venv/bin/activate)
pip install -r requirements.txt
python -m spacy download fr_core_news_sm

# 3. Configuration (les valeurs par défaut correspondent au docker-compose)
copy .env.example .env            # macOS/Linux : cp .env.example .env

# 4. Tout construire : sources (≈ 1,2 M lignes) + chargement complet + ML/NLP (≈ 2 min)
python run.py tout

# 5. Tableau de bord -> http://localhost:8501
python run.py tableau
```

### Données publiques réelles (facultatif)

- **Kaggle** : télécharger *Supply Chain Shipment Pricing Data* et placer `SCMS_Delivery_History_Dataset.csv` dans
  `data/kaggle/`, puis relancer `python run.py tout`. Les autres sources générées se recalent alors sur les vraies expéditions.
- **API** : Open-Meteo, frankfurter (BCE) et Banque mondiale ne demandent pas de clé. EIA et UN Comtrade demandent une clé
  gratuite, à renseigner dans `.env`. Sans réseau ou sans clé, l'ETL bascule automatiquement sur les instantanés de
  `data/api_cache/`. On peut aussi forcer ce mode avec `OFFLINE=1`.

## 2. Commandes

| Commande | Rôle |
|---|---|
| `python run.py tout` | crée les bases, génère les 15 sources, premier chargement complet + ML/NLP |
| `python run.py generer` | régénère les sources (`ECHELLE=3` dans `.env` pour ≈ 3,4 M lignes) |
| `python run.py complet` / `incremental` | chargement complet / incrémental |
| `python run.py reprise` | reprise sur incident à partir de l'étape en échec |
| `python run.py simuler` | insertions, modifications et suppressions dans les sources |
| `python run.py demo` | **scénario de soutenance** (voir § 4) |
| `python run.py ml` | recalcul des 5 modèles uniquement |
| `python run.py tableau` | tableau de bord Streamlit |
| `python run.py planificateur [--minutes 1]` | déclencheur 1 : planification |
| `python run.py surveillance` | déclencheur 2 : dépôt de fichier dans `data/depot/` |
| `python run.py ecouteur` | déclencheur 3 : événement PostgreSQL (trigger + LISTEN/NOTIFY) |

## 3. Correspondance avec l'énoncé

| Exigence | Réalisation | Où |
|---|---|---|
| ≥ 15 sources, ≥ 4 formats | 15 sources, 6 formats (CSV, Excel, JSON/API, XML, PostgreSQL, MySQL) | `generateurs/`, `etl/extraction.py` |
| ≥ 1 million de lignes, paramétrable | ≈ 1,2 M à l'échelle 1, paramètre `ECHELLE` | `config.py` |
| Entrepôt modélisé, étoile/constellation, dimension date, SCD2 | constellation de 11 faits et 10 dimensions, `dim_date` à rôles multiples, `dim_fournisseur` en SCD2 | `sql/entrepot_ddl.sql` |
| Staging, qualité, rejets journalisés | `staging.stg_*`, 5 familles de règles, `etl.rejet` (JSONB) | `etl/sources.py`, `etl/pipeline.py` |
| Erreurs, reprise, journal des exécutions | transaction par étape, `--reprise`, verrou, `etl.journal_execution` / `journal_etape` | `etl/pipeline.py`, `etl/journal.py` |
| ≥ 2 déclenchements automatiques | 3 : planification (APScheduler / cron / Airflow), dépôt de fichier, trigger BDD | `declencheurs/` |
| Incrémental (filigrane, CDC, hachage) + démo I/U/D | les 3 mécanismes, démo scriptée | `etl/delta.py`, `demo/` |
| 25 indicateurs sur 5 pages | numérotés #1 à #25 dans le tableau de bord | `tableau_de_bord/vues/` |
| 3 ML + 2 NLP avec métriques, batch planifié | étape `ml_batch` → schéma `ml` | `ml/` |
| Textes libres | contrats, incidents, douane, sinistres, audits | `generateurs/textes.py` |
| 5 pages, filtres communs, navigation, actualité | Streamlit : barre latérale + date du dernier chargement | `tableau_de_bord/app.py` |

## 4. Scénario de démonstration (soutenance, ≈ 10 min)

1. `python run.py demo` affiche successivement :
   - le chargement complet (≈ 1,17 M lignes, 147 rejets) ;
   - les modifications des sources ;
   - un incrémental (≈ 1 700 I / 240 U / 110 D, nouvelles versions SCD2) ;
   - un incrémental sans changement (0/0/0) ;
   - une panne simulée suivie de sa reprise.
2. Dans un 2e terminal, lancer `python run.py surveillance`, puis copier un fichier `incidents_transport_*.csv` dans
   `data/depot/` : l'ETL se lance tout seul.
3. Dans un 3e terminal, lancer `python run.py ecouteur`, puis modifier un fournisseur dans PostgreSQL (Adminer :
   http://localhost:8080) : l'ETL se déclenche en quelques secondes et la dimension SCD2 crée une version.
4. Ouvrir le tableau de bord : la date du dernier chargement et son déclencheur ont changé. Faire le tour des 5 pages
   et des encadrés ML/NLP, puis tester le simulateur de coût sur la page Expéditions.

## 5. Arborescence

```
config.py            configuration (.env)
run.py               point d'entrée
generateurs/         génération des sources (référentiels, SCMS, API, dérivées, textes FR)
etl/                 extraction, qualité, delta (hachages), chargement, SCD2, orchestrateur, journal
sql/                 DDL des sources (triggers CDC/NOTIFY), DDL de l'entrepôt, vues de restitution
ml/                  batch ML (régression, risque fournisseur, anomalies) et NLP (contrats, incidents)
declencheurs/        planificateur, surveillance de dossier, écouteur PostgreSQL, DAG Airflow, crontab
demo/                simulation de modifications et scénario incrémental / reprise
tableau_de_bord/     application Streamlit (5 pages)
docs/                dossier de conception, diagrammes, captures d'écran
data/                sources, instantanés d'API, dépôt, archive, modèles, journaux (non versionné)
```
