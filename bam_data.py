
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

from bam_db import save_curve_sqlite, load_latest_curve_sqlite


BAM_TREASURY_URL = (
    "https://www.bkam.ma/Marches/Principaux-indicateurs/Marche-obligataire/"
    "Marche-des-bons-de-tresor/Marche-secondaire/Taux-de-reference-des-bons-du-tresor"
)

BAM_CSV_URL_TEMPLATE = (
    "https://www.bkam.ma/export/blockcsv/2340/"
    "c3367fcefc5f524397748201aee5dab8/"
    "e1d6b9bbf87f86f8ba53e8518e882982"
    "?block=e1d6b9bbf87f86f8ba53e8518e882982&t={ts}"
)

LOCAL_CACHE_DIR = Path.home() / ".streamlit_obligations_maroc_v5"
LOCAL_BAM_CACHE_CSV = LOCAL_CACHE_DIR / "courbe_bam_cache.csv"
LOCAL_BAM_CACHE_META = LOCAL_CACHE_DIR / "courbe_bam_cache_meta.json"
LOCAL_BAM_HISTORY_DIR = LOCAL_CACHE_DIR / "historique_courbes_bam"


DEFAULT_SAMPLE_CURVE = pd.DataFrame(
    {
        "date_echeance": [
            "18/05/2026", "19/10/2026", "15/02/2027", "15/03/2027",
            "20/09/2027", "15/04/2030", "20/10/2031", "18/06/2035",
            "18/07/2039", "14/08/2045", "19/04/2055"
        ],
        "transaction_mdh": [0.0] * 11,
        "taux_moyen_pondere": [
            0.02130, 0.02280, 0.02300, 0.02300, 0.02340, 0.02720,
            0.02910, 0.03100, 0.03440, 0.03680, 0.04010
        ],
        "date_valeur": [
            "05/05/2026", "05/05/2026", "05/05/2026", "05/05/2026",
            "04/05/2026", "04/05/2026", "05/05/2026", "04/05/2026",
            "04/05/2026", "04/05/2026", "04/05/2026"
        ],
        "source": ["Echantillon local"] * 11,
    }
)


def strip_accents(s: str) -> str:
    s = "" if s is None else str(s)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_col(s: str) -> str:
    s = strip_accents(str(s)).lower().strip()
    for ch in ["'", "’", ".", ",", ";", ":", "(", ")", "%", "\n", "\r", "\t", "-"]:
        s = s.replace(ch, " ")
    return "_".join(s.split())


def parse_percent(x: Any) -> float:
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.number)):
        v = float(x)
        return v / 100 if abs(v) > 1 else v
    s = str(x).strip().replace("\xa0", " ").replace("%", "").replace(" ", "").replace(",", ".")
    if s in ["", "-", "nan", "None"]:
        return np.nan
    try:
        v = float(s)
        return v / 100 if abs(v) > 1 else v
    except Exception:
        return np.nan



def parse_percent_series(series: pd.Series) -> pd.Series:
    """
    Conversion robuste d'une colonne de taux en décimal.
    - Si le symbole % est présent, on divise par 100.
    - Si les valeurs numériques sont typiquement supérieures à 20%, on suppose qu'elles sont exprimées en pourcentage.
      Exemple : 2.5 devient 0.025 ; 0.5 devient 0.005.
    - Si les valeurs sont déjà décimales, on les conserve.
    """
    s = series.copy()
    as_str = s.astype(str)
    has_percent = as_str.str.contains("%", na=False).any()

    cleaned = as_str.str.replace("%", "", regex=False)
    cleaned = cleaned.str.replace("\xa0", " ", regex=False).str.replace(" ", "", regex=False)
    cleaned = cleaned.str.replace(",", ".", regex=False)
    numeric = pd.to_numeric(cleaned, errors="coerce")

    if has_percent:
        return numeric / 100.0

    median_abs = numeric.dropna().abs().median()
    if pd.notna(median_abs) and median_abs > 0.20:
        return numeric / 100.0

    return numeric


def parse_number(x: Any) -> float:
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.number)):
        return float(x)
    s = str(x).strip().replace("\xa0", " ").replace(" ", "").replace(",", ".").replace("%", "")
    if s in ["", "-", "nan", "None"]:
        return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan


def parse_date_any(x: Any) -> pd.Timestamp:
    if pd.isna(x):
        return pd.NaT
    if isinstance(x, pd.Timestamp):
        return x
    if isinstance(x, datetime):
        return pd.Timestamp(x.date())
    if isinstance(x, date):
        return pd.Timestamp(x)
    return pd.to_datetime(str(x).strip(), dayfirst=True, errors="coerce")


def normalize_bam_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    raw = df.copy()
    raw.columns = [normalize_col(c) for c in raw.columns]

    col_map = {}
    for c in raw.columns:
        if "echeance" in c or c in ["maturite", "date_maturite"]:
            col_map[c] = "date_echeance"
        elif "date" in c and "valeur" in c:
            col_map[c] = "date_valeur"
        elif "taux" in c and ("moyen" in c or "pondere" in c or "tmp" in c or "reference" in c):
            col_map[c] = "taux_moyen_pondere"
        elif "transaction" in c or "montant" in c:
            col_map[c] = "transaction_mdh"
        elif c in ["date_echeance", "date_valeur", "taux_moyen_pondere", "transaction_mdh"]:
            col_map[c] = c

    raw = raw.rename(columns=col_map)

    if not {"date_echeance", "taux_moyen_pondere", "date_valeur"}.issubset(raw.columns):
        if raw.shape[1] >= 4:
            tmp = raw.iloc[:, :4].copy()
            tmp.columns = ["date_echeance", "transaction_mdh", "taux_moyen_pondere", "date_valeur"]
            raw = tmp

    needed = ["date_echeance", "taux_moyen_pondere", "date_valeur"]
    if any(c not in raw.columns for c in needed):
        return pd.DataFrame()

    if "transaction_mdh" not in raw.columns:
        raw["transaction_mdh"] = np.nan

    out = raw.copy()
    out["date_echeance"] = out["date_echeance"].apply(parse_date_any)
    out["date_valeur"] = out["date_valeur"].apply(parse_date_any)
    out["taux_moyen_pondere"] = parse_percent_series(out["taux_moyen_pondere"])
    out["transaction_mdh"] = out["transaction_mdh"].apply(parse_number)
    out = out.dropna(subset=["date_echeance", "date_valeur", "taux_moyen_pondere"])
    out = out[out["taux_moyen_pondere"].between(-0.05, 0.30)].copy()
    if "source" not in out.columns:
        out["source"] = "BAM / fichier utilisateur"
    return out[["date_echeance", "transaction_mdh", "taux_moyen_pondere", "date_valeur", "source"]].sort_values(
        ["date_valeur", "date_echeance"]
    ).reset_index(drop=True)


def find_dynamic_bam_csv_url(html: str) -> Optional[str]:
    """
    Détecte dynamiquement l'URL d'export CSV BAM depuis la page HTML.
    Évite de dépendre d'un hash hardcodé qui peut changer.
    """
    try:
        # 1) Liens directs dans les href.
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all(["a", "button"]):
            href = a.get("href") or a.get("data-url") or a.get("data-href")
            if href and "export/blockcsv" in href:
                if href.startswith("/"):
                    return "https://www.bkam.ma" + href
                return href

        # 2) Recherche brute dans le HTML / scripts.
        m = re.search(r"[\"']([^\"']*export/blockcsv/[^\"']+)[\"']", html)
        if m:
            url = m.group(1).replace("\\/", "/")
            if url.startswith("/"):
                return "https://www.bkam.ma" + url
            return url
    except Exception:
        pass
    return None


def fetch_bam_curve_online() -> Tuple[pd.DataFrame, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    html_error = ""
    csv_error = ""

    html_text = ""
    dynamic_csv_url = None
    try:
        resp = requests.get(BAM_TREASURY_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        html_text = resp.text
        dynamic_csv_url = find_dynamic_bam_csv_url(html_text)
        tables = pd.read_html(io.StringIO(html_text), decimal=",", thousands=" ")
        best = pd.DataFrame()
        for t in tables:
            norm = normalize_bam_table(t)
            if len(norm) > len(best):
                best = norm
        if not best.empty:
            best["source"] = "BAM HTML"
            return best, "Courbe récupérée depuis la page BAM."
    except Exception as e:
        html_error = str(e)

    try:
        url = dynamic_csv_url or BAM_CSV_URL_TEMPLATE.format(ts=int(time.time()))
        if "{ts}" in url:
            url = url.format(ts=int(time.time()))
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        content = resp.content.decode("utf-8", errors="replace")
        sep = ";" if content.count(";") >= content.count(",") else ","
        df_csv = pd.read_csv(io.StringIO(content), sep=sep, engine="python")
        norm = normalize_bam_table(df_csv)
        if not norm.empty:
            norm["source"] = "BAM CSV"
            return norm, "Courbe récupérée depuis l'export CSV BAM."
    except Exception as e:
        csv_error = str(e)

    sample = normalize_bam_table(DEFAULT_SAMPLE_CURVE)
    return sample, (
        "BAM non récupérable automatiquement pour cette session. "
        f"HTML: {html_error}. CSV: {csv_error}. Utilisation de l'échantillon local."
    )


def save_local_bam_curve(df: pd.DataFrame, message: str) -> None:
    try:
        if df is None or df.empty:
            return
        LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_BAM_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(LOCAL_BAM_CACHE_CSV, index=False, encoding="utf-8-sig")
        today_key = date.today().isoformat()
        history_file = LOCAL_BAM_HISTORY_DIR / f"courbe_bam_{today_key}.csv"
        df.to_csv(history_file, index=False, encoding="utf-8-sig")
        meta = {
            "fetch_date": today_key,
            "fetch_datetime": datetime.now().isoformat(timespec="seconds"),
            "message": message,
            "rows": int(len(df)),
            "history_file": str(history_file),
        }
        LOCAL_BAM_CACHE_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        save_curve_sqlite(df, source=message)
    except Exception:
        pass


def load_local_bam_curve() -> Tuple[pd.DataFrame, Dict[str, Any]]:
    try:
        if not LOCAL_BAM_CACHE_CSV.exists():
            return pd.DataFrame(), {}
        df = pd.read_csv(LOCAL_BAM_CACHE_CSV)
        df = normalize_bam_table(df)
        meta = {}
        if LOCAL_BAM_CACHE_META.exists():
            meta = json.loads(LOCAL_BAM_CACHE_META.read_text(encoding="utf-8"))
        return df, meta
    except Exception:
        return pd.DataFrame(), {}


def get_bam_curve(force_refresh: bool = False) -> Tuple[pd.DataFrame, str, Dict[str, Any]]:
    today_key = date.today().isoformat()
    cached_df, cached_meta = load_local_bam_curve()
    if not force_refresh and not cached_df.empty and cached_meta.get("fetch_date") == today_key:
        return cached_df, "Courbe chargée depuis le cache local du jour.", cached_meta

    df, msg = fetch_bam_curve_online()

    # Si BAM renvoie l'échantillon local, tenter la dernière vraie courbe SQLite.
    try:
        is_sample = (df is not None and not df.empty and "source" in df.columns and df["source"].astype(str).str.contains("Echantillon|Échantillon|sample", case=False, na=False).any())
        if is_sample:
            latest_df, latest_meta = load_latest_curve_sqlite()
            if latest_df is not None and not latest_df.empty:
                return latest_df, "BAM indisponible : dernière courbe locale SQLite utilisée. Date: " + str(latest_meta.get("date_valeur", "-")), latest_meta
    except Exception:
        pass

    save_local_bam_curve(df, msg)
    _, meta = load_local_bam_curve()
    return df, msg, meta


def read_uploaded_curve(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".csv"):
            content = uploaded_file.getvalue().decode("utf-8", errors="replace")
            sep = ";" if content.count(";") >= content.count(",") else ","
            df = pd.read_csv(io.StringIO(content), sep=sep, engine="python")
        else:
            df = pd.read_excel(uploaded_file)
        return normalize_bam_table(df)
    except Exception:
        return pd.DataFrame()


def select_curve_snapshot(
    all_curve: pd.DataFrame,
    curve_reference_date: date,
    mode: str = "last_per_maturity",
    day_count_basis: str = "ACT/365",
    maturity_date_basis: str = "date_valeur",
) -> pd.DataFrame:
    """
    Sélectionne la courbe utilisée.

    maturity_date_basis :
    - "date_valeur" : calcule les tenors depuis la date de valeur BAM de chaque point.
      C'est le comportement le plus fidèle au fichier BAM et évite de perdre des points
      quand la dernière courbe disponible est à J-1.
    - "date_reference" : calcule les tenors depuis curve_reference_date.
      Utile pour backtesting strict, mais peut exclure les maturités très courtes.
    """
    if all_curve is None or all_curve.empty:
        return pd.DataFrame()

    df = all_curve.copy()
    vts = pd.Timestamp(curve_reference_date)
    past = df[df["date_valeur"] <= vts].copy()
    if past.empty:
        past = df.copy()

    if mode == "strict_common_date":
        max_val_date = past["date_valeur"].max()
        curve = past[past["date_valeur"] == max_val_date].copy()
    else:
        curve = past.sort_values(["date_echeance", "date_valeur"]).groupby("date_echeance", as_index=False).tail(1).copy()

    if str(maturity_date_basis).lower().startswith("date_val"):
        base_dates = pd.to_datetime(curve["date_valeur"], errors="coerce")
    else:
        base_dates = pd.Series([vts] * len(curve), index=curve.index)

    curve["days_to_maturity"] = (pd.to_datetime(curve["date_echeance"], errors="coerce") - base_dates).dt.days
    curve = curve[curve["days_to_maturity"] > 0].copy()
    curve["tenor_years"] = curve["days_to_maturity"] / (360.0 if day_count_basis == "ACT/360" else 365.0)

    # Garder un seul point si même échéance/date valeur, mais ne pas supprimer des points
    # uniquement parce que le tenor arrondi est identique.
    curve = curve.sort_values(["tenor_years", "date_echeance", "date_valeur"])
    curve = curve.drop_duplicates(["date_echeance", "date_valeur"], keep="last").reset_index(drop=True)
    return curve


def curve_selection_diagnostics(
    all_curve: pd.DataFrame,
    curve_reference_date: date,
    mode: str = "last_per_maturity",
    maturity_date_basis: str = "date_valeur",
) -> Dict[str, Any]:
    if all_curve is None or all_curve.empty:
        return {
            "lignes_brutes": 0,
            "lignes_passees": 0,
            "points_utilises": 0,
            "exclus_maturite": 0,
            "duplicates_echeance": 0,
            "base_maturite": maturity_date_basis,
        }

    df = all_curve.copy()
    vts = pd.Timestamp(curve_reference_date)
    past = df[df["date_valeur"] <= vts].copy()
    if past.empty:
        past = df.copy()

    if mode == "strict_common_date":
        max_val_date = past["date_valeur"].max()
        pre = past[past["date_valeur"] == max_val_date].copy()
    else:
        pre = past.sort_values(["date_echeance", "date_valeur"]).groupby("date_echeance", as_index=False).tail(1).copy()

    if str(maturity_date_basis).lower().startswith("date_val"):
        base_dates = pd.to_datetime(pre["date_valeur"], errors="coerce")
    else:
        base_dates = pd.Series([vts] * len(pre), index=pre.index)

    tmp = pre.copy()
    tmp["days_to_maturity_diag"] = (pd.to_datetime(tmp["date_echeance"], errors="coerce") - base_dates).dt.days
    exclus = tmp[tmp["days_to_maturity_diag"] <= 0].copy()
    used = select_curve_snapshot(df, curve_reference_date, mode=mode, maturity_date_basis=maturity_date_basis)

    return {
        "lignes_brutes": int(len(df)),
        "lignes_apres_mode": int(len(pre)),
        "points_utilises": int(len(used)),
        "exclus_maturite": int(len(exclus)),
        "duplicates_echeance": int(pre.duplicated(["date_echeance", "date_valeur"]).sum()),
        "base_maturite": maturity_date_basis,
        "lignes_exclues": exclus,
    }

def round_rate_percent_decimals(rate: float, decimals: int = 3) -> float:
    """
    Arrondit un taux décimal au nombre de décimales affichées en pourcentage.

    Exemple :
    0.03221987 = 3.221987% -> 3.222% -> 0.03222
    """
    try:
        if pd.isna(rate):
            return np.nan
        return round(float(rate) * 100.0, decimals) / 100.0
    except Exception:
        return rate


def interpolate_zero_rate(
    t: float,
    curve: pd.DataFrame,
    method: str = "Taux linéaire",
    target_days: Optional[int | float] = None,
) -> float:
    """
    Interpolation de taux.

    V13.3 :
    - Pour la méthode AMMC / taux linéaire, l'interpolation se fait sur les jours de maturité :
      tr = t1 + (t2 - t1) * (M - M1) / (M2 - M1)
    - Si target_days est fourni, il est utilisé directement.
    - Sinon, si la courbe contient days_to_maturity, on convertit t en jours avec la base implicite de la courbe.
    - L'arrondi final reste à 3 décimales en pourcentage.
    """
    if curve is None or curve.empty:
        return round_rate_percent_decimals(0.0)

    y = curve["taux_moyen_pondere"].astype(float).values

    if "days_to_maturity" in curve.columns:
        x_days = curve["days_to_maturity"].astype(float).values
        if target_days is None:
            # Utilisé seulement comme fallback : la majorité des appels V13.3 passent target_days explicitement.
            target = float(t) * 365.0
        else:
            target = float(target_days)

        order = np.argsort(x_days)
        x_days, y = x_days[order], y[order]
        mask = np.isfinite(x_days) & np.isfinite(y)
        x_days, y = x_days[mask], y[mask]
        if len(x_days) == 0:
            return round_rate_percent_decimals(0.0)
        if len(x_days) == 1:
            return round_rate_percent_decimals(float(y[0]))
        if target <= x_days[0]:
            return round_rate_percent_decimals(float(y[0]))
        if target >= x_days[-1]:
            return round_rate_percent_decimals(float(y[-1]))

        if method == "Log-DF linéaire":
            x_years = x_days / 365.0
            t_years = target / 365.0
            dfs = np.array([(1.0 + yi) ** (-xi) for xi, yi in zip(x_years, y)])
            log_df_t = np.interp(target, x_days, np.log(np.maximum(dfs, 1e-12)))
            df_t = np.exp(log_df_t)
            return round_rate_percent_decimals(float(df_t ** (-1.0 / max(t_years, 1e-12)) - 1.0))

        return round_rate_percent_decimals(float(np.interp(target, x_days, y)))

    # Fallback si la courbe n'a pas days_to_maturity.
    if t <= 0:
        return round_rate_percent_decimals(0.0)
    x = curve["tenor_years"].astype(float).values
    order = np.argsort(x)
    x, y = x[order], y[order]
    if len(x) == 1:
        return round_rate_percent_decimals(float(y[0]))
    if t <= x[0]:
        return round_rate_percent_decimals(float(y[0]))
    if t >= x[-1]:
        return round_rate_percent_decimals(float(y[-1]))
    if method == "Log-DF linéaire":
        dfs = np.array([(1.0 + yi) ** (-xi) for xi, yi in zip(x, y)])
        log_df_t = np.interp(t, x, np.log(np.maximum(dfs, 1e-12)))
        df_t = np.exp(log_df_t)
        return round_rate_percent_decimals(float(df_t ** (-1.0 / t) - 1.0))
    return round_rate_percent_decimals(float(np.interp(t, x, y)))


def list_curve_history() -> pd.DataFrame:
    if not LOCAL_BAM_HISTORY_DIR.exists():
        return pd.DataFrame(columns=["date", "file"])
    rows = []
    for p in sorted(LOCAL_BAM_HISTORY_DIR.glob("courbe_bam_*.csv")):
        rows.append({"date": p.stem.replace("courbe_bam_", ""), "file": str(p)})
    return pd.DataFrame(rows)


def load_curve_history_file(path: str) -> pd.DataFrame:
    try:
        return normalize_bam_table(pd.read_csv(path))
    except Exception:
        return pd.DataFrame()
