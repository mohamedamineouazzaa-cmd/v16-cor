
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from pricing_engine import dict_to_inputs, compute_metrics, build_cashflows, price_from_cf


LOCAL_DIR = Path.home() / ".streamlit_obligations_maroc_v5"
PORTFOLIO_DIR = LOCAL_DIR / "portefeuilles"
VALUATION_HISTORY_DIR = LOCAL_DIR / "historique_valorisations"


def default_bond_dict(next_id: str = "OBL001") -> Dict[str, Any]:
    today = date.today()
    return {
        "id": next_id,
        "source": "Manuel",
        "emetteur": "Trésor / Emetteur",
        "nom_court": "",
        "nom_long": "",
        "mnemonique": "",
        "categorie_maroclear": "",
        "type_maroclear": "",
        "type_taux_maroclear": "",
        "type": "Obligation à taux fixe in fine",
        "date_emission": date(today.year - 2, today.month, min(today.day, 28)).isoformat(),
        "date_jouissance": date(today.year - 2, today.month, min(today.day, 28)).isoformat(),
        "date_echeance": date(today.year + 4, today.month, min(today.day, 28)).isoformat(),
        "mode_calendrier_coupon": "Depuis échéance vers arrière",
        "autoriser_coupon_long_contractuel": False,
        "nature_ligne": "Ligne normale",
        "structure_flux_confirmee": False,
        "date_premier_coupon": "",
        "date_coupon_precedent": "",
        "date_prochain_coupon": "",
        "maroclear_coupon_dates": "",
        "maroclear_coupon_dates_count": 0,
        "maroclear_prmy_date": "",
        "nominal": 100000.0,
        "nominal_utilise": 100000.0,
        "capital_restant_du_manuel": 0.0,
        "nominal_maroclear_parvalue": np.nan,
        "nominal_maroclear_newparvalue": np.nan,
        "issue_size_maroclear": np.nan,
        "issue_capital_maroclear": np.nan,
        "type_nominal": "Manuel / standard",
        "alertes_nominal": "",
        "quantite": 1.0,
        "nominal_total_detenu": 100000.0,
        "taux_coupon_pct": 2.50,
        "frequence": "Annuelle",
        "marge_bps": 0.0,
        "spread_credit_bps": 0.0,
        "spread_liquidite_bps": 0.0,
        "spread_subordination_bps": 0.0,
        "spread_specifique_bps": 0.0,
        "ajustement_marche_bps": 0.0,
        "tax_pct": 0.0,
        "base_coupon": "ACT/365",
        "base_actualisation": "ACT/365",
        "mode_actualisation": "Actuarielle annuelle",
        "interpolation": "Taux linéaire",
        "mode_pricing": "Courbe BAM / AMMC",
        "taux_ytm_fourni_pct": 0.0,
        "utiliser_prix_marche": False,
        "prix_clean_marche_pct": np.nan,
        "mode_ref_variable": "Courbe BAM interpolée",
        "mode_projection_variable": "FRN par au prochain reset recommandé",
        "frequence_reset": "Annuelle",
        "date_dernier_fixing": "",
        "date_prochain_fixing": "",
        "taux_ref_manuel_pct": 2.50,
        "coupon_courant_fixe_pct": 0.0,
        "tenor_ref_jours": 364,
        "mode_amortissement": "Amortissement constant",
        "valeur_option_pct": 0.0,
        "prix_action": 0.0,
        "prix_conversion": 0.0,
        "ratio_conversion_manuel": 0.0,
        "valeur_temps_option_pct": 0.0,
        "echeancier_personnalise": False,
        "fichier_echeancier": "",
        "taux_variables_table": False,
    }


def load_portfolio_file(uploaded_file) -> List[Dict[str, Any]]:
    if uploaded_file is None:
        return []
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        content = uploaded_file.getvalue().decode("utf-8", errors="replace")
        sep = ";" if content.count(";") >= content.count(",") else ","
        df = pd.read_csv(io.StringIO(content), sep=sep, engine="python")
    else:
        df = pd.read_excel(uploaded_file)
    return dataframe_to_portfolio(df)


def dataframe_to_portfolio(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    return df.replace({np.nan: None}).to_dict(orient="records")


def portfolio_to_dataframe(portfolio: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(portfolio)


def save_portfolio_local(portfolio: List[Dict[str, Any]], name: str) -> Path:
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.strip()) or "portefeuille"
    path = PORTFOLIO_DIR / f"{safe_name}.json"
    path.write_text(json.dumps(portfolio, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def list_saved_portfolios() -> pd.DataFrame:
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    rows = [{"name": p.stem, "file": str(p)} for p in sorted(PORTFOLIO_DIR.glob("*.json"))]
    return pd.DataFrame(rows)


def load_portfolio_local(path: str) -> List[Dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _value_one_position(args):
    i, b, global_settings, curve, custom_schedules, variable_tables = args
    try:
        inputs = dict_to_inputs(b, global_settings)
        csch = custom_schedules.get(inputs.id)
        vtab = variable_tables.get(inputs.id)
        m, cf, _ = compute_metrics(inputs, curve, custom_schedule=csch, variable_rates_table=vtab)
        m["ligne"] = i
        m["source"] = b.get("source", "Manuel")
        m["categorie_maroclear"] = b.get("categorie_maroclear", "")

        if str(b.get("categorie_maroclear", "")).upper() == "FPCT" and (csch is None or csch.empty):
            m["conformite_ammc"] = "Indicatif - FPCT sans échéancier confirmé"
            m["message_conformite"] = "FPCT : confirmez un échéancier personnalisé pour considérer la valorisation comme conforme."

        cf2 = pd.DataFrame()
        if cf is not None and not cf.empty:
            cf2 = cf.copy()
            cf2["ligne"] = i
            cf2["cashflow_brut_position"] = cf2["cashflow_brut"] * inputs.quantity
            cf2["pv_brut_position"] = cf2["pv_brut"] * inputs.quantity
        return m, cf2, None
    except Exception as e:
        return None, pd.DataFrame(), {"ligne": i, "id": b.get("id", ""), "erreur": str(e)}


def value_portfolio(portfolio: List[Dict[str, Any]], global_settings: Dict[str, Any], curve: pd.DataFrame,
                    custom_schedules: Dict[str, pd.DataFrame] | None = None,
                    variable_tables: Dict[str, pd.DataFrame] | None = None) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    custom_schedules = custom_schedules or {}
    variable_tables = variable_tables or {}
    if not portfolio:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    tasks = [(i, b, global_settings, curve, custom_schedules, variable_tables) for i, b in enumerate(portfolio)]
    summaries = []
    cashflows = []
    errors = []

    # Parallélisation ligne par ligne : chaque compute_metrics est indépendant.
    max_workers = min(max(1, os.cpu_count() or 1), len(tasks), 8)
    if max_workers <= 1 or len(tasks) <= 2:
        results = [_value_one_position(t) for t in tasks]
    else:
        results_map = {}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_value_one_position, t): t[0] for t in tasks}
            for fut in as_completed(futs):
                results_map[futs[fut]] = fut.result()
        results = [results_map[i] for i in range(len(tasks))]

    for m, cf2, err in results:
        if err is not None:
            errors.append(err)
        else:
            summaries.append(m)
            if cf2 is not None and not cf2.empty:
                cashflows.append(cf2)

    return (
        pd.DataFrame(summaries),
        pd.concat(cashflows, ignore_index=True) if cashflows else pd.DataFrame(),
        pd.DataFrame(errors),
    )

def portfolio_kpis(summary_df: pd.DataFrame) -> Dict[str, float]:
    if summary_df is None or summary_df.empty:
        return {"nb": 0, "clean": 0.0, "dirty": 0.0, "accrued": 0.0, "pvbp": 0.0, "duration": np.nan, "convexity": np.nan}
    dirty = summary_df["valeur_position_dirty"].sum()
    clean = summary_df["valeur_position_clean"].sum()
    accrued = summary_df["interets_courus_position"].sum()
    pvbp = summary_df["pvbp_position"].sum()
    weights = summary_df["valeur_position_dirty"] / dirty if abs(dirty) > 1e-12 else 0.0
    duration = (weights * summary_df["duration_modifiee"].fillna(0.0)).sum() if abs(dirty) > 1e-12 else np.nan
    convexity = (weights * summary_df["convexite"].fillna(0.0)).sum() if abs(dirty) > 1e-12 else np.nan
    return {"nb": len(summary_df), "clean": clean, "dirty": dirty, "accrued": accrued, "pvbp": pvbp, "duration": duration, "convexity": convexity}


def add_maturity_buckets(summary_df: pd.DataFrame, valuation_date: date) -> pd.DataFrame:
    if summary_df is None or summary_df.empty:
        return pd.DataFrame()
    df = summary_df.copy()
    df["date_echeance_dt"] = pd.to_datetime(df["date_echeance"], errors="coerce")
    df["maturite_residuelle"] = (df["date_echeance_dt"].dt.date - valuation_date).apply(lambda x: x.days / 365.0 if pd.notna(x) else np.nan)

    def bucket(x):
        if pd.isna(x):
            return "N/A"
        if x <= 1:
            return "0-1 an"
        if x <= 3:
            return "1-3 ans"
        if x <= 5:
            return "3-5 ans"
        if x <= 10:
            return "5-10 ans"
        return "10 ans+"

    df["bucket_maturite"] = df["maturite_residuelle"].apply(bucket)
    return df


def risk_contributions(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df is None or summary_df.empty:
        return pd.DataFrame()
    df = summary_df.copy()
    total_clean = df["valeur_position_clean"].sum()
    total_pvbp = df["pvbp_position"].sum()
    total_dirty = df["valeur_position_dirty"].sum()
    df["poids_clean"] = df["valeur_position_clean"] / total_clean if abs(total_clean) > 1e-12 else np.nan
    df["contribution_pvbp"] = df["pvbp_position"] / total_pvbp if abs(total_pvbp) > 1e-12 else np.nan
    df["contribution_duration"] = df["poids_clean"] * df["duration_modifiee"]
    df["poids_dirty"] = df["valeur_position_dirty"] / total_dirty if abs(total_dirty) > 1e-12 else np.nan
    return df


def _shift_curve_for_scenario(curve: pd.DataFrame, parallel_bps: float = 0.0, short_bps: float = 0.0, long_bps: float = 0.0) -> pd.DataFrame:
    if curve is None or curve.empty:
        return curve
    out = curve.copy()
    if "tenor_years" not in out.columns or "taux_moyen_pondere" not in out.columns:
        return out
    shifts = []
    for t in out["tenor_years"].astype(float):
        shape = short_bps if t <= 2 else long_bps if t >= 10 else short_bps + (long_bps - short_bps) * ((t - 2) / 8)
        shifts.append((parallel_bps + shape) / 10000.0)
    out["taux_moyen_pondere"] = out["taux_moyen_pondere"].astype(float) + np.array(shifts)
    return out


def scenario_portfolio(portfolio: List[Dict[str, Any]], global_settings: Dict[str, Any], curve: pd.DataFrame,
                       scenarios: List[Dict[str, Any]],
                       custom_schedules: Dict[str, pd.DataFrame] | None = None,
                       variable_tables: Dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """
    Scénarios alignés avec la méthode de pricing active.
    Si une formule AMMC est applicable dans compute_metrics, le scénario utilise aussi cette formule.
    """
    custom_schedules = custom_schedules or {}
    variable_tables = variable_tables or {}
    rows = []
    for sc in scenarios:
        total = 0.0
        curve_s = _shift_curve_for_scenario(
            curve,
            parallel_bps=float(sc.get("parallel_bps", 0.0)),
            short_bps=float(sc.get("short_bps", 0.0)),
            long_bps=float(sc.get("long_bps", 0.0)),
        )
        for b in portfolio:
            b_s = deepcopy(b)
            credit_bps = float(sc.get("credit_bps", 0.0))
            if credit_bps:
                b_s["spread_credit_bps"] = float(b_s.get("spread_credit_bps", 0.0) or 0.0) + credit_bps

            inputs = dict_to_inputs(b_s, global_settings)
            csch = custom_schedules.get(inputs.id)
            vtab = variable_tables.get(inputs.id)
            m, cf, _ = compute_metrics(inputs, curve_s, custom_schedule=csch, variable_rates_table=vtab)
            p = float(m.get("dirty_price", 0.0)) * inputs.quantity
            total += p
        rows.append({"scenario": sc.get("name", ""), **sc, "valeur_dirty_portefeuille": total})
    df = pd.DataFrame(rows)
    if not df.empty:
        base = df.loc[df["scenario"].eq("Base"), "valeur_dirty_portefeuille"]
        base_val = float(base.iloc[0]) if not base.empty else float(df["valeur_dirty_portefeuille"].iloc[0])
        df["variation_valeur"] = df["valeur_dirty_portefeuille"] - base_val
        df["variation_pct"] = df["variation_valeur"] / base_val if abs(base_val) > 1e-12 else np.nan
    return df

def save_valuation_history(summary_df: pd.DataFrame, kpis: Dict[str, Any], valuation_date: date) -> Path:
    VALUATION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = VALUATION_HISTORY_DIR / f"valorisation_{valuation_date.isoformat()}_{pd.Timestamp.now().strftime('%H%M%S')}.json"
    payload = {
        "valuation_date": valuation_date.isoformat(),
        "timestamp": pd.Timestamp.now().isoformat(),
        "kpis": kpis,
        "summary": summary_df.to_dict(orient="records") if summary_df is not None else [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def list_valuation_history() -> pd.DataFrame:
    VALUATION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(VALUATION_HISTORY_DIR.glob("valorisation_*.json")):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            k = payload.get("kpis", {})
            rows.append({
                "date": payload.get("valuation_date"),
                "timestamp": payload.get("timestamp"),
                "valeur_clean": k.get("clean"),
                "valeur_dirty": k.get("dirty"),
                "duration": k.get("duration"),
                "pvbp": k.get("pvbp"),
                "file": str(p),
            })
        except Exception:
            pass
    return pd.DataFrame(rows)
