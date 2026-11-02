"""Référentiels partagés par les générateurs (pays, fournisseurs, produits).

Les valeurs (poids des pays, modes, groupes de produits, ordres de grandeur LPI) reprennent
la structure du jeu USAID « Supply Chain Shipment Pricing Data » (SCMS, 2006-2015).
"""

# nom SCMS (anglais), nom FR, ISO3, ISO2, capitale, lat, lon, région, poids, LPI de base, stabilité politique (WB PV.EST)
PAYS = [
    ("South Africa", "Afrique du Sud", "ZAF", "ZA", "Pretoria", -25.75, 28.19, "Afrique australe", 1406, 3.6, -0.1),
    ("Nigeria", "Nigeria", "NGA", "NG", "Abuja", 9.06, 7.49, "Afrique de l'Ouest", 1194, 2.6, -1.9),
    ("Côte d'Ivoire", "Côte d'Ivoire", "CIV", "CI", "Abidjan", 5.36, -4.01, "Afrique de l'Ouest", 1083, 2.7, -1.2),
    ("Uganda", "Ouganda", "UGA", "UG", "Kampala", 0.35, 32.58, "Afrique de l'Est", 779, 2.8, -0.9),
    ("Vietnam", "Viêt Nam", "VNM", "VN", "Hanoï", 21.03, 105.85, "Asie", 688, 3.1, 0.2),
    ("Zambia", "Zambie", "ZMB", "ZM", "Lusaka", -15.39, 28.32, "Afrique australe", 683, 2.4, 0.3),
    ("Haiti", "Haïti", "HTI", "HT", "Port-au-Prince", 18.54, -72.34, "Caraïbes", 655, 2.2, -0.8),
    ("Mozambique", "Mozambique", "MOZ", "MZ", "Maputo", -25.97, 32.57, "Afrique australe", 631, 2.3, 0.0),
    ("Zimbabwe", "Zimbabwe", "ZWE", "ZW", "Harare", -17.83, 31.05, "Afrique australe", 538, 2.2, -0.8),
    ("Tanzania", "Tanzanie", "TZA", "TZ", "Dodoma", -6.16, 35.75, "Afrique de l'Est", 519, 2.6, -0.2),
    ("Rwanda", "Rwanda", "RWA", "RW", "Kigali", -1.95, 30.06, "Afrique de l'Est", 430, 2.6, 0.0),
    ("Congo, DRC", "RD Congo", "COD", "CD", "Kinshasa", -4.32, 15.31, "Afrique centrale", 333, 2.2, -2.1),
    ("Guyana", "Guyana", "GUY", "GY", "Georgetown", 6.80, -58.16, "Amérique du Sud", 237, 2.4, -0.2),
    ("Ethiopia", "Éthiopie", "ETH", "ET", "Addis-Abeba", 9.03, 38.74, "Afrique de l'Est", 216, 2.4, -1.5),
    ("South Sudan", "Soudan du Sud", "SSD", "SS", "Djouba", 4.85, 31.58, "Afrique de l'Est", 164, 1.9, -2.3),
    ("Kenya", "Kenya", "KEN", "KE", "Nairobi", -1.29, 36.82, "Afrique de l'Est", 111, 2.8, -1.2),
    ("Burundi", "Burundi", "BDI", "BI", "Gitega", -3.43, 29.93, "Afrique de l'Est", 98, 2.3, -1.6),
    ("Namibia", "Namibie", "NAM", "NA", "Windhoek", -22.56, 17.08, "Afrique australe", 95, 2.7, 0.8),
    ("Cameroon", "Cameroun", "CMR", "CM", "Douala", 4.05, 9.70, "Afrique centrale", 75, 2.5, -0.6),
    ("Botswana", "Botswana", "BWA", "BW", "Gaborone", -24.65, 25.91, "Afrique australe", 70, 2.8, 1.0),
    ("Ghana", "Ghana", "GHA", "GH", "Accra", 5.60, -0.19, "Afrique de l'Ouest", 58, 2.7, 0.0),
    ("Dominican Republic", "République dominicaine", "DOM", "DO", "Saint-Domingue", 18.49, -69.93, "Caraïbes", 52, 2.6, 0.1),
    ("Sudan", "Soudan", "SDN", "SD", "Khartoum", 15.50, 32.56, "Afrique de l'Est", 46, 2.2, -2.2),
    ("Swaziland", "Eswatini", "SWZ", "SZ", "Mbabane", -26.31, 31.14, "Afrique australe", 35, 2.3, -0.2),
    ("Mali", "Mali", "MLI", "ML", "Bamako", 12.64, -8.00, "Afrique de l'Ouest", 17, 2.3, -1.5),
    ("Guatemala", "Guatemala", "GTM", "GT", "Guatemala", 14.63, -90.51, "Amérique centrale", 15, 2.5, -0.6),
    ("Pakistan", "Pakistan", "PAK", "PK", "Islamabad", 33.68, 73.05, "Asie", 15, 2.5, -2.6),
    ("Malawi", "Malawi", "MWI", "MW", "Lilongwe", -13.96, 33.79, "Afrique australe", 14, 2.5, 0.0),
    ("Benin", "Bénin", "BEN", "BJ", "Cotonou", 6.37, 2.39, "Afrique de l'Ouest", 13, 2.5, 0.2),
    ("Lebanon", "Liban", "LBN", "LB", "Beyrouth", 33.89, 35.50, "Moyen-Orient", 8, 2.7, -1.6),
    ("Angola", "Angola", "AGO", "AO", "Luanda", -8.84, 13.23, "Afrique centrale", 7, 2.2, -0.4),
    ("Liberia", "Liberia", "LBR", "LR", "Monrovia", 6.30, -10.80, "Afrique de l'Ouest", 6, 2.3, -0.5),
    ("Senegal", "Sénégal", "SEN", "SN", "Dakar", 14.69, -17.45, "Afrique de l'Ouest", 6, 2.5, -0.1),
    ("Togo", "Togo", "TGO", "TG", "Lomé", 6.13, 1.22, "Afrique de l'Ouest", 6, 2.4, -0.3),
]

# Pays d'origine des fournisseurs (pour la distance / le fret) : ISO3, lat, lon, devise de facturation
ORIGINES = {
    "IND": ("Inde", 19.08, 72.88, "INR"),
    "ZAF": ("Afrique du Sud", -26.20, 28.05, "ZAR"),
    "USA": ("États-Unis", 40.71, -74.01, "USD"),
    "DEU": ("Allemagne", 50.11, 8.68, "EUR"),
    "CHE": ("Suisse", 47.37, 8.54, "CHF"),
    "CHN": ("Chine", 31.23, 121.47, "CNY"),
    "ISR": ("Israël", 32.08, 34.78, "USD"),
    "IRL": ("Irlande", 53.35, -6.26, "EUR"),
    "BEL": ("Belgique", 51.22, 4.40, "EUR"),
    "GBR": ("Royaume-Uni", 51.51, -0.13, "GBP"),
    "KEN": ("Kenya", -1.29, 36.82, "USD"),
}

# Centres de distribution régionaux SCMS (Regional Distribution Centers)
RDC = [
    ("RDC-ZA", "RDC Johannesburg", "ZAF", "Johannesburg", -26.20, 28.05),
    ("RDC-KE", "RDC Nairobi", "KEN", "Nairobi", -1.29, 36.82),
    ("RDC-GH", "RDC Accra", "GHA", "Accra", 5.60, -0.19),
]

# fournisseur (libellé SCMS), pays d'origine, poids
FOURNISSEURS = [
    ("SCMS from RDC", "ZAF", 5404),
    ("Orgenics, Ltd", "ISR", 754),
    ("S. BUYS WHOLESALER", "ZAF", 715),
    ("Aurobindo Pharma Limited", "IND", 668),
    ("Trinity Biotech, Plc", "IRL", 356),
    ("ABBVIE LOGISTICS (FORMERLY ABBOTT LOGISTICS BV)", "BEL", 347),
    ("PHARMACY DIRECT", "ZAF", 326),
    ("MYLAN LABORATORIES LTD (FORMERLY MATRIX LABORATORIES)", "IND", 154),
    ("HETERO LABS LIMITED", "IND", 137),
    ("CIPLA LIMITED", "IND", 132),
    ("STRIDES ARCOLAB LIMITED", "IND", 98),
    ("RANBAXY Fine Chemicals LTD.", "IND", 97),
    ("ABBOTT LABORATORIES (PUERTO RICO)", "USA", 74),
    ("Standard Diagnostics", "CHN", 71),
    ("IDA FOUNDATION", "BEL", 65),
    ("Gilead Sciences Ireland, Inc.", "IRL", 58),
    ("MICRO LABS LIMITED", "IND", 52),
    ("Inverness Japan", "USA", 45),
    ("Chembio Diagnostics Systems, Inc.", "USA", 44),
    ("BIO-RAD LABORATORIES (FRANCE)", "DEU", 41),
    ("ACCESS BIO, INC.", "USA", 37),
    ("EMCURE PHARMACEUTICALS LTD", "IND", 33),
    ("MERCK SHARP & DOHME IDEA GMBH (FORMALLY MERCK SHARP & DOHME B.V.)", "CHE", 31),
    ("BRISTOL-MYERS SQUIBB", "USA", 29),
    ("GLAXOSMITHKLINE EXPORT LIMITED", "GBR", 27),
    ("ZEPHYR BIOMEDICALS", "IND", 23),
    ("Guilin Pharmaceuticals Company Ltd.", "CHN", 21),
    ("Novartis Pharma AG", "CHE", 19),
    ("BOEHRINGER INGELHEIM INTERNATIONAL GMBH", "DEU", 18),
    ("Remedica Ltd", "GBR", 16),
    ("JSI R&T INSTITUTE, INC.", "USA", 14),
    ("Premier Medical Corporation Ltd.", "IND", 13),
    ("Shanghai Kehua Bio-engineering Co.,Ltd.", "CHN", 12),
    ("KAS MEDICS LIMITED", "KEN", 11),
    ("ARK DIAGNOSTICS", "USA", 10),
    ("Janssen Sciences Ireland UC", "IRL", 9),
]

# groupe, sous-classification, molécule, marque, dosage, forme, unités par conditionnement, prix unitaire USD, poids kg par conditionnement
PRODUITS = [
    ("ARV", "Adult", "Efavirenz", "Generic", "600mg", "Tablet", 30, 0.11, 0.045),
    ("ARV", "Adult", "Lamivudine/Nevirapine/Zidovudine", "Generic", "150/200/300mg", "Tablet", 60, 0.17, 0.090),
    ("ARV", "Adult", "Lamivudine/Zidovudine", "Generic", "150/300mg", "Tablet", 60, 0.12, 0.080),
    ("ARV", "Adult", "Tenofovir Disoproxil Fumarate", "Generic", "300mg", "Tablet", 30, 0.17, 0.050),
    ("ARV", "Adult", "Efavirenz/Lamivudine/Tenofovir Disoproxil Fumarate", "Generic", "600/300/300mg", "Tablet", 30, 0.38, 0.060),
    ("ARV", "Adult", "Lopinavir/Ritonavir", "Kaletra", "200/50mg", "Tablet - FDC", 120, 0.36, 0.140),
    ("ARV", "Adult", "Nevirapine", "Generic", "200mg", "Tablet", 60, 0.04, 0.060),
    ("ARV", "Adult", "Abacavir", "Generic", "300mg", "Tablet", 60, 0.33, 0.070),
    ("ARV", "Adult", "Atazanavir/Ritonavir", "Generic", "300/100mg", "Tablet - FDC", 30, 0.55, 0.050),
    ("ARV", "Pediatric", "Nevirapine", "Generic", "10mg/ml", "Oral suspension", 1, 1.40, 0.300),
    ("ARV", "Pediatric", "Lamivudine/Zidovudine", "Generic", "30/60mg", "Chewable/dispersible tablet", 60, 0.06, 0.060),
    ("ARV", "Pediatric", "Abacavir/Lamivudine", "Generic", "60/30mg", "Tablet", 60, 0.09, 0.060),
    ("ARV", "Pediatric", "Lopinavir/Ritonavir", "Kaletra", "80/20mg/ml", "Oral solution", 1, 18.0, 0.450),
    ("HRDT", "HIV test", "HIV 1/2, Determine Complete HIV Kit", "Determine", "N/A", "Test kit", 100, 0.80, 0.900),
    ("HRDT", "HIV test", "HIV 1/2, Uni-Gold HIV Kit", "Uni-Gold", "N/A", "Test kit", 20, 1.30, 0.500),
    ("HRDT", "HIV test", "HIV 1/2, OraQuick Kit", "OraQuick", "N/A", "Test kit", 100, 3.20, 1.400),
    ("HRDT", "HIV test - Ancillary", "HIV, Lancet & Buffer Kit", "Generic", "N/A", "Test kit - Ancillary", 100, 0.05, 0.300),
    ("ANTM", "Malaria", "Quinine Sulfate", "Generic", "300mg", "Tablet", 1000, 0.03, 0.600),
    ("ACT", "Malaria", "Artemether/Lumefantrine", "Coartem", "20/120mg", "Tablet", 24, 0.04, 0.020),
    ("MRDT", "Malaria", "Malaria Antigen P.f", "SD Bioline", "N/A", "Test kit", 25, 0.45, 0.250),
]

# Poids relatifs des groupes de produits (≈ jeu SCMS : ARV 8550, HRDT 1728, ANTM 22, ACT 16, MRDT 8)
POIDS_GROUPES = {"ARV": 8550, "HRDT": 1728, "ANTM": 22, "ACT": 16, "MRDT": 8}

MODES = {"Air": 6113, "Truck": 2830, "Air Charter": 650, "Ocean": 371, "": 360}
INCOTERMS = {"EXW": 2778, "DDP": 1443, "FCA": 397, "CIP": 275, "DDU": 15, "DAP": 9, "CIF": 3}

# devises fournisseurs suivies via l'API de change (BCE / frankfurter)
DEVISES = ["EUR", "ZAR", "INR", "CNY", "GBP", "CHF"]
PARITE_XAF_EUR = 655.957  # parité fixe FCFA / euro


def dict_pays():
    return {p[0]: p for p in PAYS}
