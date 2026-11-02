"""Générateurs de textes libres réalistes en français (incidents, contrats, douane, sinistres, audits)."""
import numpy as np

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
NOMBRES = {7: "sept", 10: "dix", 14: "quatorze", 15: "quinze", 20: "vingt", 21: "vingt et un", 30: "trente",
           45: "quarante-cinq", 60: "soixante", 90: "quatre-vingt-dix", 120: "cent vingt"}

# ------------------------------------------------------------------ incidents
INCIDENTS = {
    "Douane": [
        "Marchandise bloquée en douane à {lieu} : {doc_douane} manquant, mainlevée en attente.",
        "Contrôle physique ordonné par le service des douanes de {lieu}, conteneur immobilisé {h} heures.",
        "Retard de dédouanement à {lieu}, la déclaration a été rejetée pour erreur de code SH.",
        "Les douanes de {lieu} exigent l'attestation d'exonération ; dossier transmis au ministère, colis en attente.",
        "Customs hold at {lieu}: exemption letter not accepted, awaiting clearance.",
        "Inspection douanière prolongée, scanner en panne au poste de {lieu}. Libération prévue sous {j} jours.",
    ],
    "Transport": [
        "Panne du camion sur l'axe {axe}, transbordement nécessaire. Retard estimé à {h} heures.",
        "Vol annulé au départ de {hub}, la palette a été reprogrammée sur le vol suivant.",
        "Congestion portuaire à {lieu}, le navire attend un poste à quai depuis {j} jours.",
        "Le transporteur n'a pas respecté le créneau de chargement, enlèvement décalé.",
        "Rupture de correspondance à {hub}, fret resté au sol faute de capacité en soute.",
        "Truck broke down near the border, cargo transferred to a second vehicle.",
        "Route impraticable entre {lieu} et l'entrepôt central suite à un accident, déviation de {km} km.",
    ],
    "Météo": [
        "Fortes pluies à {lieu} : route inondée, livraison suspendue pendant {h} heures.",
        "Vol retardé à cause d'un orage violent sur {hub}, aéroport fermé temporairement.",
        "Tempête tropicale annoncée, le port de {lieu} a suspendu les opérations de déchargement.",
        "Pistes boueuses après les averses, le camion est resté embourbé à {km} km de la destination.",
        "Heavy rain and flooding on the {axe} corridor, delivery postponed.",
        "Visibilité réduite (brume sèche / harmattan), atterrissage annulé à {lieu}.",
    ],
    "Documentation": [
        "Le certificat d'origine ne correspond pas à la facture, correction demandée au fournisseur.",
        "Packing list incomplète : numéros de lots absents, réception refusée par le magasin central.",
        "Erreur sur le connaissement (B/L), nom du destinataire incorrect, amendement en cours.",
        "Certificat d'analyse (CoA) non joint à l'expédition, quarantaine du lot en attendant le document.",
        "Invoice and AWB quantities do not match, shipment kept on hold.",
        "Licence d'importation expirée, renouvellement demandé auprès de l'autorité de réglementation pharmaceutique.",
    ],
    "Fournisseur": [
        "Le fournisseur {fournisseur} a livré la marchandise au transitaire avec {j} jours de retard.",
        "Production retardée chez {fournisseur} (rupture de principe actif), date d'enlèvement repoussée.",
        "Quantité expédiée inférieure à la commande : {pct} % du volume seulement, reliquat annoncé.",
        "Le fournisseur n'a pas confirmé la date de mise à disposition, relance effectuée.",
        "Supplier {fournisseur} shipped the wrong pack size, replacement requested.",
    ],
    "Avarie": [
        "Cartons écrasés à la réception, {pct} % des boîtes endommagées, réserves émises sur le bon de livraison.",
        "Palette renversée lors de la manutention à {hub}, emballages déchirés.",
        "Infiltration d'eau dans le conteneur, cartons mouillés et étiquettes illisibles.",
        "Damaged packaging found at the warehouse, photos sent to the insurer.",
    ],
    "Chaîne du froid": [
        "Excursion de température enregistrée par l'enregistreur : {t} °C pendant {h} heures.",
        "Rupture de la chaîne du froid à {hub}, les tests ont été stockés hors zone réfrigérée.",
        "Le data logger indique une température supérieure à 30 °C, lot mis en quarantaine.",
        "Groupe frigorifique du camion en panne, température non conforme à l'arrivée.",
    ],
    "Vol": [
        "Vol de {n} cartons constaté à l'ouverture du conteneur, scellé non conforme.",
        "Effraction dans l'entrepôt de transit de {lieu}, une partie des colis a disparu.",
        "Pilferage detected: {n} cartons missing, seal number does not match the B/L.",
        "Colis manquants à la livraison, suspicion de vol pendant le transport routier.",
    ],
}
DOCS_DOUANE = ["le certificat d'exonération", "la déclaration préalable d'importation", "le visa pharmaceutique",
               "l'autorisation de mise sur le marché"]
AXES = ["Lagos-Abuja", "Abidjan-Bouaké", "Durban-Johannesburg", "Dar es Salaam-Dodoma", "Mombasa-Kampala",
        "Beira-Harare", "Douala-Yaoundé", "Lusaka-Ndola", "Maputo-Matola"]
HUBS = ["Johannesburg", "Addis-Abeba", "Nairobi", "Dubaï", "Paris-CDG", "Bruxelles", "Mumbai", "Accra"]


AMBIGUS = ["Retard constaté à la livraison, en attente d'explications du transitaire.",
           "Expédition non arrivée à la date prévue, le transporteur ne répond pas.",
           "Problème signalé par l'équipe pays, détails à confirmer.",
           "Shipment delayed, root cause under investigation.",
           "Livraison partielle, le reste du lot est attendu la semaine prochaine.",
           "Écart constaté entre le bon de livraison et la marchandise reçue."]


def _remplir(rng, modele, lieu, fournisseur):
    return modele.format(lieu=lieu, h=int(rng.integers(4, 96)), j=int(rng.integers(2, 15)), axe=rng.choice(AXES),
                         hub=rng.choice(HUBS), km=int(rng.integers(20, 300)), fournisseur=fournisseur,
                         pct=int(rng.integers(5, 60)), t=int(rng.integers(26, 41)), n=int(rng.integers(2, 40)),
                         doc_douane=rng.choice(DOCS_DOUANE))


def incident(rng, cause, lieu, fournisseur):
    if rng.random() < 0.12:   # description vague : la cause n'est pas lisible dans le texte
        txt = rng.choice(AMBIGUS)
    else:
        txt = _remplir(rng, rng.choice(INCIDENTS[cause]), lieu, fournisseur)
    if rng.random() < 0.22:   # phrase secondaire d'une autre nature (bruit, distracteur)
        autre = rng.choice([k for k in INCIDENTS if k != cause])
        txt += " Par ailleurs : " + _remplir(rng, rng.choice(INCIDENTS[autre]), lieu, fournisseur).lower()
    # bruit réaliste : complément d'information, abréviations, minuscules
    if rng.random() < 0.35:
        txt += rng.choice([" Client informé.", " Transitaire relancé par téléphone.", " Voir mail du superviseur.",
                           " RAS sur le reste du lot.", " Photos jointes au dossier.", " Escalade au responsable pays."])
    if rng.random() < 0.15:
        txt = txt.lower()
    return txt


# ------------------------------------------------------------------ contrats
def _date_txt(rng, d):
    if rng.random() < 0.5:
        return d.strftime("%d/%m/%Y")
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def _jours_txt(rng, n):
    r = rng.random()
    if n in NOMBRES and r < 0.4:
        return f"{NOMBRES[n]} ({n}) jours"
    if r < 0.7:
        return f"{n} jours calendaires"
    return f"{n} jours"


def _pct_txt(rng, p):
    s = f"{p:.2f}".rstrip("0").rstrip(".")
    return rng.choice([f"{s.replace('.', ',')} %", f"{s} %", f"{s.replace('.', ',')} pour cent"])


def contrat(rng, c):
    """c : dict avec fournisseur, num, date_signature, date_debut, date_fin, incoterm, penalite_pct, unite,
    plafond_pct, delai_livraison_j, delai_paiement_j, force_majeure, montant, devise."""
    art = []
    art.append(f"CONTRAT-CADRE D'APPROVISIONNEMENT N° {c['num']}\nEntre le Programme SCMS (ci-après « l'Acheteur ») "
               f"et la société {c['fournisseur']} (ci-après « le Fournisseur »).")
    art.append(f"Article 1 – Objet. Le présent contrat a pour objet la fourniture de produits de santé "
               f"({c['produits']}) destinés aux programmes nationaux de lutte contre le VIH et le paludisme.")
    art.append(f"Article 2 – Durée. Le contrat prend effet le {_date_txt(rng, c['date_debut'])} et "
               + rng.choice(["expire le ", "arrive à échéance le ", "reste en vigueur jusqu'au "])
               + f"{_date_txt(rng, c['date_fin'])}, sauf résiliation anticipée.")
    art.append(f"Article 3 – Conditions de livraison. Les marchandises sont livrées selon l'Incoterm {c['incoterm']} "
               f"(Incoterms 2010). Le délai de livraison est fixé à {_jours_txt(rng, c['delai_livraison_j'])} "
               f"à compter de la réception du bon de commande.")
    unite = "par jour de retard" if c["unite"] == "jour" else "par semaine de retard"
    formul = rng.choice([
        f"En cas de retard, le Fournisseur sera redevable d'une pénalité de {_pct_txt(rng, c['penalite_pct'])} "
        f"de la valeur de la commande {unite}, plafonnée à {_pct_txt(rng, c['plafond_pct'])} du montant total.",
        f"Tout retard de livraison entraîne l'application de pénalités égales à {_pct_txt(rng, c['penalite_pct'])} "
        f"{unite}, dans la limite de {_pct_txt(rng, c['plafond_pct'])} de la valeur du contrat.",
        f"Des pénalités de retard de {_pct_txt(rng, c['penalite_pct'])} {unite} seront appliquées ; leur montant "
        f"cumulé ne pourra excéder {_pct_txt(rng, c['plafond_pct'])} du prix de la commande concernée.",
    ])
    art.append("Article 4 – Pénalités. " + formul)
    montant = f"{c['montant']:,.0f}".replace(",", " ")
    art.append(f"Article 5 – Paiement. Les factures sont réglées à {_jours_txt(rng, c['delai_paiement_j'])} "
               f"date de facture, en {c['devise']}, par virement bancaire. Montant plafond du contrat : {montant} {c['devise']}.")
    if c["force_majeure"]:
        art.append("Article 6 – Force majeure. Aucune des parties ne sera tenue responsable d'un manquement résultant "
                   "d'un cas de force majeure (catastrophe naturelle, guerre, grève générale, épidémie), à condition "
                   "d'en notifier l'autre partie sous dix (10) jours.")
    art.append("Article 7 – Qualité. Les produits doivent être préqualifiés par l'OMS ou approuvés par une autorité "
               "de réglementation stricte ; la durée de vie résiduelle à la livraison ne peut être inférieure à 75 %.")
    if rng.random() < 0.5:
        art.append("Article 8 – Litiges. Tout différend sera soumis à l'arbitrage de la Chambre de commerce internationale.")
    texte = "\n".join(art)
    # bruit de numérisation (contrats scannés puis passés à l'OCR) sur une partie des documents
    if rng.random() < 0.10:
        texte = texte.replace("pénalité", "penalite").replace("Pénalités", "Penalites").replace("pénalités", "penalites")
    if rng.random() < 0.06:
        texte = texte.replace(" jours", " j.")
    if rng.random() < 0.05:
        texte = texte.replace(" %", "%").replace("%", " pc")
    return texte


# ------------------------------------------------------------------ douane, sinistres, audits
def commentaire_douane(rng, long_):
    if long_:
        return rng.choice(["Déclaration rejetée puis redéposée, pièces complémentaires exigées.",
                           "Inspection physique à 100 %, attente de l'inspecteur.",
                           "Exonération non reconnue par le bureau, intervention du ministère de la Santé.",
                           "Scanner hors service, file d'attente importante au poste frontière.",
                           "Valeur en douane contestée, réévaluation demandée."])
    return rng.choice(["Mainlevée obtenue sans difficulté.", "Circuit vert, pas d'inspection.", "RAS.",
                       "Dossier complet, dédouanement rapide.", "", "Visite documentaire uniquement."])


def description_sinistre(rng, nature):
    base = {
        "Vol": "Disparition de cartons constatée à la livraison ; constat dressé avec le transporteur.",
        "Avarie": "Marchandise endommagée (cartons écrasés ou mouillés), réserves émises à la réception.",
        "Température": "Excursion de température hors plage autorisée, lot déclaré non utilisable par l'assurance qualité.",
        "Perte totale": "Perte totale de l'envoi suite à un accident de la route / incendie dans l'entrepôt de transit.",
        "Mouille": "Infiltration d'eau pendant la traversée maritime, emballages et notices détériorés.",
    }[nature]
    return base + rng.choice(["", " Expertise demandée.", " Dossier transmis au courtier.", " Photos et PV joints."])


def commentaire_audit(rng, note):
    if note >= 4:
        return rng.choice(["Audit satisfaisant, système qualité robuste et traçabilité complète des lots.",
                           "Aucune non-conformité majeure ; délais de livraison respectés sur la période.",
                           "Fournisseur fiable, documentation BPF à jour."])
    if note >= 3:
        return rng.choice(["Quelques écarts mineurs sur la documentation des lots, plan d'actions en cours.",
                           "Retards ponctuels signalés, capacité de production à surveiller.",
                           "Non-conformité mineure sur l'étiquetage, corrigée lors de l'audit de suivi."])
    return rng.choice(["Non-conformités majeures : retards répétés et certificats d'analyse manquants.",
                       "Capacité de production insuffisante, ruptures fréquentes ; mise sous surveillance.",
                       "Audit défavorable, dépendance à un seul site de fabrication et traçabilité faible."])
