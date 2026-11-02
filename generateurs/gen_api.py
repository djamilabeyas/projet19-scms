"""Instantanés de secours des 6 API (format identique aux réponses réelles).

Utilisés par l'ETL quand l'API n'est pas joignable (pas de réseau, clé absente, quota).
- Open-Meteo archive  : https://archive-api.open-meteo.com/v1/archive
- Taux de change      : https://api.frankfurter.app (BCE)
- Prix du pétrole EIA : https://api.eia.gov/v2/petroleum/pri/spt/data (Brent, RBRTE)
- Banque mondiale     : https://api.worldbank.org/v2/country/{iso}/indicator/{code}?format=json
- UN Comtrade         : https://comtradeapi.un.org/data/v1/get/C/A/HS
"""
import json
import numpy as np
import pandas as pd

import config
from generateurs.referentiel import PAYS, DEVISES

JOURS = pd.date_range(config.DATE_DEBUT, config.DATE_FIN, freq="D")
JOURS_OUVRES = pd.bdate_range(config.DATE_DEBUT, config.DATE_FIN)

# Trajectoire mensuelle approximative du Brent (USD/baril) 2006-2015
ANCRES_BRENT = {
    "2006-01": 63, "2006-07": 74, "2007-01": 54, "2007-11": 92, "2008-07": 133, "2008-12": 40,
    "2009-06": 68, "2010-06": 75, "2011-04": 123, "2012-03": 125, "2012-06": 95, "2013-06": 103,
    "2014-06": 112, "2014-12": 62, "2015-05": 64, "2015-12": 38,
}
ANCRES_EURUSD = {
    "2006-01": 1.21, "2007-12": 1.46, "2008-07": 1.58, "2008-11": 1.27, "2009-12": 1.46,
    "2010-06": 1.22, "2011-04": 1.44, "2012-07": 1.23, "2014-05": 1.39, "2015-03": 1.08, "2015-12": 1.09,
}


def _trajectoire(ancres, index, rng, vol):
    s = pd.Series({pd.Timestamp(k + "-15"): v for k, v in ancres.items()})
    s = s.reindex(s.index.union(index)).interpolate("time").reindex(index).bfill().ffill()
    bruit = np.cumsum(rng.normal(0, vol, len(index)))
    bruit = bruit - pd.Series(bruit).rolling(60, min_periods=1).mean().values
    return (s.values * (1 + bruit)).round(4)


def serie_brent(rng):
    return pd.Series(_trajectoire(ANCRES_BRENT, JOURS_OUVRES, rng, 0.012), index=JOURS_OUVRES)


def generer(rng):
    out = config.CACHE_API
    # ---------- 1. Prix du pétrole (EIA v2) ----------
    brent = serie_brent(rng)
    eia = {"response": {"total": len(brent), "dateFormat": "YYYY-MM-DD", "frequency": "daily",
                        "data": [{"period": d.strftime("%Y-%m-%d"), "duoarea": "NA", "product": "EPCBRENT",
                                  "series": "RBRTE", "series-description": "UK Brent Crude Oil Spot Price FOB (Dollars per Barrel)",
                                  "value": float(v), "units": "$/BBL"} for d, v in brent.items()]}}
    (out / "eia_brent.json").write_text(json.dumps(eia), encoding="utf-8")

    # ---------- 2. Taux de change (frankfurter, base USD) ----------
    eurusd = pd.Series(_trajectoire(ANCRES_EURUSD, JOURS_OUVRES, rng, 0.004), index=JOURS_OUVRES)
    base = {"ZAR": 7.5, "INR": 45.0, "CNY": 7.6, "GBP": 0.62, "CHF": 1.1}
    tend = {"ZAR": 0.08, "INR": 0.04, "CNY": -0.025, "GBP": 0.015, "CHF": -0.03}
    rates = {}
    n = len(JOURS_OUVRES)
    t = np.arange(n) / 260
    autres = {}
    for c in base:
        autres[c] = base[c] * np.exp(tend[c] * t + np.cumsum(rng.normal(0, 0.005, n)) * 0.6)
    for i, d in enumerate(JOURS_OUVRES):
        r = {"EUR": round(1 / eurusd.iloc[i], 5)}
        for c in base:
            r[c] = round(float(autres[c][i]), 4)
        rates[d.strftime("%Y-%m-%d")] = r
    fx = {"amount": 1.0, "base": "USD", "start_date": config.DATE_DEBUT, "end_date": config.DATE_FIN, "rates": rates}
    (out / "frankfurter_usd.json").write_text(json.dumps(fx), encoding="utf-8")

    # ---------- 3. Météo (Open-Meteo archive), une réponse par capitale ----------
    meteo_dir = out / "open_meteo"
    meteo_dir.mkdir(exist_ok=True)
    doy = JOURS.dayofyear.values
    for p in PAYS:
        nom, _, iso3, _, ville, lat, lon = p[:7]
        hemi = 1 if lat >= 0 else -1
        tmoy = 30 - abs(lat) * 0.35 + 4 * np.cos(2 * np.pi * (doy - 200 * (hemi > 0) - 20) / 365) * hemi
        tmax = tmoy + rng.normal(0, 1.8, len(JOURS))
        # saisons des pluies : bimodale près de l'équateur, unimodale ailleurs
        if abs(lat) < 8:
            saison = 0.5 + 0.5 * np.sin(4 * np.pi * (doy - 60) / 365)
        else:
            saison = 0.5 + 0.5 * np.sin(2 * np.pi * (doy - 100 - 182 * (hemi < 0)) / 365)
        pluie = np.where(rng.random(len(JOURS)) < 0.15 + 0.45 * saison,
                         rng.gamma(1.4, 6 + 14 * saison), 0.0)
        vent = np.abs(rng.normal(14, 6, len(JOURS)) + 8 * (pluie > 30))
        rep = {"latitude": lat, "longitude": lon, "timezone": "GMT", "daily_units": {
            "time": "iso8601", "temperature_2m_max": "°C", "precipitation_sum": "mm", "wind_speed_10m_max": "km/h"},
            "daily": {"time": [d.strftime("%Y-%m-%d") for d in JOURS],
                      "temperature_2m_max": np.round(tmax, 1).tolist(),
                      "precipitation_sum": np.round(pluie, 1).tolist(),
                      "wind_speed_10m_max": np.round(vent, 1).tolist()}}
        (meteo_dir / f"{iso3}.json").write_text(json.dumps(rep), encoding="utf-8")

    # ---------- 4. Banque mondiale (API v2 : [meta, data]) ----------
    wb = {}
    annees = range(2006, 2016)
    for p in PAYS:
        nom, nom_fr, iso3, iso2 = p[:4]
        pv = p[10]
        pib0 = float(np.clip(rng.lognormal(7.0, 0.7), 300, 8000))
        pop0 = float(rng.uniform(0.8, 60) * 1e6) if iso3 not in ("NGA", "PAK", "ETH", "VNM", "COD") else float(rng.uniform(60, 180) * 1e6)
        for code, nomind in [("NY.GDP.PCAP.CD", "GDP per capita (current US$)"), ("SP.POP.TOTL", "Population, total"),
                             ("PV.EST", "Political Stability and Absence of Violence/Terrorism: Estimate"),
                             ("RQ.EST", "Regulatory Quality: Estimate")]:
            rows = []
            for a in annees:
                k = a - 2006
                if code == "NY.GDP.PCAP.CD":
                    v = pib0 * (1.045 ** k) * rng.normal(1, 0.03)
                elif code == "SP.POP.TOTL":
                    v = pop0 * (1.026 ** k)
                elif code == "PV.EST":
                    v = pv + rng.normal(0, 0.15)
                else:
                    v = pv * 0.5 - 0.3 + rng.normal(0, 0.1)
                rows.append({"indicator": {"id": code, "value": nomind}, "country": {"id": iso2, "value": nom},
                             "countryiso3code": iso3, "date": str(a), "value": round(float(v), 4),
                             "unit": "", "obs_status": "", "decimal": 1})
            wb.setdefault(code, []).extend(rows)
    for code, rows in wb.items():
        meta = {"page": 1, "pages": 1, "per_page": len(rows), "total": len(rows), "sourceid": "2", "lastupdated": "2016-07-01"}
        (out / f"worldbank_{code.replace('.', '_')}.json").write_text(json.dumps([meta, rows]), encoding="utf-8")

    # ---------- 5. UN Comtrade : importations de médicaments (HS 3004) ----------
    data = []
    for p in PAYS:
        nom, nom_fr, iso3 = p[:3]
        v0 = float(rng.lognormal(18.5, 1.0))
        for a in annees:
            data.append({"typeCode": "C", "freqCode": "A", "refPeriodId": int(f"{a}0101"), "refYear": a,
                         "reporterISO": iso3, "reporterDesc": nom, "flowCode": "M", "flowDesc": "Import",
                         "partnerCode": 0, "partnerDesc": "World", "cmdCode": "3004",
                         "cmdDesc": "Medicaments; packaged for retail sale", "primaryValue": round(v0 * 1.07 ** (a - 2006) * rng.normal(1, .06), 2),
                         "netWgt": round(v0 / 25 * rng.normal(1, .1), 1)})
    (out / "comtrade_3004.json").write_text(json.dumps({"elapsedTime": "0.2 secs", "count": len(data), "data": data, "error": ""}),
                                            encoding="utf-8")
    return brent, eurusd
