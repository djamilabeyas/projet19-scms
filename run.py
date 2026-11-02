"""Point d'entrée unique du projet 19.

  python run.py tout            # crée les bases, génère les 15 sources, chargement complet + ML/NLP
  python run.py generer         # (re)génère les sources (ECHELLE=2 pour doubler le volume)
  python run.py complet         # chargement complet
  python run.py incremental     # chargement incrémental
  python run.py reprise         # reprise sur incident de la dernière exécution en échec
  python run.py ml              # recalcul des modèles ML/NLP seulement
  python run.py simuler         # simule des insertions / modifications / suppressions dans les sources
  python run.py demo            # démonstration complète : complet -> modifications -> incrémental -> panne -> reprise
  python run.py tableau         # lance le tableau de bord (http://localhost:8501)
  python run.py planificateur [--minutes N]   # déclencheur 1 : planification
  python run.py surveillance    # déclencheur 2 : dépôt de fichier dans data/depot
  python run.py ecouteur        # déclencheur 3 : événement PostgreSQL (LISTEN/NOTIFY)
"""
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); return
    cmd, reste = sys.argv[1], sys.argv[2:]
    py = [sys.executable, "-m"]
    table = {
        "generer": [py + ["generateurs.generer_tout"]],
        "complet": [py + ["etl.pipeline", "--mode", "complet"]],
        "incremental": [py + ["etl.pipeline", "--mode", "incremental"]],
        "reprise": [py + ["etl.pipeline", "--reprise"]],
        "ml": [py + ["etl.pipeline", "--sources", "__aucune__"]],
        "simuler": [py + ["demo.simuler_modifications"]],
        "demo": [py + ["demo.demo_incremental"]],
        "tableau": [py + ["streamlit", "run", "tableau_de_bord/app.py"]],
        "planificateur": [py + ["declencheurs.planificateur"]],
        "surveillance": [py + ["declencheurs.surveillance_dossier"]],
        "ecouteur": [py + ["declencheurs.ecouteur_bdd"]],
    }
    table["tout"] = table["generer"] + table["complet"]
    if cmd not in table:
        print(f"Commande inconnue : {cmd}\n{__doc__}"); sys.exit(1)
    for c in table[cmd]:
        r = subprocess.run(c + reste, cwd=RACINE)
        if r.returncode:
            sys.exit(r.returncode)


if __name__ == "__main__":
    main()
