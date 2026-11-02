-- =====================================================================
-- Entrepôt de données du projet 19 · Expéditions internationales et approvisionnement (USAID / SCMS)
-- Modèle en CONSTELLATION : 11 tables de faits partageant des dimensions conformes
-- Schémas : staging (zone de transit), dwh (entrepôt), etl (pilotage), ml (résultats ML/NLP)
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS dwh;
CREATE SCHEMA IF NOT EXISTS etl;
CREATE SCHEMA IF NOT EXISTS ml;

-- ------------------------------------------------------------ pilotage ETL
CREATE TABLE IF NOT EXISTS etl.journal_execution (
    id_execution     SERIAL PRIMARY KEY,
    debut            TIMESTAMP NOT NULL DEFAULT now(),
    fin              TIMESTAMP,
    mode             VARCHAR(12) NOT NULL,          -- COMPLET | INCREMENTAL
    declencheur      VARCHAR(20) NOT NULL,          -- manuel | planification | depot_fichier | evenement_bdd | airflow
    detail_declencheur TEXT,
    statut           VARCHAR(10) NOT NULL DEFAULT 'EN_COURS',   -- EN_COURS | SUCCES | ECHEC
    lignes_lues      BIGINT DEFAULT 0,
    lignes_inserees  BIGINT DEFAULT 0,
    lignes_maj       BIGINT DEFAULT 0,
    lignes_supprimees BIGINT DEFAULT 0,
    lignes_rejetees  BIGINT DEFAULT 0,
    reprise_de       INTEGER REFERENCES etl.journal_execution(id_execution),
    message          TEXT
);

CREATE TABLE IF NOT EXISTS etl.journal_etape (
    id_etape         SERIAL PRIMARY KEY,
    id_execution     INTEGER NOT NULL REFERENCES etl.journal_execution(id_execution),
    etape            VARCHAR(40) NOT NULL,
    statut           VARCHAR(10) NOT NULL,          -- EN_COURS | SUCCES | ECHEC | IGNOREE
    debut            TIMESTAMP DEFAULT now(),
    fin              TIMESTAMP,
    lignes_lues      BIGINT DEFAULT 0,
    lignes_inserees  BIGINT DEFAULT 0,
    lignes_maj       BIGINT DEFAULT 0,
    lignes_supprimees BIGINT DEFAULT 0,
    lignes_rejetees  BIGINT DEFAULT 0,
    message          TEXT
);
CREATE INDEX IF NOT EXISTS ix_etape_exec ON etl.journal_etape(id_execution);

CREATE TABLE IF NOT EXISTS etl.rejet (
    id_rejet         BIGSERIAL PRIMARY KEY,
    id_execution     INTEGER REFERENCES etl.journal_execution(id_execution),
    source           VARCHAR(40),
    cle              TEXT,
    regle            VARCHAR(40),                   -- doublon | valeur_manquante | format_invalide | incoherence | reference_inconnue
    motif            TEXT,
    donnees          JSONB,
    date_rejet       TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS etl.filigrane (           -- colonnes de filigrane (watermarks) par source
    source           VARCHAR(40) PRIMARY KEY,
    valeur           TEXT,
    maj_le           TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS etl.empreinte (           -- hachage de chaque ligne chargée (détection I/U/D)
    source           VARCHAR(40),
    cle              TEXT,
    hachage          BIGINT,
    fichier          TEXT,
    PRIMARY KEY (source, cle)
);
CREATE INDEX IF NOT EXISTS ix_empreinte_fichier ON etl.empreinte(source, fichier);

CREATE TABLE IF NOT EXISTS etl.fichier_traite (      -- empreinte des fichiers : un fichier inchangé n'est pas relu
    source           VARCHAR(40),
    chemin           TEXT,
    hachage_fichier  CHAR(32),
    taille           BIGINT,
    traite_le        TIMESTAMP DEFAULT now(),
    PRIMARY KEY (source, chemin)
);

-- ------------------------------------------------------------ dimensions conformes
CREATE TABLE IF NOT EXISTS dwh.dim_date (
    date_sk      INTEGER PRIMARY KEY,                -- AAAAMMJJ ; -1 = date inconnue
    date_jour    DATE,
    annee        SMALLINT, semestre SMALLINT, trimestre SMALLINT, mois SMALLINT,
    nom_mois     VARCHAR(12), annee_mois CHAR(7), semaine_iso SMALLINT,
    jour         SMALLINT, jour_semaine SMALLINT, nom_jour VARCHAR(10), est_weekend BOOLEAN
);

CREATE TABLE IF NOT EXISTS dwh.dim_pays (
    pays_sk      SERIAL PRIMARY KEY,
    iso3         CHAR(3) UNIQUE NOT NULL,
    iso2         CHAR(2),
    nom_source   VARCHAR(60),                       -- libellé du jeu SCMS (anglais)
    nom_fr       VARCHAR(60),
    capitale     VARCHAR(60),
    latitude     NUMERIC(8,4), longitude NUMERIC(8,4),
    region       VARCHAR(40),
    est_destination BOOLEAN
);

CREATE TABLE IF NOT EXISTS dwh.dim_mode_transport (
    mode_sk      SMALLINT PRIMARY KEY,
    code_source  VARCHAR(20) UNIQUE,
    libelle      VARCHAR(30),
    famille      VARCHAR(20)
);

-- Dimension à variation lente de TYPE 2 : l'historique des évaluations fournisseurs est conservé
CREATE TABLE IF NOT EXISTS dwh.dim_fournisseur (
    fournisseur_sk     SERIAL PRIMARY KEY,
    code_fournisseur   VARCHAR(12) NOT NULL,        -- clé naturelle
    nom                VARCHAR(120),
    pays_origine_iso3  CHAR(3),
    ville              VARCHAR(80),
    categorie          VARCHAR(30),
    certification      VARCHAR(30),
    note_qualite       NUMERIC(3,1),
    categorie_risque   VARCHAR(10),
    delai_paiement_j   INTEGER,
    devise_facturation CHAR(3),
    commentaire_audit  TEXT,
    hachage_scd        BIGINT,                      -- hachage des attributs historisés
    version            SMALLINT DEFAULT 1,
    date_debut_validite TIMESTAMP NOT NULL,
    date_fin_validite  TIMESTAMP NOT NULL DEFAULT '9999-12-31',
    est_courant        BOOLEAN NOT NULL DEFAULT TRUE,
    est_supprime_source BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_fourn_code ON dwh.dim_fournisseur(code_fournisseur, est_courant);

CREATE TABLE IF NOT EXISTS dwh.dim_produit (
    produit_sk        SERIAL PRIMARY KEY,
    cle_produit       VARCHAR(250) UNIQUE NOT NULL,
    groupe_produit    VARCHAR(10), sous_classification VARCHAR(40), molecule VARCHAR(120),
    marque            VARCHAR(60), dosage VARCHAR(40), forme VARCHAR(60), unites_par_pack INTEGER
);

CREATE TABLE IF NOT EXISTS dwh.dim_entrepot (
    entrepot_sk       SERIAL PRIMARY KEY,
    code_entrepot     VARCHAR(12) UNIQUE NOT NULL,
    nom VARCHAR(100), type_entrepot VARCHAR(40), pays_iso3 CHAR(3), ville VARCHAR(80),
    latitude NUMERIC(9,5), longitude NUMERIC(9,5), capacite_palettes INTEGER, surface_m2 INTEGER,
    temperature_controlee BOOLEAN, gestionnaire VARCHAR(80), est_supprime_source BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS dwh.dim_contrat (
    contrat_sk        SERIAL PRIMARY KEY,
    id_contrat        VARCHAR(30) UNIQUE NOT NULL,
    code_fournisseur  VARCHAR(12), nom_fournisseur VARCHAR(120),
    date_signature DATE, montant_plafond NUMERIC(16,2), devise CHAR(3), statut VARCHAR(10),
    texte             TEXT
);

CREATE TABLE IF NOT EXISTS dwh.dim_bureau_douane (
    bureau_sk SERIAL PRIMARY KEY, libelle VARCHAR(80) UNIQUE NOT NULL, type_bureau VARCHAR(20), pays_iso3 CHAR(3)
);

CREATE TABLE IF NOT EXISTS dwh.dim_cause_incident (
    cause_sk SMALLINT PRIMARY KEY, libelle VARCHAR(30) UNIQUE, categorie VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS dwh.dim_indicateur (
    indicateur_sk SERIAL PRIMARY KEY, code VARCHAR(40) UNIQUE NOT NULL, libelle VARCHAR(120),
    source VARCHAR(40), unite VARCHAR(20)
);

-- ------------------------------------------------------------ tables de faits
-- F1 · grain : une ligne de commande SCMS (ID)
CREATE TABLE IF NOT EXISTS dwh.fait_ligne_expedition (
    id_ligne            INTEGER PRIMARY KEY,
    asn_dn              VARCHAR(20) NOT NULL,       -- dimension dégénérée : l'expédition
    code_projet         VARCHAR(20), num_pq VARCHAR(20), num_po_so VARCHAR(20),
    date_pq_sk INTEGER, date_po_sk INTEGER, date_reference_sk INTEGER, date_prevue_sk INTEGER,
    date_livraison_sk INTEGER, date_enregistrement_sk INTEGER,
    pays_sk INTEGER REFERENCES dwh.dim_pays, fournisseur_sk INTEGER, produit_sk INTEGER REFERENCES dwh.dim_produit,
    mode_sk SMALLINT REFERENCES dwh.dim_mode_transport, entrepot_sk INTEGER,
    gere_par VARCHAR(40), circuit VARCHAR(20), incoterm VARCHAR(20), site_fabrication VARCHAR(80), premiere_ligne BOOLEAN,
    quantite INTEGER, valeur_usd NUMERIC(14,2), prix_pack_usd NUMERIC(12,2), prix_unitaire_usd NUMERIC(12,4),
    poids_kg NUMERIC(12,2),               -- poids ventilé sur la ligne (au prorata de la valeur)
    fret_usd NUMERIC(14,2),               -- fret ventilé sur la ligne
    assurance_usd NUMERIC(12,2),
    fret_inclus_prix BOOLEAN, poids_non_saisi BOOLEAN,
    delai_livraison_j INTEGER,            -- livraison − date de référence (PO, sinon PQ)
    ecart_contractuel_j INTEGER,          -- livraison − date prévue
    a_temps BOOLEAN,
    delai_reponse_j INTEGER,              -- envoi PO au fournisseur − 1re demande de cotation
    id_execution INTEGER, maj_le TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fle_asn ON dwh.fait_ligne_expedition(asn_dn);

-- F2 · grain : un dossier de dédouanement
CREATE TABLE IF NOT EXISTS dwh.fait_dedouanement (
    id_dedouanement VARCHAR(12) PRIMARY KEY, asn_dn VARCHAR(20), pays_sk INTEGER, bureau_sk INTEGER,
    date_arrivee_sk INTEGER, date_depot_sk INTEGER, date_mainlevee_sk INTEGER, regime VARCHAR(40),
    inspection_physique BOOLEAN, delai_dedouanement_j INTEGER, delai_depot_j INTEGER, frais_usd NUMERIC(12,2),
    commentaire TEXT, id_execution INTEGER, maj_le TIMESTAMP DEFAULT now()
);

-- F3 · grain : un incident de transport
CREATE TABLE IF NOT EXISTS dwh.fait_incident (
    id_incident VARCHAR(12) PRIMARY KEY, asn_dn VARCHAR(20), date_sk INTEGER, horodatage TIMESTAMP, pays_sk INTEGER,
    mode_sk SMALLINT, cause_declaree_sk SMALLINT, gravite VARCHAR(10), lieu VARCHAR(60), retard_heures INTEGER,
    cout_estime_usd NUMERIC(12,2), description TEXT, id_execution INTEGER, maj_le TIMESTAMP DEFAULT now()
);

-- F4 · grain : une police d'assurance cargo (une par expédition)
CREATE TABLE IF NOT EXISTS dwh.fait_police_assurance (
    numero_police VARCHAR(12) PRIMARY KEY, asn_dn VARCHAR(20), date_effet_sk INTEGER, assureur VARCHAR(40),
    valeur_assuree_usd NUMERIC(14,2), taux_prime_pct NUMERIC(6,3), prime_usd NUMERIC(12,2), franchise_usd NUMERIC(10,2),
    id_execution INTEGER, maj_le TIMESTAMP DEFAULT now()
);

-- F5 · grain : un sinistre cargo
CREATE TABLE IF NOT EXISTS dwh.fait_sinistre (
    numero_sinistre VARCHAR(12) PRIMARY KEY, numero_police VARCHAR(12), id_incident VARCHAR(12), asn_dn VARCHAR(20),
    date_declaration_sk INTEGER, nature VARCHAR(20), statut VARCHAR(10), montant_reclame_usd NUMERIC(14,2),
    montant_indemnise_usd NUMERIC(14,2), description TEXT, id_execution INTEGER, maj_le TIMESTAMP DEFAULT now()
);

-- F6 · grain : un événement de suivi de conteneur (≈ 600 000 lignes)
CREATE TABLE IF NOT EXISTS dwh.fait_evenement_conteneur (
    id_evenement BIGINT PRIMARY KEY, numero_conteneur VARCHAR(20), asn_dn VARCHAR(20), date_sk INTEGER,
    horodatage TIMESTAMP, mode_sk SMALLINT, type_evenement VARCHAR(20), latitude NUMERIC(8,4), longitude NUMERIC(8,4),
    temperature_c NUMERIC(5,1), alerte_temperature BOOLEAN, commentaire TEXT, id_execution INTEGER
);
CREATE INDEX IF NOT EXISTS ix_evt_asn ON dwh.fait_evenement_conteneur(asn_dn);

-- F7 · grain : un mouvement de stock dans un entrepôt régional (≈ 350 000 lignes)
CREATE TABLE IF NOT EXISTS dwh.fait_mouvement_stock (
    id_mouvement BIGINT PRIMARY KEY, entrepot_sk INTEGER, date_sk INTEGER, groupe_produit VARCHAR(10),
    type_mouvement VARCHAR(12), quantite_palettes NUMERIC(10,2), asn_dn VARCHAR(20), commentaire TEXT, id_execution INTEGER
);

-- F8 · grain : un tarif de fret (année × origine × destination × mode)
CREATE TABLE IF NOT EXISTS dwh.fait_tarif_fret (
    cle_tarif VARCHAR(40) PRIMARY KEY, annee SMALLINT, origine VARCHAR(10), pays_sk INTEGER, mode_sk SMALLINT,
    tarif_usd_kg NUMERIC(10,3), minimum_usd NUMERIC(10,2), transitaire VARCHAR(40), id_execution INTEGER
);

-- F9 · grain : jour × série de marché (Brent, taux de change)
CREATE TABLE IF NOT EXISTS dwh.fait_marche_quotidien (
    date_sk INTEGER, indicateur_sk INTEGER, valeur NUMERIC(16,6), id_execution INTEGER,
    PRIMARY KEY (date_sk, indicateur_sk)
);

-- F10 · grain : jour × pays (météo de la capitale / ville de livraison)
CREATE TABLE IF NOT EXISTS dwh.fait_meteo_quotidienne (
    date_sk INTEGER, pays_sk INTEGER, temperature_max_c NUMERIC(5,1), precipitations_mm NUMERIC(6,1),
    vent_max_kmh NUMERIC(5,1), fortes_pluies BOOLEAN, id_execution INTEGER, PRIMARY KEY (date_sk, pays_sk)
);

-- F11 · grain : pays × année × indicateur (LPI, Banque mondiale, Comtrade)
CREATE TABLE IF NOT EXISTS dwh.fait_indicateur_pays (
    pays_sk INTEGER, annee SMALLINT, indicateur_sk INTEGER, valeur NUMERIC(20,4), id_execution INTEGER,
    PRIMARY KEY (pays_sk, annee, indicateur_sk)
);

-- ------------------------------------------------------------ résultats ML / NLP (écrits par la tâche batch)
CREATE TABLE IF NOT EXISTS ml.prediction_expedition (
    asn_dn VARCHAR(20) PRIMARY KEY, cout_fret_predit_usd NUMERIC(14,2), delai_predit_j NUMERIC(8,1),
    cout_fret_reel_usd NUMERIC(14,2), delai_reel_j INTEGER, jeu VARCHAR(10), version_modele VARCHAR(20), calcule_le TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ml.score_risque_fournisseur (
    code_fournisseur VARCHAR(12), annee SMALLINT, score_risque NUMERIC(5,4), classe_predite BOOLEAN,
    classe_reelle BOOLEAN, version_modele VARCHAR(20), calcule_le TIMESTAMP, PRIMARY KEY (code_fournisseur, annee)
);
CREATE TABLE IF NOT EXISTS ml.anomalie_prix (
    id_ligne INTEGER PRIMARY KEY, score_anomalie NUMERIC(8,5), est_anomalie BOOLEAN, ecart_mediane_pct NUMERIC(10,2),
    version_modele VARCHAR(20), calcule_le TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ml.clause_contrat (
    id_contrat VARCHAR(30) PRIMARY KEY, penalite_pct NUMERIC(6,3), unite_penalite VARCHAR(10), plafond_pct NUMERIC(6,2),
    delai_livraison_j INTEGER, delai_paiement_j INTEGER, date_debut DATE, date_echeance DATE, incoterm VARCHAR(5),
    force_majeure BOOLEAN, extrait_penalite TEXT, version_modele VARCHAR(20), calcule_le TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ml.classification_incident (
    id_incident VARCHAR(12) PRIMARY KEY, cause_predite VARCHAR(30), probabilite NUMERIC(5,4), cause_declaree VARCHAR(30),
    cause_retenue VARCHAR(30), origine_cause VARCHAR(10), version_modele VARCHAR(20), calcule_le TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ml.metrique_modele (
    id SERIAL PRIMARY KEY, modele VARCHAR(40), metrique VARCHAR(40), valeur NUMERIC(12,4), jeu VARCHAR(20),
    version_modele VARCHAR(20), calcule_le TIMESTAMP DEFAULT now()
);
