"""Génère les 15 sources du projet 19 (paramétrable : ECHELLE=2 python -m generateurs.generer_tout)."""
import shutil
import time
import numpy as np

import config
from etl import bdd
from generateurs import gen_api, gen_scms, gen_derives


def main():
    t0 = time.time()
    rng = np.random.default_rng(config.GRAINE)
    print(f"Génération des sources (échelle = {config.ECHELLE})")
    for d in (config.SOURCES, config.DEPOT, config.ARCHIVE):   # repart d'un état propre (supprime les fichiers de démo)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    bdd.creer_bases()
    brent, _ = gen_api.generer(rng)
    print("  -> instantanés API : EIA, frankfurter, Open-Meteo (34 villes), Banque mondiale (4 indicateurs), Comtrade")
    gen_scms.generer(rng, brent)
    gen_derives.generer(rng)
    print(f"Terminé en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
