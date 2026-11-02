"""DAGs Apache Airflow (alternative à APScheduler) — à copier dans le dossier dags/ d'Airflow.

  scms_etl_quotidien : ETL incrémental chaque nuit à 02:00 (Africa/Douala), puis recalcul ML/NLP et contrôles.
  scms_etl_depot     : capteur de fichier (FileSensor) sur data/depot, toutes les 10 minutes.

Variable Airflow attendue : PROJET19_DIR = chemin absolu du projet (ex. /opt/projet19-scms).
"""
from datetime import datetime, timedelta

import pendulum
from airflow import DAG
from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.sensors.filesystem import FileSensor

PROJET = Variable.get("PROJET19_DIR", default_var="/opt/projet19-scms")
DEFAUT = {"owner": "djamila", "retries": 2, "retry_delay": timedelta(minutes=5)}
TZ = pendulum.timezone("Africa/Douala")

with DAG("scms_etl_quotidien", start_date=datetime(2026, 1, 1, tzinfo=TZ), schedule="0 2 * * *", catchup=False,
         default_args=DEFAUT, tags=["projet19", "etl"], doc_md=__doc__) as dag_quotidien:
    reprise = BashOperator(task_id="reprise_si_echec",
                           bash_command=f"cd {PROJET} && python -m etl.pipeline --reprise --declencheur airflow || true")
    etl = BashOperator(task_id="etl_incremental",
                       bash_command=f"cd {PROJET} && python -m etl.pipeline --mode incremental --declencheur airflow --sans-ml")
    ml = BashOperator(task_id="ml_nlp_batch",
                      bash_command=f"cd {PROJET} && python -m etl.pipeline --mode incremental --declencheur airflow --sources __aucune__")
    reprise >> etl >> ml

with DAG("scms_etl_depot", start_date=datetime(2026, 1, 1, tzinfo=TZ), schedule="*/10 * * * *", catchup=False,
         max_active_runs=1, default_args=DEFAUT, tags=["projet19", "depot"]) as dag_depot:
    capteur = FileSensor(task_id="attendre_fichier", filepath=f"{PROJET}/data/depot", fs_conn_id="fs_default",
                         poke_interval=30, timeout=540, mode="reschedule", soft_fail=True)
    router = BashOperator(task_id="router_et_charger",
                          bash_command=f"cd {PROJET} && python -c \"from declencheurs.surveillance_dossier import traiter; "
                                       f"import config; [traiter(f) for f in config.DEPOT.iterdir() if f.is_file()]\"")
    capteur >> router
