-- Source 8 · Fournisseurs (PostgreSQL, base src_fournisseurs)
-- Base opérationnelle « achats » : fiche fournisseur, évaluation qualité, audit.
DROP TABLE IF EXISTS fournisseur CASCADE;
DROP TABLE IF EXISTS journal_suppressions CASCADE;

CREATE TABLE fournisseur (
    id_fournisseur     SERIAL PRIMARY KEY,
    code_fournisseur   VARCHAR(12) UNIQUE NOT NULL,
    nom                VARCHAR(120) NOT NULL,          -- libellé identique à la colonne Vendor du jeu SCMS
    pays_origine_iso3  CHAR(3),
    ville              VARCHAR(80),
    categorie          VARCHAR(30),                    -- Fabricant, Grossiste, Distributeur, Fondation, Centre régional
    certification      VARCHAR(30),                    -- OMS-PQ, FDA, SRA, Aucune
    note_qualite       NUMERIC(3,1),                   -- 1 à 5
    categorie_risque   VARCHAR(10),                    -- faible, moyen, élevé
    delai_paiement_j   INTEGER,
    devise_facturation CHAR(3),
    email_contact      VARCHAR(120),
    commentaire_audit  TEXT,                           -- texte libre du dernier audit
    actif              BOOLEAN DEFAULT TRUE,
    created_at         TIMESTAMP DEFAULT now(),
    updated_at         TIMESTAMP DEFAULT now()         -- colonne de filigrane pour l'incrémental
);

-- CDC des suppressions : chaque DELETE est journalisé pour être propagé à l'entrepôt
CREATE TABLE journal_suppressions (
    id            SERIAL PRIMARY KEY,
    table_source  VARCHAR(60),
    cle           VARCHAR(60),
    supprime_le   TIMESTAMP DEFAULT now()
);

CREATE OR REPLACE FUNCTION f_maj_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION f_journal_suppression() RETURNS trigger AS $$
BEGIN
  INSERT INTO journal_suppressions(table_source, cle) VALUES (TG_TABLE_NAME, OLD.code_fournisseur);
  RETURN OLD;
END; $$ LANGUAGE plpgsql;

-- Déclencheur base de données : NOTIFY sur le canal etl_fournisseurs (écouté par declencheurs/ecouteur_bdd.py)
CREATE OR REPLACE FUNCTION f_notifier_etl() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('etl_fournisseurs', json_build_object('operation', TG_OP, 'table', TG_TABLE_NAME,
          'cle', COALESCE(NEW.code_fournisseur, OLD.code_fournisseur), 'horodatage', now())::text);
  RETURN NULL;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_fournisseur_maj BEFORE UPDATE ON fournisseur FOR EACH ROW EXECUTE FUNCTION f_maj_updated_at();
CREATE TRIGGER trg_fournisseur_suppr AFTER DELETE ON fournisseur FOR EACH ROW EXECUTE FUNCTION f_journal_suppression();
CREATE TRIGGER trg_fournisseur_notify AFTER INSERT OR UPDATE OR DELETE ON fournisseur FOR EACH ROW EXECUTE FUNCTION f_notifier_etl();
