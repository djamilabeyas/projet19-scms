-- =====================================================================
-- Couche de restitution : vues utilisées par le tableau de bord (et par Power BI / Metabase si besoin)
-- Recréées à chaque exécution ETL (étape controles_finaux)
-- =====================================================================
DROP MATERIALIZED VIEW IF EXISTS dwh.mv_expedition CASCADE;

-- Une ligne par EXPÉDITION (ASN/DN), enrichie : douane, incidents, assurance, Brent, change, prédictions ML
CREATE MATERIALIZED VIEW dwh.mv_expedition AS
WITH lignes AS (
    SELECT f.asn_dn,
           min(f.pays_sk) pays_sk, min(f.mode_sk) mode_sk, min(f.fournisseur_sk) fournisseur_sk, min(f.entrepot_sk) entrepot_sk,
           min(p.groupe_produit) groupe_produit, min(f.circuit) circuit, min(f.incoterm) incoterm,
           min(NULLIF(f.date_reference_sk, -1)) date_reference_sk, min(NULLIF(f.date_prevue_sk, -1)) date_prevue_sk,
           min(NULLIF(f.date_livraison_sk, -1)) date_livraison_sk,
           count(*) nb_lignes, sum(f.quantite) quantite, sum(f.valeur_usd) valeur_usd, sum(f.poids_kg) poids_kg,
           sum(f.fret_usd) fret_usd, bool_or(f.fret_inclus_prix) fret_inclus_prix, sum(f.assurance_usd) assurance_scms_usd,
           max(f.ecart_contractuel_j) ecart_contractuel_j, max(f.delai_livraison_j) delai_livraison_j,
           max(f.delai_reponse_j) delai_reponse_j
    FROM dwh.fait_ligne_expedition f JOIN dwh.dim_produit p USING (produit_sk)
    GROUP BY f.asn_dn
), inc AS (
    SELECT i.asn_dn, count(*) nb_incidents,
           count(*) FILTER (WHERE COALESCE(ci.cause_retenue, c.libelle) = 'Météo') nb_incidents_meteo,
           count(*) FILTER (WHERE i.gravite IN ('majeure', 'critique')) nb_incidents_graves,
           sum(i.cout_estime_usd) cout_incidents_usd
    FROM dwh.fait_incident i
    LEFT JOIN dwh.dim_cause_incident c ON c.cause_sk = i.cause_declaree_sk
    LEFT JOIN ml.classification_incident ci USING (id_incident)
    GROUP BY i.asn_dn
), brent AS (
    SELECT m.date_sk, m.valeur FROM dwh.fait_marche_quotidien m JOIN dwh.dim_indicateur i USING (indicateur_sk)
    WHERE i.code = 'BRENT_USD_BBL'
), eur AS (
    SELECT m.date_sk, d.annee, m.valeur FROM dwh.fait_marche_quotidien m JOIN dwh.dim_indicateur i USING (indicateur_sk)
    JOIN dwh.dim_date d USING (date_sk) WHERE i.code = 'USD_EUR'
), eur_annuel AS (SELECT annee, avg(valeur) taux_moyen FROM eur GROUP BY annee)
SELECT l.*,
       dr.date_jour date_reference, dp.date_jour date_prevue, dl.date_jour date_livraison,
       COALESCE(dl.annee, dp.annee) annee, COALESCE(dl.annee_mois, dp.annee_mois) annee_mois,
       (l.ecart_contractuel_j <= 0) a_temps,
       d.delai_dedouanement_j, d.inspection_physique, COALESCE(d.frais_usd, 0) frais_douane_usd, d.bureau_sk,
       COALESCE(inc.nb_incidents, 0) nb_incidents, COALESCE(inc.nb_incidents_meteo, 0) nb_incidents_meteo,
       COALESCE(inc.nb_incidents_graves, 0) nb_incidents_graves, COALESCE(inc.cout_incidents_usd, 0) cout_incidents_usd,
       pa.prime_usd, pa.valeur_assuree_usd,
       COALESCE(pa.prime_usd, l.assurance_scms_usd, 0) cout_assurance_usd,
       COALESCE(s.nb_sinistres, 0) nb_sinistres, COALESCE(s.montant_reclame, 0) montant_sinistres_usd,
       COALESCE(s.montant_indemnise, 0) montant_indemnise_usd,
       b.valeur brent_usd,
       GREATEST(0, (b.valeur - 60) * 0.0015) baf_pct,
       COALESCE(l.fret_usd, 0) * GREATEST(0, (b.valeur - 60) * 0.0015) / (1 + GREATEST(0, (b.valeur - 60) * 0.0015)) surcout_carburant_usd,
       COALESCE(l.fret_usd, 0) + COALESCE(pa.prime_usd, l.assurance_scms_usd, 0) + COALESCE(d.frais_usd, 0) cout_total_usd,
       e.valeur taux_usd_eur, ea.taux_moyen taux_budget_usd_eur,
       (COALESCE(l.fret_usd, 0) + COALESCE(pa.prime_usd, l.assurance_scms_usd, 0) + COALESCE(d.frais_usd, 0))
           * (e.valeur - ea.taux_moyen) effet_change_eur,
       pe.cout_fret_predit_usd, pe.delai_predit_j
FROM lignes l
LEFT JOIN dwh.dim_date dr ON dr.date_sk = l.date_reference_sk
LEFT JOIN dwh.dim_date dp ON dp.date_sk = l.date_prevue_sk
LEFT JOIN dwh.dim_date dl ON dl.date_sk = l.date_livraison_sk
LEFT JOIN dwh.fait_dedouanement d ON d.asn_dn = l.asn_dn
LEFT JOIN inc ON inc.asn_dn = l.asn_dn
LEFT JOIN dwh.fait_police_assurance pa ON pa.asn_dn = l.asn_dn
LEFT JOIN (SELECT asn_dn, count(*) nb_sinistres, sum(montant_reclame_usd) montant_reclame,
                  sum(montant_indemnise_usd) montant_indemnise FROM dwh.fait_sinistre GROUP BY asn_dn) s ON s.asn_dn = l.asn_dn
LEFT JOIN LATERAL (SELECT valeur FROM brent WHERE brent.date_sk <= COALESCE(l.date_reference_sk, l.date_prevue_sk)
                   ORDER BY date_sk DESC LIMIT 1) b ON TRUE
LEFT JOIN LATERAL (SELECT valeur FROM eur WHERE eur.date_sk <= COALESCE(l.date_reference_sk, l.date_prevue_sk)
                   ORDER BY date_sk DESC LIMIT 1) e ON TRUE
LEFT JOIN eur_annuel ea ON ea.annee = (COALESCE(l.date_reference_sk, l.date_prevue_sk) / 10000) - 1
LEFT JOIN ml.prediction_expedition pe ON pe.asn_dn = l.asn_dn;

CREATE UNIQUE INDEX ON dwh.mv_expedition(asn_dn);

-- Vue « à plat » avec libellés : base de la plupart des indicateurs
CREATE OR REPLACE VIEW dwh.v_expedition AS
SELECT e.*, p.nom_fr pays, p.iso3, p.region, p.latitude, p.longitude, m.libelle mode_transport,
       f.nom fournisseur, f.code_fournisseur, f.pays_origine_iso3
FROM dwh.mv_expedition e
JOIN dwh.dim_pays p USING (pays_sk)
JOIN dwh.dim_mode_transport m USING (mode_sk)
JOIN dwh.dim_fournisseur f USING (fournisseur_sk);

-- Indice de risque pays (0 = faible, 100 = élevé) : 40 % LPI, 30 % stabilité politique, 30 % délai de dédouanement
CREATE OR REPLACE VIEW dwh.v_risque_pays AS
WITH lpi AS (
    SELECT ip.pays_sk, avg(ip.valeur) lpi FROM dwh.fait_indicateur_pays ip JOIN dwh.dim_indicateur i USING (indicateur_sk)
    WHERE i.code = 'LPI_SCORE' GROUP BY ip.pays_sk
), pv AS (
    SELECT ip.pays_sk, avg(ip.valeur) pv FROM dwh.fait_indicateur_pays ip JOIN dwh.dim_indicateur i USING (indicateur_sk)
    WHERE i.code = 'WB_PV.EST' GROUP BY ip.pays_sk
), dd AS (
    SELECT pays_sk, avg(delai_dedouanement_j) delai FROM dwh.fait_dedouanement GROUP BY pays_sk
)
SELECT p.pays_sk, p.nom_fr pays, p.iso3, p.latitude, p.longitude, lpi.lpi, pv.pv stabilite_politique, dd.delai delai_dedouanement_moyen,
       round((40 * (5 - lpi.lpi) / 4 + 30 * (2.5 - pv.pv) / 5
             + 30 * LEAST(dd.delai / NULLIF((SELECT max(delai) FROM dd), 0), 1))::numeric, 1) indice_risque
FROM dwh.dim_pays p JOIN lpi USING (pays_sk) JOIN pv USING (pays_sk) JOIN dd USING (pays_sk)
WHERE p.est_destination;

-- Performance fournisseur par année
CREATE OR REPLACE VIEW dwh.v_fournisseur_annee AS
SELECT f.code_fournisseur, f.nom fournisseur, e.annee, count(*) nb_expeditions, sum(e.valeur_usd) valeur_usd,
       avg(e.a_temps::int) taux_a_temps, avg(e.ecart_contractuel_j) ecart_moyen_j, avg(e.delai_reponse_j) delai_reponse_j,
       avg((e.a_temps AND e.nb_incidents_graves = 0)::int) taux_conformite, avg((e.nb_incidents > 0)::int) taux_incident
FROM dwh.mv_expedition e JOIN dwh.dim_fournisseur f USING (fournisseur_sk)
GROUP BY 1, 2, 3;

-- Fraîcheur des données : date du dernier chargement réussi
CREATE OR REPLACE VIEW etl.v_fraicheur AS
SELECT max(fin) FILTER (WHERE statut = 'SUCCES') dernier_chargement,
       (SELECT mode FROM etl.journal_execution WHERE statut = 'SUCCES' ORDER BY fin DESC LIMIT 1) dernier_mode,
       (SELECT declencheur FROM etl.journal_execution WHERE statut = 'SUCCES' ORDER BY fin DESC LIMIT 1) dernier_declencheur,
       count(*) nb_executions
FROM etl.journal_execution;
