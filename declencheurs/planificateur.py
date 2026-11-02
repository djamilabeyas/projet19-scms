"""Déclencheur 1 · PLANIFICATION (APScheduler, multiplateforme Windows / Linux / macOS).

  python -m declencheurs.planificateur             # ETL incrémental chaque nuit à 02:00, ML batch le dimanche à 03:00
  python -m declencheurs.planificateur --minutes 2 # démonstration : ETL incrémental toutes les 2 minutes

Alternatives équivalentes fournies : declencheurs/crontab.txt (cron / Planificateur de tâches Windows)
et declencheurs/dags/scms_etl_dag.py (Apache Airflow).
"""
import argparse

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from etl.journal import log


def job_etl():
    from etl.pipeline import executer
    executer("INCREMENTAL", "planification", "APScheduler – ETL incrémental", avec_ml=False)


def job_ml():
    from etl.pipeline import executer
    executer("INCREMENTAL", "planification", "APScheduler – recalcul hebdomadaire ML/NLP", filtre_sources=["__aucune__"])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=None, help="intervalle de démonstration en minutes")
    a = p.parse_args(argv)
    s = BlockingScheduler(timezone="Africa/Douala")
    if a.minutes:
        s.add_job(job_etl, "interval", minutes=a.minutes, id="etl_demo", max_instances=1, coalesce=True)
        log.info(f"Planificateur démarré : ETL incrémental toutes les {a.minutes} min (Ctrl+C pour arrêter)")
    else:
        s.add_job(job_etl, CronTrigger(hour=2, minute=0), id="etl_nuit", max_instances=1, coalesce=True, misfire_grace_time=3600)
        s.add_job(job_ml, CronTrigger(day_of_week="sun", hour=3, minute=0), id="ml_hebdo", max_instances=1)
        log.info("Planificateur démarré : ETL tous les jours à 02:00, ML/NLP le dimanche à 03:00 (Ctrl+C pour arrêter)")
    try:
        s.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Planificateur arrêté.")


if __name__ == "__main__":
    main()
