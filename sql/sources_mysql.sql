-- Source 12 · Entrepôts régionaux (MySQL / MariaDB, base src_entrepots)
DROP TABLE IF EXISTS mouvement_stock;
DROP TABLE IF EXISTS entrepot;
DROP TABLE IF EXISTS journal_suppressions;

CREATE TABLE entrepot (
    code_entrepot      VARCHAR(12) PRIMARY KEY,
    nom                VARCHAR(100) NOT NULL,
    type_entrepot      VARCHAR(40),          -- Centre de distribution régional, Magasin central national
    pays_iso3          CHAR(3),
    ville              VARCHAR(80),
    latitude           DECIMAL(9,5),
    longitude          DECIMAL(9,5),
    capacite_palettes  INT,
    surface_m2         INT,
    temperature_controlee TINYINT(1),
    gestionnaire       VARCHAR(80),
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE mouvement_stock (
    id_mouvement       BIGINT AUTO_INCREMENT PRIMARY KEY,
    code_entrepot      VARCHAR(12) NOT NULL,
    date_mouvement     DATE NOT NULL,
    groupe_produit     VARCHAR(10),
    type_mouvement     VARCHAR(12),          -- ENTREE, SORTIE, TRANSFERT, AJUSTEMENT
    quantite_palettes  DECIMAL(10,2),
    reference_asn_dn   VARCHAR(20),
    commentaire        VARCHAR(255),
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_maj (updated_at),
    CONSTRAINT fk_mvt_entrepot FOREIGN KEY (code_entrepot) REFERENCES entrepot(code_entrepot)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE journal_suppressions (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    table_source  VARCHAR(60),
    cle           VARCHAR(60),
    supprime_le   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TRIGGER trg_mvt_suppr AFTER DELETE ON mouvement_stock FOR EACH ROW
  INSERT INTO journal_suppressions(table_source, cle) VALUES ('mouvement_stock', OLD.id_mouvement);

CREATE TRIGGER trg_entrepot_suppr AFTER DELETE ON entrepot FOR EACH ROW
  INSERT INTO journal_suppressions(table_source, cle) VALUES ('entrepot', OLD.code_entrepot);
