
# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy
import io
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as pex
import streamlit as st

from bam_data import (
    get_bam_curve, read_uploaded_curve, normalize_bam_table,
    select_curve_snapshot, curve_selection_diagnostics, list_curve_history, load_curve_history_file
)
from maroclear_ref import (
    read_maroclear_bytes, search_reference, reference_quality_checks, instrument_to_portfolio_row,
    enrich_simple_portfolio
)
from portfolio_manager import (
    default_bond_dict, portfolio_to_dataframe, load_portfolio_file, save_portfolio_local,
    list_saved_portfolios, load_portfolio_local, value_portfolio, portfolio_kpis,
    add_maturity_buckets, risk_contributions, scenario_portfolio, save_valuation_history,
    list_valuation_history
)
from pricing_engine import dict_to_inputs, compute_metrics, generate_coupon_schedule, get_previous_coupon_date, year_fraction
from validation_rules import validate_portfolio, validate_limits, validate_valuation_summary
from export_tools import excel_bytes, pdf_report_bytes, pdf_simplified_report_bytes


st.set_page_config(page_title="Valorisation Obligataire Maroc", page_icon="🏦", layout="wide")

BOND_TYPES = [
    "BDT / zéro coupon court terme",
    "Obligation à taux fixe in fine",
    "Obligation à taux révisable / variable",
    "Obligation amortissable",
    "Obligation subordonnée",
    "Obligation perpétuelle",
    "Obligation callable simplifiée",
    "Obligation puttable simplifiée",
    "Obligation convertible simplifiée",
]
FREQS = ["Annuelle", "Semestrielle", "Trimestrielle", "Mensuelle"]
DAY_COUNT = ["ACT/365", "ACT/360", "ACT/ACT", "30/360"]
COMPOUNDING = ["Actuarielle annuelle", "Simple", "Continue"]
INTERP = ["Taux linéaire", "Log-DF linéaire"]


def fmt_dh(x):
    try:
        if pd.isna(x): return "-"
        return f"{x:,.2f}".replace(",", " ").replace(".", ",")
    except Exception:
        return "-"


def fmt_pct(x):
    try:
        if pd.isna(x): return "-"
        return f"{x*100:.3f}%"
    except Exception:
        return "-"


def _safe_date_from_value(x, fallback=None):
    try:
        ts = pd.to_datetime(x, errors="coerce")
        if pd.isna(ts):
            return fallback or date.today()
        return ts.date()
    except Exception:
        return fallback or date.today()


def make_flux_editor_default(instrument_dict, global_settings, curve_snapshot, active_custom_schedule=None):
    """
    Prépare un tableau de flux éditable pour un seul titre.
    Priorité :
    1) échéancier personnalisé déjà actif ;
    2) cashflows calculés par le moteur ;
    3) calendrier coupon vide généré.
    """
    if active_custom_schedule is not None and not active_custom_schedule.empty:
        df = active_custom_schedule.copy()
        if "type_flux" not in df.columns:
            df["type_flux"] = "personnalisé"
        keep = [c for c in ["date_flux", "coupon", "principal", "type_flux"] if c in df.columns]
        return df[keep]

    try:
        inputs_tmp = dict_to_inputs(instrument_dict, global_settings)
        m_tmp, cf_tmp, accrued_tmp = compute_metrics(inputs_tmp, curve_snapshot)
        if cf_tmp is not None and not cf_tmp.empty:
            # Pour le mode FRN par reset, le principal correspond à une hypothèse de revente au pair
            # au reset, pas forcément à un remboursement juridique. On le marque clairement.
            out = cf_tmp[["date_flux", "coupon_brut", "principal", "source_cashflow"]].copy()
            out["date_flux"] = pd.to_datetime(out["date_flux"], errors="coerce").dt.strftime("%Y-%m-%d")
            out = out.rename(columns={"coupon_brut": "coupon", "source_cashflow": "type_flux"})
            return out[["date_flux", "coupon", "principal", "type_flux"]]
    except Exception:
        pass

    try:
        inputs_tmp = dict_to_inputs(instrument_dict, global_settings)
        full_schedule = generate_coupon_schedule(inputs_tmp)
        future_dates = [d for d in full_schedule if d > global_settings.get("settlement_date", date.today())]
        if not future_dates and inputs_tmp.maturity_date > global_settings.get("settlement_date", date.today()):
            future_dates = [inputs_tmp.maturity_date]
        return pd.DataFrame([
            {"date_flux": d.isoformat(), "coupon": 0.0, "principal": 0.0, "type_flux": "manuel"}
            for d in future_dates
        ])
    except Exception:
        return pd.DataFrame([{"date_flux": date.today().isoformat(), "coupon": 0.0, "principal": 0.0, "type_flux": "manuel"}])


def make_variable_table_default(instrument_dict, global_settings):
    """
    Prépare une table de taux variables éditable par titre.
    L'utilisateur peut renseigner soit coupon_total_pct, soit taux_reference_pct.
    """
    try:
        inputs_tmp = dict_to_inputs(instrument_dict, global_settings)
        full_schedule = generate_coupon_schedule(inputs_tmp)
        future_dates = [d for d in full_schedule if d > global_settings.get("settlement_date", date.today())]
        if not future_dates and inputs_tmp.maturity_date > global_settings.get("settlement_date", date.today()):
            future_dates = [inputs_tmp.maturity_date]
        rows = []
        current_coupon = float(instrument_dict.get("coupon_courant_fixe_pct", 0.0) or 0.0)
        facial_coupon = float(instrument_dict.get("taux_coupon_pct", 0.0) or 0.0)
        for i, d in enumerate(future_dates, start=1):
            rows.append({
                "date_flux": d.isoformat(),
                "taux_reference_pct": "",
                "coupon_total_pct": current_coupon if (i == 1 and current_coupon > 0) else facial_coupon,
                "note": "coupon courant" if (i == 1 and current_coupon > 0) else "à confirmer",
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame([{
            "date_flux": date.today().isoformat(),
            "taux_reference_pct": "",
            "coupon_total_pct": float(instrument_dict.get("coupon_courant_fixe_pct", instrument_dict.get("taux_coupon_pct", 0.0)) or 0.0),
            "note": "à confirmer",
        }])


def init_state():
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = []
    if "maroclear_ref" not in st.session_state:
        st.session_state.maroclear_ref = pd.DataFrame()
    if "form_defaults" not in st.session_state:
        st.session_state.form_defaults = default_bond_dict()
    if "edit_index" not in st.session_state:
        st.session_state.edit_index = None
    if "custom_schedules" not in st.session_state:
        st.session_state.custom_schedules = {}
    if "variable_tables" not in st.session_state:
        st.session_state.variable_tables = {}
    if "uploaded_curve_df" not in st.session_state:
        st.session_state.uploaded_curve_df = pd.DataFrame()
    if "uploaded_curve_name" not in st.session_state:
        st.session_state.uploaded_curve_name = ""
    if "uploaded_curve_status" not in st.session_state:
        st.session_state.uploaded_curve_status = ""
    if "uploaded_curve_raw_columns" not in st.session_state:
        st.session_state.uploaded_curve_raw_columns = []
    if "last_manual_preview" not in st.session_state:
        st.session_state.last_manual_preview = None


init_state()


@st.cache_data(show_spinner=False)
def cached_read_maroclear(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    return read_maroclear_bytes(file_bytes, file_name)


@st.cache_data(show_spinner=False)
def cached_read_uploaded_curve(file_bytes: bytes, file_name: str):
    """
    Lecture robuste de la courbe BAM uploadée.
    Supporte :
    - CSV propre avec en-têtes en première ligne ;
    - CSV officiel BAM avec lignes de titre :
      "Taux de référence des bons du Trésor"
      "En millions de dirhams"
      puis la ligne d'en-tête ;
    - séparateur ; , tabulation ;
    - décimales françaises et symbole %.
    Retourne : dataframe normalisé, message, colonnes brutes.
    """
    try:
        name = file_name.lower()
        raw_columns = []
        raw = None

        def find_bam_header_line(txt: str) -> int:
            lines = txt.splitlines()
            for i, line in enumerate(lines[:30]):
                l = line.lower()
                if (
                    ("date d" in l or "date_echeance" in l or "date echeance" in l)
                    and ("taux" in l or "moyen" in l)
                ):
                    return i
            return 0

        def try_read_csv(txt: str, sep: str, skiprows: int):
            return pd.read_csv(
                io.StringIO(txt),
                sep=sep,
                engine="python",
                skiprows=skiprows,
                quotechar='"',
                on_bad_lines="skip",
            )

        if name.endswith(".csv"):
            encodings = ["utf-8-sig", "utf-8", "latin1"]
            seps = [";", ",", "\t"]
            candidates = []

            for enc in encodings:
                try:
                    txt = file_bytes.decode(enc, errors="replace")
                except Exception:
                    continue

                header_line = find_bam_header_line(txt)

                for sep in seps:
                    for skiprows in sorted(set([0, header_line])):
                        try:
                            candidate = try_read_csv(txt, sep, skiprows)
                            if candidate is None or candidate.empty:
                                continue
                            cols = [str(c).lower() for c in candidate.columns]
                            score = 0
                            score += sum(("date" in c) for c in cols)
                            score += sum(("taux" in c or "moyen" in c) for c in cols)
                            score += candidate.shape[1]
                            candidates.append((score, candidate))
                        except Exception:
                            pass

            if candidates:
                candidates = sorted(candidates, key=lambda x: x[0], reverse=True)
                raw = candidates[0][1]
        else:
            raw = pd.read_excel(io.BytesIO(file_bytes))

        if raw is None or raw.empty:
            return pd.DataFrame(), (
                "Fichier lu, mais aucune ligne exploitable. "
                "Si c'est un CSV BAM officiel, vérifiez que la ligne contenant "
                "Date d'échéance;Transaction;Taux moyen pondéré;Date de la valeur est présente."
            ), []

        # Supprimer les lignes Total / vides avant normalisation.
        raw_columns = [str(c) for c in raw.columns]
        raw = raw.dropna(how="all")
        if raw.shape[1] > 0:
            first_col = raw.iloc[:, 0].astype(str).str.lower().str.strip()
            raw = raw[~first_col.isin(["total", "totaux"])]

        norm = normalize_bam_table(raw)

        if norm is None or norm.empty:
            msg = (
                "Fichier chargé, mais format de courbe non reconnu. "
                "Colonnes attendues : date_echeance, taux_moyen_pondere, date_valeur "
                "ou Date d'échéance, Taux moyen pondéré, Date de la valeur."
            )
            return pd.DataFrame(), msg, raw_columns

        norm["source"] = f"Upload utilisateur : {file_name}"
        msg = f"Courbe uploadée activée : {file_name} ({len(norm)} points)."
        return norm, msg, raw_columns

    except Exception as e:
        return pd.DataFrame(), f"Erreur lecture fichier courbe : {e}", []


def _df_to_json_cache(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    return df.to_json(orient="split", date_format="iso")


def _dict_df_to_json_cache(d: dict) -> str:
    if not d:
        return "{}"
    payload = {}
    for k, v in d.items():
        if v is not None and not v.empty:
            payload[str(k)] = _df_to_json_cache(v)
    return json.dumps(payload, sort_keys=True)


@st.cache_data(show_spinner=False)
def cached_value_portfolio_json(portfolio_json: str, global_json: str, curve_json: str, custom_json: str, variable_json: str):
    portfolio = json.loads(portfolio_json)
    gs_raw = json.loads(global_json)
    global_settings_cached = {
        "valuation_date": pd.to_datetime(gs_raw["valuation_date"]).date(),
        "settlement_date": pd.to_datetime(gs_raw["settlement_date"]).date(),
    }

    curve_cached = pd.DataFrame()
    if curve_json:
        curve_cached = pd.read_json(io.StringIO(curve_json), orient="split")
        for c in ["date_echeance", "date_valeur"]:
            if c in curve_cached.columns:
                curve_cached[c] = pd.to_datetime(curve_cached[c], errors="coerce")

    def parse_dict_df(txt: str):
        raw = json.loads(txt or "{}")
        out = {}
        for k, v in raw.items():
            df = pd.read_json(io.StringIO(v), orient="split")
            if "date_flux" in df.columns:
                df["date_flux"] = pd.to_datetime(df["date_flux"], errors="coerce").dt.strftime("%Y-%m-%d")
            out[k] = df
        return out

    return value_portfolio(
        portfolio,
        global_settings_cached,
        curve_cached,
        custom_schedules=parse_dict_df(custom_json),
        variable_tables=parse_dict_df(variable_json),
    )

def curve_is_sample(df: pd.DataFrame) -> bool:
    if df is None or df.empty or "source" not in df.columns:
        return False
    return df["source"].astype(str).str.contains("Echantillon|Échantillon|sample", case=False, na=False).any()


st.title("🏦 Valorisation Obligataire Maroc")
st.caption("Courbe BAM, référentiel Maroclear, valorisation, risques, contrôles et exports.")

with st.sidebar:
    st.header("⚙️ Paramètres globaux")
    valuation_date = st.date_input("Date de valorisation", value=date.today())
    settlement_date = st.date_input("Date de règlement", value=valuation_date)

    st.divider()
    st.subheader("Courbe BAM")
    auto_fetch = st.checkbox("Mise à jour BAM quotidienne à l'ouverture", value=True)
    force_bam = st.button("📥 Obtenir les données BAM maintenant", use_container_width=True)
    desired_curve_date = st.date_input("Date de valeur souhaitée", value=valuation_date)
    curve_mode_label = st.selectbox("Méthode courbe", ["Dernière observation par maturité", "Strict : dernière date commune"])
    maturity_basis_label = st.selectbox("Base de calcul des maturités", ["Date valeur BAM", "Date de valeur souhaitée"], index=0)
    uploaded_curve = st.file_uploader("Upload courbe BAM CSV/XLSX", type=["csv", "xlsx", "xls"], key="curve_upload")

    if uploaded_curve is not None:
        parsed_curve, parsed_msg, raw_cols = cached_read_uploaded_curve(uploaded_curve.getvalue(), uploaded_curve.name)
        st.session_state.uploaded_curve_df = parsed_curve
        st.session_state.uploaded_curve_name = uploaded_curve.name
        st.session_state.uploaded_curve_status = parsed_msg
        st.session_state.uploaded_curve_raw_columns = raw_cols

    if not st.session_state.uploaded_curve_df.empty:
        st.success(f"Courbe uploadée active : {st.session_state.uploaded_curve_name}")
        use_uploaded_curve = st.checkbox("Utiliser la courbe uploadée pour la valorisation", value=True)
        if st.button("Retirer la courbe uploadée", use_container_width=True):
            st.session_state.uploaded_curve_df = pd.DataFrame()
            st.session_state.uploaded_curve_name = ""
            st.session_state.uploaded_curve_status = ""
            st.session_state.uploaded_curve_raw_columns = []
            st.rerun()
    else:
        use_uploaded_curve = False
        if st.session_state.uploaded_curve_status:
            st.error(st.session_state.uploaded_curve_status)
            if st.session_state.uploaded_curve_raw_columns:
                st.caption("Colonnes détectées : " + ", ".join(st.session_state.uploaded_curve_raw_columns[:8]))

    st.divider()
    if st.button("🧹 Vider portefeuille", use_container_width=True):
        st.session_state.portfolio = []
        st.session_state.edit_index = None
        st.session_state.form_defaults = default_bond_dict()
        st.rerun()


# Chargement courbe
if auto_fetch or force_bam:
    bam_df, curve_msg, bam_meta = get_bam_curve(force_refresh=force_bam)
else:
    bam_df, curve_msg, bam_meta = get_bam_curve(force_refresh=False)

# Priorité à la courbe uploadée si l'utilisateur l'a activée.
uploaded_curve_df = st.session_state.uploaded_curve_df
if use_uploaded_curve and uploaded_curve_df is not None and not uploaded_curve_df.empty:
    all_curve = uploaded_curve_df.copy()
    curve_msg = st.session_state.uploaded_curve_status or "Courbe utilisée : fichier uploadé."
    curve_source_active = "upload"
else:
    all_curve = bam_df
    curve_source_active = "bam_auto_or_sample"

curve_mode = "strict_common_date" if curve_mode_label.startswith("Strict") else "last_per_maturity"
maturity_basis = "date_reference" if maturity_basis_label.startswith("Date de valeur souhaitée") else "date_valeur"
curve_snapshot = select_curve_snapshot(all_curve, desired_curve_date, mode=curve_mode, maturity_date_basis=maturity_basis)
curve_diag = curve_selection_diagnostics(all_curve, desired_curve_date, mode=curve_mode, maturity_date_basis=maturity_basis)

# Si l'utilisateur a uploadé une courbe mais que le snapshot est vide, ne pas revenir silencieusement à l'échantillon.
if use_uploaded_curve and (curve_snapshot is None or curve_snapshot.empty):
    curve_msg = (
        "Courbe uploadée lue, mais aucun point exploitable après sélection de la date de valeur. "
        "Vérifiez la Date de valeur souhaitée, les dates d'échéance et les colonnes du fichier."
    )

global_settings = {"valuation_date": valuation_date, "settlement_date": settlement_date}

portfolio_json = json.dumps(st.session_state.portfolio, ensure_ascii=False, sort_keys=True, default=str)
global_json = json.dumps({
    "valuation_date": valuation_date.isoformat(),
    "settlement_date": settlement_date.isoformat(),
}, sort_keys=True)
curve_json = _df_to_json_cache(curve_snapshot)
custom_json = _dict_df_to_json_cache(st.session_state.custom_schedules)
variable_json = _dict_df_to_json_cache(st.session_state.variable_tables)

summary_df, all_cf_df, errors_df = cached_value_portfolio_json(
    portfolio_json,
    global_json,
    curve_json,
    custom_json,
    variable_json,
)
kpis = portfolio_kpis(summary_df)
alerts_df = validate_portfolio(st.session_state.portfolio, valuation_date)
valuation_alerts_df = validate_valuation_summary(summary_df)
if not valuation_alerts_df.empty:
    alerts_df = pd.concat([alerts_df, valuation_alerts_df], ignore_index=True) if not alerts_df.empty else valuation_alerts_df


def build_simplified_export(summary: pd.DataFrame) -> pd.DataFrame:
    if summary is None or summary.empty:
        return pd.DataFrame(columns=["id", "emetteur", "type", "dirty_price", "taux_utilise_pct"])
    out = summary.copy()
    def pick_rate(row):
        try:
            if str(row.get("mode_pricing", "")).startswith("YTM") and pd.notna(row.get("taux_ytm_fourni")) and float(row.get("taux_ytm_fourni")) > 0:
                return float(row.get("taux_ytm_fourni")) * 100
            if pd.notna(row.get("taux_ammc")):
                return float(row.get("taux_ammc")) * 100
            if pd.notna(row.get("ytm")):
                return float(row.get("ytm")) * 100
        except Exception:
            return np.nan
        return np.nan
    out["taux_utilise_pct"] = out.apply(pick_rate, axis=1)
    out["methode"] = out.get("methode_pricing_active", "")
    cols = ["id", "emetteur", "type", "dirty_price", "taux_utilise_pct", "methode"]
    return out[[c for c in cols if c in out.columns]]


tabs = st.tabs([
    "1️⃣ Courbe BAM",
    "2️⃣ Référentiel Maroclear",
    "3️⃣ Recherche & ajout titre",
    "4️⃣ Portefeuille",
    "5️⃣ Saisie instrument",
    "6️⃣ Valorisation détaillée",
    "7️⃣ Risques & stress tests",
    "8️⃣ Contrôles",
    "9️⃣ Exports",
])


# -------------------------------------------------------------------
# 1. Courbe BAM
# -------------------------------------------------------------------
with tabs[0]:
    st.subheader("Courbe BAM")

    if curve_source_active == "upload" and not curve_snapshot.empty:
        st.success(curve_msg)
        st.info("La valorisation utilise actuellement la courbe que vous avez uploadée.")
    elif "non récupérable" in curve_msg.lower() or curve_is_sample(curve_snapshot):
        st.error("Courbe BAM réelle non confirmée : chargez une courbe du jour pour une valorisation fiable.")
        st.warning(curve_msg)
    else:
        st.success(curve_msg)

    model_curve = pd.DataFrame({
        "date_echeance": ["2026-08-17", "2027-05-18", "2028-05-16"],
        "transaction_mdh": [0, 0, 0],
        "taux_moyen_pondere": [0.0229, 0.0250, 0.0275],
        "date_valeur": ["2026-05-11", "2026-05-11", "2026-05-11"],
    })
    st.download_button(
        "⬇️ Télécharger un modèle de courbe BAM compatible",
        data=model_curve.to_csv(index=False, sep=";").encode("utf-8-sig"),
        file_name="modele_courbe_bam.csv",
        mime="text/csv",
        use_container_width=True,
    )

    if st.session_state.uploaded_curve_status and st.session_state.uploaded_curve_df.empty:
        st.error(st.session_state.uploaded_curve_status)
        if st.session_state.uploaded_curve_raw_columns:
            st.caption("Colonnes détectées : " + ", ".join(st.session_state.uploaded_curve_raw_columns))

    if bam_meta:
        st.caption(f"Dernière récupération : {bam_meta.get('fetch_datetime', '-')}, lignes : {bam_meta.get('rows', '-')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lignes brutes", curve_diag.get("lignes_brutes", len(all_curve) if all_curve is not None else 0))
    c2.metric("Points utilisés", len(curve_snapshot))
    c3.metric("Date valeur min", curve_snapshot["date_valeur"].min().strftime("%d/%m/%Y") if not curve_snapshot.empty else "-")
    c4.metric("Date valeur max", curve_snapshot["date_valeur"].max().strftime("%d/%m/%Y") if not curve_snapshot.empty else "-")

    with st.expander("Diagnostic sélection courbe"):
        st.write({
            "mode": curve_mode_label,
            "base_maturite": maturity_basis_label,
            "lignes_apres_mode": curve_diag.get("lignes_apres_mode"),
            "points_utilises": curve_diag.get("points_utilises"),
            "exclus_maturite": curve_diag.get("exclus_maturite"),
            "duplicates_echeance_date": curve_diag.get("duplicates_echeance"),
        })
        excl = curve_diag.get("lignes_exclues")
        if isinstance(excl, pd.DataFrame) and not excl.empty:
            show_excl = excl.copy()
            for c in ["date_echeance", "date_valeur"]:
                if c in show_excl.columns:
                    show_excl[c] = pd.to_datetime(show_excl[c], errors="coerce").dt.strftime("%d/%m/%Y")
            st.caption("Lignes exclues car maturité <= base de calcul.")
            st.dataframe(show_excl, use_container_width=True, hide_index=True)

    if not curve_snapshot.empty:
        show = curve_snapshot.copy()
        show["date_echeance"] = show["date_echeance"].dt.strftime("%d/%m/%Y")
        show["date_valeur"] = show["date_valeur"].dt.strftime("%d/%m/%Y")
        show["taux_pct"] = show["taux_moyen_pondere"] * 100
        st.dataframe(show[["date_echeance", "date_valeur", "tenor_years", "taux_pct", "transaction_mdh", "source"]], use_container_width=True, hide_index=True)
        fig = pex.line(curve_snapshot, x="tenor_years", y="taux_moyen_pondere", markers=True, title="Courbe BDT utilisée")
        fig.update_yaxes(tickformat=".2%")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Historique local des courbes")
    hist = list_curve_history()
    st.dataframe(hist, use_container_width=True, hide_index=True)


# -------------------------------------------------------------------
# 2. Référentiel Maroclear
# -------------------------------------------------------------------
with tabs[1]:
    st.subheader("Référentiel Maroclear")
    st.markdown("Importe le fichier REP MCL. L'application le transforme en base titres exploitable pour la valorisation.")

    mcl_file = st.file_uploader("Importer fichier Maroclear REP MCL XLSX/CSV", type=["xlsx", "xls", "csv"], key="mcl_upload")
    if mcl_file is not None:
        with st.spinner("Lecture du référentiel Maroclear..."):
            ref = cached_read_maroclear(mcl_file.getvalue(), mcl_file.name)
            st.session_state.maroclear_ref = ref
        st.success(f"Référentiel chargé : {len(st.session_state.maroclear_ref):,} lignes normalisées.")

    ref_df = st.session_state.maroclear_ref
    if ref_df.empty:
        st.info("Aucun référentiel chargé. Uploade le fichier REP MCL pour activer la recherche par ISIN.")
    else:
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Instruments", len(ref_df))
        r2.metric("Titres de dette", int(ref_df["is_debt"].sum()))
        r3.metric("Actifs", int(ref_df["is_active"].sum()))
        r4.metric("Catégories", ref_df["category"].nunique())

        st.markdown("### Contrôle qualité référentiel")
        qc = reference_quality_checks(ref_df)
        st.dataframe(qc, use_container_width=True, hide_index=True)

        st.markdown("### Aperçu simplifié")
        preview = search_reference(ref_df, only_debt=False, only_active=False, max_rows=200)
        st.dataframe(preview, use_container_width=True, hide_index=True)


# -------------------------------------------------------------------
# 3. Recherche & ajout titre
# -------------------------------------------------------------------
with tabs[2]:
    st.subheader("Recherche instrument Maroclear → Ajout au portefeuille")
    ref_df = st.session_state.maroclear_ref

    if ref_df.empty:
        st.info("Charge d'abord le référentiel dans l'onglet Référentiel Maroclear.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        query = f1.text_input("Recherche rapide : ISIN / mnémonique / émetteur", help="La recherche utilise un index pré-calculé.")
        only_debt = f2.checkbox("Dette seulement", value=True)
        only_active = f3.checkbox("Actifs seulement", value=True)
        only_not_matured = f4.checkbox("Non échus seulement", value=True)

        f5, f6, f7, f8 = st.columns(4)
        cats = ["Tous"] + sorted(ref_df["category"].dropna().astype(str).unique().tolist())
        cat = f5.selectbox("Catégorie", cats)
        issuer = f6.text_input("Filtre émetteur contient", value="", help="Plus rapide qu’un menu déroulant avec des milliers d’émetteurs.")
        interest_types = ["Tous"] + sorted(ref_df["interest_type"].dropna().astype(str).unique().tolist())
        itype = f7.selectbox("Type taux", interest_types)
        max_rows = f8.number_input("Résultats max", min_value=50, max_value=2000, value=300, step=50)

        results = search_reference(
            ref_df,
            query=query,
            only_debt=only_debt,
            only_active=only_active,
            category=cat,
            issuer=issuer if issuer.strip() else "Tous",
            interest_type=itype,
            max_rows=int(max_rows),
            maturity_after=valuation_date if only_not_matured else None,
        )
        st.dataframe(results, use_container_width=True, hide_index=True)

        if not results.empty:
            records_for_selection = results.reset_index(drop=True)
            labels = [
                f"{pos} | {r['isin']} | {r.get('issuer_name','')} | {r.get('app_bond_type','')}"
                for pos, r in records_for_selection.iterrows()
            ]
            sel = st.selectbox("Sélectionner un titre à ajouter", labels)
            sel_pos = labels.index(sel)
            instr = records_for_selection.iloc[sel_pos].to_dict()

            st.markdown("### Paramètres portefeuille à compléter")
            a1, a2, a3, a4 = st.columns(4)
            qty = a1.number_input("Quantité", value=1.0, min_value=0.0, step=1.0)
            sp = a2.number_input("Spread crédit bps", value=0.0, step=1.0)
            liq = a3.number_input("Spread liquidité bps", value=0.0, step=1.0)
            market_price_ref = a4.number_input("Prix clean marché %", value=100.0, step=0.01)

            st.markdown("### Choix du nominal utilisé")
            parv = instr.get("par_value", np.nan)
            newparv = instr.get("new_par_value", np.nan)
            isize = instr.get("issue_size", np.nan)
            icap = instr.get("issue_capital", np.nan)
            n1, n2, n3, n4 = st.columns(4)
            n1.metric("PARVALUE Maroclear", "-" if pd.isna(parv) else f"{float(parv):,.2f}")
            n2.metric("NEWPARVALUE Maroclear", "-" if pd.isna(newparv) else f"{float(newparv):,.2f}")
            n3.metric("ISSUESIZE", "-" if pd.isna(isize) else f"{float(isize):,.0f}")
            n4.metric("ISSUECAPITAL", "-" if pd.isna(icap) else f"{float(icap):,.2f}")

            nominal_mode_label = st.radio(
                "Nominal à utiliser dans la valorisation",
                ["Auto intelligent", "Utiliser PARVALUE Maroclear", "Utiliser NEWPARVALUE Maroclear", "Forcer 100 000 MAD", "Saisir nominal manuellement"],
                horizontal=True,
            )
            nominal_mode_map = {
                "Auto intelligent": "auto",
                "Utiliser PARVALUE Maroclear": "parvalue",
                "Utiliser NEWPARVALUE Maroclear": "newparvalue",
                "Forcer 100 000 MAD": "standard_100000",
                "Saisir nominal manuellement": "manuel",
            }
            manual_nominal = st.number_input("Nominal manuel", value=100000.0, min_value=0.0, step=1000.0, disabled=nominal_mode_label != "Saisir nominal manuellement")
            nominal_mode = nominal_mode_map[nominal_mode_label]

            maturity_selected = pd.to_datetime(instr.get("maturity_date"), errors="coerce")
            is_matured_selected = (not pd.isna(maturity_selected)) and maturity_selected.date() <= valuation_date

            if is_matured_selected:
                st.warning(
                    "Ce titre semble déjà échu par rapport à la date de valorisation. "
                    "Il ne doit normalement pas être ajouté à un portefeuille vivant."
                )
                allow_matured = st.checkbox("Autoriser quand même l'ajout du titre échu", value=False)
            else:
                allow_matured = True

            if st.button("➕ Ajouter ce titre Maroclear au portefeuille", use_container_width=True, disabled=not allow_matured):
                row = instrument_to_portfolio_row(instr, quantity=qty, spread_credit_bps=sp, spread_liquidite_bps=liq, market_clean_price_pct=market_price_ref, nominal_mode=nominal_mode, manual_nominal=manual_nominal)
                st.session_state.portfolio.append(row)
                st.success(f"Titre {row['id']} ajouté au portefeuille.")
                st.rerun()

        st.divider()
        st.markdown("### Import portefeuille simplifié par ISIN")
        st.caption("Format minimal : ISIN ; Quantite ; Prix clean marche pct ; Spread credit bps ; Spread liquidite bps. Si spread absent : 0 bps.")
        simple_file = st.file_uploader("Importer portefeuille simple CSV/XLSX", type=["csv", "xlsx", "xls"], key="simple_pf")
        if simple_file is not None:
            if simple_file.name.lower().endswith(".csv"):
                content = simple_file.getvalue().decode("utf-8", errors="replace")
                sep = ";" if content.count(";") >= content.count(",") else ","
                simple_df = pd.read_csv(io.StringIO(content), sep=sep)
            else:
                simple_df = pd.read_excel(simple_file)
            rows, errs = enrich_simple_portfolio(simple_df, ref_df)
            st.write(f"Lignes enrichies : {len(rows)}")
            if not errs.empty:
                st.error("Certaines lignes n'ont pas été trouvées.")
                st.dataframe(errs, use_container_width=True, hide_index=True)
            if rows and st.button("Ajouter toutes les lignes enrichies au portefeuille"):
                st.session_state.portfolio.extend(rows)
                st.success("Portefeuille enrichi ajouté.")
                st.rerun()


# -------------------------------------------------------------------
# 4. Portefeuille
# -------------------------------------------------------------------
with tabs[3]:
    st.subheader("Portefeuille")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Lignes", int(kpis["nb"]))
    k2.metric("Clean total", fmt_dh(kpis["clean"]))
    k3.metric("Dirty total", fmt_dh(kpis["dirty"]))
    k4.metric("Duration", "-" if pd.isna(kpis["duration"]) else f"{kpis['duration']:.4f}")
    k5.metric("PVBP", fmt_dh(kpis["pvbp"]))

    up_pf = st.file_uploader("Importer portefeuille complet CSV/XLSX", type=["csv", "xlsx", "xls"], key="full_pf")
    if up_pf is not None:
        rows = load_portfolio_file(up_pf)
        if st.button("Remplacer le portefeuille par ce fichier"):
            st.session_state.portfolio = rows
            st.success("Portefeuille importé.")
            st.rerun()

    if not st.session_state.portfolio:
        st.info("Aucune ligne. Ajoute via Maroclear ou via saisie manuelle.")
    else:
        raw = portfolio_to_dataframe(st.session_state.portfolio)
        st.markdown("### Données saisies")
        st.dataframe(raw, use_container_width=True, hide_index=True)

        st.markdown("### Résumé valorisé")
        if not summary_df.empty:
            hidden_compare_cols = [
                "dirty_price_dcf", "prix_ammc", "prix_net_ammc", "ecart_app_vs_dcf",
                "formule_ammc", "methode_pricing_active"
            ]
            view = summary_df.drop(columns=[c for c in hidden_compare_cols if c in summary_df.columns]).copy()
            st.dataframe(view, use_container_width=True, hide_index=True)

            rc = risk_contributions(add_maturity_buckets(summary_df, valuation_date))
            col1, col2 = st.columns(2)
            with col1:
                if "type" in summary_df.columns:
                    fig = pex.pie(summary_df, values="valeur_position_clean", names="type", title="Répartition par type")
                    st.plotly_chart(fig, use_container_width=True)
            with col2:
                if "bucket_maturite" in rc.columns:
                    bucket_df = rc.groupby("bucket_maturite", as_index=False)["valeur_position_clean"].sum()
                    fig2 = pex.bar(bucket_df, x="bucket_maturite", y="valeur_position_clean", title="Buckets de maturité")
                    st.plotly_chart(fig2, use_container_width=True)

        st.divider()
        labels = [f"{i+1} - {b.get('id','')} - {b.get('emetteur','')}" for i, b in enumerate(st.session_state.portfolio)]
        sel = st.selectbox("Action sur ligne", labels)
        idx = labels.index(sel)
        a1, a2, a3 = st.columns(3)
        if a1.button("✏️ Modifier dans formulaire"):
            st.session_state.form_defaults = deepcopy(st.session_state.portfolio[idx])
            st.session_state.edit_index = idx
            st.success("Ligne chargée dans l'onglet Nouvelle obligation manuelle.")
        if a2.button("📋 Dupliquer"):
            row = deepcopy(st.session_state.portfolio[idx])
            row["id"] = str(row.get("id", "OBL")) + "_COPY"
            st.session_state.portfolio.append(row)
            st.rerun()
        if a3.button("🗑️ Supprimer"):
            del st.session_state.portfolio[idx]
            st.rerun()

        st.divider()
        c1, c2 = st.columns(2)
        save_name = c1.text_input("Nom de sauvegarde portefeuille", value="portefeuille_obligataire")
        if c2.button("💾 Sauvegarder localement"):
            path = save_portfolio_local(st.session_state.portfolio, save_name)
            st.success(f"Sauvegardé : {path}")

        saved = list_saved_portfolios()
        if not saved.empty:
            choice = st.selectbox("Charger portefeuille sauvegardé", saved["name"].tolist())
            if st.button("📂 Charger sauvegarde"):
                path = saved.loc[saved["name"] == choice, "file"].iloc[0]
                st.session_state.portfolio = load_portfolio_local(path)
                st.rerun()


# -------------------------------------------------------------------
# 5. Nouvelle obligation manuelle
# -------------------------------------------------------------------
with tabs[4]:
    st.subheader("Saisie instrument & échéancier")
    fd = deepcopy(st.session_state.form_defaults)
    edit_mode = st.session_state.edit_index is not None
    if edit_mode:
        st.warning(f"Mode modification ligne {st.session_state.edit_index + 1}")

    with st.form("manual_bond_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            bid = st.text_input("ID / ISIN", value=str(fd.get("id", "OBL001")))
            emetteur = st.text_input("Émetteur", value=str(fd.get("emetteur", "Emetteur")))
            btype = st.selectbox("Type", BOND_TYPES, index=BOND_TYPES.index(fd.get("type", "Obligation à taux fixe in fine")) if fd.get("type") in BOND_TYPES else 1)
        with c2:
            issue = st.date_input("Date émission", value=pd.to_datetime(fd.get("date_emission")).date())
            mat = st.date_input("Date échéance", value=pd.to_datetime(fd.get("date_echeance")).date())
            nominal = st.number_input("Nominal utilisé", value=float(fd.get("nominal_utilise", fd.get("nominal", 100000.0))), min_value=0.0)
            crd_manual = st.number_input(
                "CRD manuel amortissable",
                value=float(fd.get("capital_restant_du_manuel", 0.0) or 0.0),
                min_value=0.0,
                help="Optionnel. Pour les obligations amortissables, ce montant pilote les intérêts courus ET l'échéancier futur restant en amortissement constant restant."
            )
            type_nominal = st.text_input("Type nominal / justification", value=str(fd.get("type_nominal", "Manuel / standard")))
        with c3:
            qty = st.number_input("Quantité", value=float(fd.get("quantite", 1.0)), min_value=0.0)
            coupon = st.number_input("Coupon annuel / taux Maroclear %", value=float(fd.get("taux_coupon_pct", 2.5)), step=0.01)
            freq = st.selectbox("Fréquence coupon", FREQS, index=FREQS.index(fd.get("frequence", "Annuelle")) if fd.get("frequence") in FREQS else 0)

        st.markdown("### Dates avancées : jouissance, premier coupon, coupon courant")
        d1, d2, d3, d4 = st.columns(4)
        jouissance = d1.date_input("Date de jouissance", value=pd.to_datetime(fd.get("date_jouissance", fd.get("date_emission"))).date())
        coupon_mode = d2.selectbox(
            "Mode calendrier coupon",
            ["Depuis échéance vers arrière", "Depuis premier coupon vers avant", "Coupons précédent/prochain saisis"],
            index=["Depuis échéance vers arrière", "Depuis premier coupon vers avant", "Coupons précédent/prochain saisis"].index(fd.get("mode_calendrier_coupon", "Depuis échéance vers arrière")) if fd.get("mode_calendrier_coupon", "Depuis échéance vers arrière") in ["Depuis échéance vers arrière", "Depuis premier coupon vers avant", "Coupons précédent/prochain saisis"] else 0,
        )
        first_coupon_default = pd.to_datetime(fd.get("date_premier_coupon", fd.get("date_echeance")), errors="coerce")
        first_coupon = d3.date_input("Date premier coupon", value=(first_coupon_default.date() if not pd.isna(first_coupon_default) else mat), disabled=coupon_mode != "Depuis premier coupon vers avant")
        prev_coupon_default = pd.to_datetime(fd.get("date_coupon_precedent", fd.get("date_emission")), errors="coerce")
        next_coupon_default = pd.to_datetime(fd.get("date_prochain_coupon", fd.get("date_echeance")), errors="coerce")
        prev_coupon = d4.date_input("Coupon précédent saisi", value=(prev_coupon_default.date() if not pd.isna(prev_coupon_default) else issue), disabled=coupon_mode != "Coupons précédent/prochain saisis")
        next_coupon = st.date_input("Prochain coupon saisi", value=(next_coupon_default.date() if not pd.isna(next_coupon_default) else mat), disabled=coupon_mode != "Coupons précédent/prochain saisis")

        if issue > mat:
            st.error("Erreur date : la date d'émission est postérieure à l'échéance.")
        if jouissance > mat:
            st.error("Erreur date : la date de jouissance est postérieure à l'échéance.")
        if coupon_mode == "Depuis premier coupon vers avant" and first_coupon < jouissance:
            st.warning("Premier coupon antérieur à la jouissance : vérifier la structure de ligne.")
        if settlement_date < valuation_date:
            st.warning("Date de règlement inférieure à la date de valorisation.")

        st.markdown("### Contrôle AMMC")
        ammc1, ammc2 = st.columns(2)
        nature_ligne = ammc1.selectbox(
            "Nature de ligne",
            ["Ligne normale", "Ligne postérieure"],
            index=["Ligne normale", "Ligne postérieure"].index(fd.get("nature_ligne", "Ligne normale")) if fd.get("nature_ligne", "Ligne normale") in ["Ligne normale", "Ligne postérieure"] else 0,
            help="Permet d'appliquer les formules AMMC spécifiques aux lignes postérieures."
        )
        structure_confirmee = ammc2.checkbox(
            "Structure de flux confirmée",
            value=bool(fd.get("structure_flux_confirmee", False)),
            help="Obligatoire pour considérer les FPCT/amortissables complexes comme conformes."
        )
        autoriser_coupon_long = st.checkbox(
            "Autoriser coupon long contractuel",
            value=bool(fd.get("autoriser_coupon_long_contractuel", False)),
            help="À cocher seulement si la note d'information confirme un premier coupon long. Sinon l'app insère des dates intermédiaires régulières pour éviter un coupon artificiellement gonflé."
        )

        st.markdown("### Spreads décomposés")
        s1, s2, s3, s4, s5 = st.columns(5)
        spread_credit = s1.number_input("Crédit bps", value=float(fd.get("spread_credit_bps", 0.0)), step=1.0)
        spread_liq = s2.number_input("Liquidité bps", value=float(fd.get("spread_liquidite_bps", 0.0)), step=1.0)
        spread_sub = s3.number_input("Subordination bps", value=float(fd.get("spread_subordination_bps", 0.0)), step=1.0)
        spread_spec = s4.number_input("Spécifique bps", value=float(fd.get("spread_specifique_bps", 0.0)), step=1.0)
        spread_mkt = s5.number_input("Ajustement marché bps", value=float(fd.get("ajustement_marche_bps", 0.0)), step=1.0)

        st.markdown("### Conventions")
        v1, v2, v3, v4, v5 = st.columns(5)
        tax = v1.number_input("Retenue à la source %", value=float(fd.get("tax_pct", 0.0)), min_value=0.0, max_value=100.0)
        base_coupon = v2.selectbox("Base coupon", DAY_COUNT, index=DAY_COUNT.index(fd.get("base_coupon", "ACT/365")) if fd.get("base_coupon") in DAY_COUNT else 0)
        base_disc = v3.selectbox("Base actualisation", DAY_COUNT, index=DAY_COUNT.index(fd.get("base_actualisation", "ACT/365")) if fd.get("base_actualisation") in DAY_COUNT else 0)
        interp = v4.selectbox("Interpolation", INTERP)
        mode_actualisation = v5.selectbox("Mode actualisation", COMPOUNDING, index=COMPOUNDING.index(fd.get("mode_actualisation", "Actuarielle annuelle")) if fd.get("mode_actualisation", "Actuarielle annuelle") in COMPOUNDING else 0)

        use_mkt = st.checkbox("Comparer avec prix clean marché", value=bool(fd.get("utiliser_prix_marche", False)))
        mkt_px = st.number_input("Prix clean marché %", value=float(fd.get("prix_clean_marche_pct", 100.0) if not pd.isna(fd.get("prix_clean_marche_pct", np.nan)) else 100.0), disabled=not use_mkt)

        pmode_col1, pmode_col2 = st.columns(2)
        mode_pricing = pmode_col1.selectbox(
            "Mode pricing",
            ["Courbe BAM / AMMC", "YTM fourni / gérant"],
            index=1 if fd.get("mode_pricing", "Courbe BAM / AMMC") == "YTM fourni / gérant" else 0,
            help="Le mode YTM fourni sert à réconcilier un pricer externe sans ajustement artificiel de spread."
        )
        taux_ytm_fourni = pmode_col2.number_input(
            "YTM fourni / gérant %",
            value=float(fd.get("taux_ytm_fourni_pct", 0.0) or 0.0),
            step=0.001,
            disabled=mode_pricing != "YTM fourni / gérant"
        )

        st.markdown("### Taux variable fiable : fixing, reset et projection")
        tv1, tv2, tv3, tv4 = st.columns(4)
        marge = tv1.number_input("Marge contractuelle bps", value=float(fd.get("marge_bps", 0.0)), step=1.0)
        ref_mode = tv2.selectbox("Mode référence", ["Courbe BAM interpolée", "Taux de référence manuel constant"], index=0 if fd.get("mode_ref_variable", "Courbe BAM interpolée") == "Courbe BAM interpolée" else 1)
        taux_ref = tv3.number_input("Taux ref manuel %", value=float(fd.get("taux_ref_manuel_pct", 2.5)), step=0.01)
        coupon_current = tv4.number_input("Coupon courant déjà fixé %", value=float(fd.get("coupon_courant_fixe_pct", 0.0)), step=0.01)

        vm1, vm2, vm3, vm4 = st.columns(4)
        variable_projection = vm1.selectbox(
            "Mode projection coupons futurs",
            [
                "FRN par au prochain reset recommandé",
                "Coupon courant fixé puis projection courbe",
                "FRN complet projeté courbe + marge",
                "Coupon courant constant jusqu'échéance",
                "Taux Maroclear/coupon facial constant",
                "Taux référence manuel constant + marge",
                "Projection forwards + marge",
                "Courbe BAM + marge",
            ],
            index=[
                "FRN par au prochain reset recommandé",
                "Coupon courant fixé puis projection courbe",
                "FRN complet projeté courbe + marge",
                "Coupon courant constant jusqu'échéance",
                "Taux Maroclear/coupon facial constant",
                "Taux référence manuel constant + marge",
                "Projection forwards + marge",
                "Courbe BAM + marge",
            ].index(fd.get("mode_projection_variable", "FRN par au prochain reset recommandé")) if fd.get("mode_projection_variable", "FRN par au prochain reset recommandé") in [
                "FRN par au prochain reset recommandé",
                "Coupon courant fixé puis projection courbe",
                "FRN complet projeté courbe + marge",
                "Coupon courant constant jusqu'échéance",
                "Taux Maroclear/coupon facial constant",
                "Taux référence manuel constant + marge",
                "Projection forwards + marge",
                "Courbe BAM + marge",
            ] else 0,
        )
        reset_freq = vm2.selectbox("Fréquence reset", FREQS, index=FREQS.index(fd.get("frequence_reset", "Annuelle")) if fd.get("frequence_reset", "Annuelle") in FREQS else 0)
        tenor_ref = vm3.selectbox("Tenor référence jours", [91, 182, 364, 365, 730, 1825], index=2)
        vm4.caption("Le coupon courant s'applique au premier flux futur si renseigné.")

        fx1, fx2, am1, am2 = st.columns(4)
        last_fixing_default = pd.to_datetime(fd.get("date_dernier_fixing", fd.get("date_emission")), errors="coerce")
        next_fixing_default = pd.to_datetime(fd.get("date_prochain_fixing", fd.get("date_echeance")), errors="coerce")
        last_fixing = fx1.date_input("Date dernier fixing", value=(last_fixing_default.date() if not pd.isna(last_fixing_default) else issue))
        next_fixing = fx2.date_input("Date prochain fixing", value=(next_fixing_default.date() if not pd.isna(next_fixing_default) else mat))
        amort_mode = am1.selectbox("Mode amortissement", ["Amortissement constant", "In fine", "Annuités constantes", "Différé d’amortissement / CRD obligatoire"])
        option_val = am2.number_input("Valeur option % nominal", value=float(fd.get("valeur_option_pct", 0.0)), step=0.1)

        submitted = st.form_submit_button("✅ Mettre à jour" if edit_mode else "➕ Ajouter au portefeuille", use_container_width=True)

    if submitted:
        row = default_bond_dict(bid)
        row.update({
            "id": bid, "source": fd.get("source", "Manuel"), "emetteur": emetteur, "type": btype,
            "date_emission": issue.isoformat(), "date_jouissance": jouissance.isoformat(), "date_echeance": mat.isoformat(),
            "mode_calendrier_coupon": coupon_mode,
            "autoriser_coupon_long_contractuel": autoriser_coupon_long,
            "nature_ligne": nature_ligne,
            "structure_flux_confirmee": structure_confirmee,
            "date_premier_coupon": first_coupon.isoformat() if coupon_mode == "Depuis premier coupon vers avant" else "",
            "date_coupon_precedent": prev_coupon.isoformat() if coupon_mode == "Coupons précédent/prochain saisis" else "",
            "date_prochain_coupon": next_coupon.isoformat() if coupon_mode == "Coupons précédent/prochain saisis" else "",
            "nominal": nominal, "nominal_utilise": nominal, "capital_restant_du_manuel": crd_manual, "type_nominal": type_nominal,
            "nominal_total_detenu": nominal * qty,
            "quantite": qty, "taux_coupon_pct": coupon, "frequence": freq,
            "spread_credit_bps": spread_credit, "spread_liquidite_bps": spread_liq,
            "spread_subordination_bps": spread_sub, "spread_specifique_bps": spread_spec,
            "ajustement_marche_bps": spread_mkt, "tax_pct": tax,
            "base_coupon": base_coupon, "base_actualisation": base_disc, "mode_actualisation": mode_actualisation, "interpolation": interp,
            "mode_pricing": mode_pricing, "taux_ytm_fourni_pct": taux_ytm_fourni,
            "utiliser_prix_marche": use_mkt, "prix_clean_marche_pct": mkt_px if use_mkt else np.nan,
            "marge_bps": marge, "mode_ref_variable": ref_mode, "mode_projection_variable": variable_projection,
            "frequence_reset": reset_freq, "date_dernier_fixing": last_fixing.isoformat(),
            "date_prochain_fixing": next_fixing.isoformat(),
            "taux_ref_manuel_pct": taux_ref,
            "coupon_courant_fixe_pct": coupon_current, "mode_amortissement": amort_mode,
            "valeur_option_pct": option_val, "tenor_ref_jours": tenor_ref,
        })
        if edit_mode:
            st.session_state.portfolio[st.session_state.edit_index] = row
            st.session_state.edit_index = None
            st.session_state.form_defaults = default_bond_dict()
        else:
            st.session_state.portfolio.append(row)

        try:
            preview_inputs = dict_to_inputs(row, global_settings)
            preview_m, preview_cf, preview_accrued = compute_metrics(preview_inputs, curve_snapshot)
            st.session_state.last_manual_preview = {
                "id": row.get("id", ""),
                "dirty_price": preview_m.get("dirty_price"),
                "clean_price": preview_m.get("clean_price"),
                "accrued_interest": preview_accrued.get("accrued_interest"),
                "ytm": preview_m.get("ytm"),
                "formule_ammc": preview_m.get("formule_ammc", ""),
                "conformite_ammc": preview_m.get("conformite_ammc", ""),
                "message_conformite": preview_m.get("message_conformite", ""),
            }
        except Exception as e:
            st.session_state.last_manual_preview = {"id": row.get("id", ""), "error": str(e)}

        st.success("Ligne enregistrée. Résultat calculé ci-dessous.")



    if st.session_state.get("last_manual_preview"):
        prev = st.session_state.last_manual_preview
        st.markdown("### Résultat immédiat")
        if prev.get("error"):
            st.error(prev["error"])
        else:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Dirty price", fmt_dh(prev.get("dirty_price")))
            r2.metric("Clean price", fmt_dh(prev.get("clean_price")))
            r3.metric("Intérêts courus", fmt_dh(prev.get("accrued_interest")))
            r4.metric("YTM", fmt_pct(prev.get("ytm")))
            if prev.get("formule_ammc"):
                st.caption(f"Formule : {prev.get('formule_ammc')}")
            st.caption(f"Conformité : {prev.get('conformite_ammc', '-')}. {prev.get('message_conformite', '')}")
        if st.button("🔄 Rafraîchir tout le portefeuille", use_container_width=True):
            st.rerun()

    st.divider()
    st.markdown("### Échéancier et taux variables")
    st.info(
        "Pour éviter de surcharger la saisie, l’échéancier se modifie maintenant directement "
        "dans l’onglet Valorisation détaillée, après sélection du titre concerné. "
        "Chaque titre garde son propre échéancier ou sa propre table de taux."
    )
    st.caption(
        "Utilisez cette logique surtout pour les FPCT, titres amortissables, titres structurés "
        "et obligations à taux variable dont les coupons futurs doivent être confirmés."
    )


# -------------------------------------------------------------------
# 6. Valorisation détaillée
# -------------------------------------------------------------------
with tabs[5]:
    st.subheader("Valorisation détaillée")
    if not st.session_state.portfolio:
        st.info("Portefeuille vide.")
    else:
        labels = [f"{i+1} - {b.get('id')} - {b.get('type')}" for i, b in enumerate(st.session_state.portfolio)]
        sel = st.selectbox("Choisir une ligne", labels, key="detail_selected_bond")
        idx = labels.index(sel)
        b = st.session_state.portfolio[idx]
        inputs = dict_to_inputs(b, global_settings)

        active_custom = st.session_state.custom_schedules.get(inputs.id)
        active_var_table = st.session_state.variable_tables.get(inputs.id)

        m, cf, accrued = compute_metrics(
            inputs, curve_snapshot,
            custom_schedule=active_custom,
            variable_rates_table=active_var_table
        )

        a, b1, c, d = st.columns(4)
        a.metric("Dirty price", fmt_dh(m["dirty_price"]))
        b1.metric("Clean price", fmt_dh(m["clean_price"]))
        c.metric("YTM", fmt_pct(m["ytm"]))
        d.metric("PVBP", fmt_dh(m["pvbp"]))

        if m.get("formule_ammc"):
            st.info(f"Méthode appliquée : {m.get('formule_ammc')}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Prix retenu", fmt_dh(m.get("dirty_price")))
            c2.metric("Taux AMMC", fmt_pct(m.get("taux_ammc")))
            c3.metric("Coupon unitaire", fmt_dh(m.get("coupon_unitaire_ammc")))
        st.caption(f"Statut conformité : {m.get('conformite_ammc', '-')}. {m.get('message_conformite', '')}")

        st.markdown("### Intérêts courus")
        st.dataframe(pd.DataFrame([accrued]), use_container_width=True, hide_index=True)

        with st.expander("Audit du calcul des intérêts courus", expanded=False):
            audit_rows = [{
                "Nominal utilisé": inputs.nominal,
                "Taux coupon courant utilisé": accrued.get("current_coupon_rate"),
                "Date coupon précédent": accrued.get("last_coupon"),
                "Date prochain coupon": accrued.get("next_coupon"),
                "Fraction courue": accrued.get("yf_accrued"),
                "Fraction période": accrued.get("yf_period"),
                "Intérêts courus": accrued.get("accrued_interest"),
            }]
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)
            st.code(
                "Intérêts courus = Nominal utilisé × Taux coupon courant × Fraction courue",
                language="text"
            )

        st.markdown("### Cash-flows")
        st.dataframe(cf, use_container_width=True, hide_index=True)
        if not cf.empty:
            fig = pex.bar(cf, x="date_flux", y=["coupon_brut", "principal"], title="Flux coupon / principal")
            st.plotly_chart(fig, use_container_width=True)

        is_variable = b.get("type") == "Obligation à taux révisable / variable"
        is_fpct = str(b.get("categorie_maroclear", "")).upper() == "FPCT"
        is_amort = b.get("type") == "Obligation amortissable"
        is_structured = is_fpct or is_amort or b.get("type") in [
            "Obligation convertible simplifiée",
            "Obligation callable simplifiée",
            "Obligation puttable simplifiée",
        ]

        st.divider()
        st.markdown("### Paramètres spécifiques du titre sélectionné")

        if is_variable:
            with st.expander("Taux variable : modifier fixing, reset et projection", expanded=True):
                p1, p2, p3, p4 = st.columns(4)
                new_prev_coupon = p1.date_input(
                    "Coupon précédent",
                    value=_safe_date_from_value(b.get("date_coupon_precedent"), inputs.issue_date),
                    key=f"var_prev_coupon_{inputs.id}"
                )
                new_next_coupon = p2.date_input(
                    "Prochain coupon / reset",
                    value=_safe_date_from_value(b.get("date_prochain_coupon"), inputs.maturity_date),
                    key=f"var_next_coupon_{inputs.id}"
                )
                new_current_coupon = p3.number_input(
                    "Coupon courant fixé %",
                    value=float(b.get("coupon_courant_fixe_pct", b.get("taux_coupon_pct", 0.0)) or 0.0),
                    step=0.01,
                    key=f"var_current_coupon_{inputs.id}"
                )
                new_margin = p4.number_input(
                    "Marge contractuelle bps",
                    value=float(b.get("marge_bps", 0.0) or 0.0),
                    step=1.0,
                    key=f"var_margin_{inputs.id}"
                )

                mode_options = [
                    "FRN par au prochain reset recommandé",
                    "Coupon courant fixé puis projection courbe",
                    "FRN complet projeté courbe + marge",
                    "Coupon courant constant jusqu'échéance",
                    "Taux Maroclear/coupon facial constant",
                    "Taux référence manuel constant + marge",
                    "Courbe BAM + marge",
                ]
                p5, p6, p7 = st.columns(3)
                new_mode = p5.selectbox(
                    "Mode de projection",
                    mode_options,
                    index=mode_options.index(b.get("mode_projection_variable", "FRN par au prochain reset recommandé")) if b.get("mode_projection_variable", "FRN par au prochain reset recommandé") in mode_options else 0,
                    key=f"var_mode_{inputs.id}"
                )
                new_tenor = p6.selectbox(
                    "Tenor référence jours",
                    [91, 182, 364, 365, 730, 1825],
                    index=[91, 182, 364, 365, 730, 1825].index(int(b.get("tenor_ref_jours", 364))) if int(float(b.get("tenor_ref_jours", 364) or 364)) in [91, 182, 364, 365, 730, 1825] else 2,
                    key=f"var_tenor_{inputs.id}"
                )
                new_reset = p7.selectbox(
                    "Fréquence reset",
                    FREQS,
                    index=FREQS.index(b.get("frequence_reset", b.get("frequence", "Annuelle"))) if b.get("frequence_reset", b.get("frequence", "Annuelle")) in FREQS else 0,
                    key=f"var_reset_{inputs.id}"
                )

                if st.button("Appliquer ces paramètres au titre", use_container_width=True, key=f"apply_var_params_{inputs.id}"):
                    st.session_state.portfolio[idx].update({
                        "mode_calendrier_coupon": "Coupons précédent/prochain saisis",
                        "date_coupon_precedent": new_prev_coupon.isoformat(),
                        "date_prochain_coupon": new_next_coupon.isoformat(),
                        "coupon_courant_fixe_pct": new_current_coupon,
                        "marge_bps": new_margin,
                        "mode_projection_variable": new_mode,
                        "tenor_ref_jours": new_tenor,
                        "frequence_reset": new_reset,
                    })
                    st.success("Paramètres du taux variable mis à jour.")
                    st.rerun()

            with st.expander("Table de taux variables du titre", expanded=False):
                st.caption(
                    "Renseignez coupon_total_pct si le coupon total par période est connu. "
                    "Sinon renseignez taux_reference_pct : la marge contractuelle sera ajoutée."
                )
                table_key = f"var_table_editor_{inputs.id}"
                if table_key not in st.session_state:
                    if active_var_table is not None and not active_var_table.empty:
                        base_var = active_var_table.copy()
                        if "note" not in base_var.columns:
                            base_var["note"] = "personnalisé"
                        st.session_state[table_key] = base_var
                    else:
                        st.session_state[table_key] = make_variable_table_default(b, global_settings)

                edited_var_table = st.data_editor(
                    st.session_state[table_key],
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"var_table_widget_{inputs.id}",
                    column_config={
                        "date_flux": st.column_config.TextColumn("Date flux"),
                        "taux_reference_pct": st.column_config.TextColumn("Taux référence %"),
                        "coupon_total_pct": st.column_config.NumberColumn("Coupon total %", step=0.01),
                        "note": st.column_config.TextColumn("Note"),
                    }
                )
                vt1, vt2 = st.columns(2)
                if vt1.button("Utiliser cette table de taux", use_container_width=True, key=f"save_var_table_{inputs.id}"):
                    clean_vt = edited_var_table.copy()
                    clean_vt["date_flux"] = pd.to_datetime(clean_vt["date_flux"], errors="coerce").dt.strftime("%Y-%m-%d")
                    if "coupon_total_pct" in clean_vt.columns:
                        clean_vt["coupon_total_pct"] = pd.to_numeric(clean_vt["coupon_total_pct"], errors="coerce")
                    if "taux_reference_pct" in clean_vt.columns:
                        clean_vt["taux_reference_pct"] = pd.to_numeric(clean_vt["taux_reference_pct"], errors="coerce")
                    clean_vt = clean_vt.dropna(subset=["date_flux"])
                    st.session_state.variable_tables[inputs.id] = clean_vt
                    st.success("Table de taux variables activée pour ce titre.")
                    st.rerun()
                if vt2.button("Supprimer la table de taux", use_container_width=True, key=f"clear_var_table_{inputs.id}"):
                    st.session_state.variable_tables.pop(inputs.id, None)
                    st.session_state.pop(table_key, None)
                    st.success("Table de taux supprimée.")
                    st.rerun()

        show_flux_editor = is_structured or st.checkbox(
            "Modifier l’échéancier de flux de ce titre",
            value=False,
            key=f"show_flux_editor_{inputs.id}"
        )

        if show_flux_editor:
            with st.expander("Échéancier de flux du titre sélectionné", expanded=is_fpct or is_amort):
                if is_fpct:
                    st.warning("FPCT : confirmez la structure de flux avant de considérer le prix comme validé.")

                gen1, gen2, gen3 = st.columns(3)
                quick_mode = gen1.selectbox(
                    "Génération rapide",
                    ["À partir des flux calculés", "In fine", "Amortissement constant", "Zéro coupon", "Manuel vide"],
                    key=f"quick_flux_mode_{inputs.id}"
                )
                include_coupon = gen2.checkbox("Inclure coupons", value=True, key=f"quick_flux_coupon_{inputs.id}")
                round_flux = gen3.checkbox("Arrondir montants", value=False, key=f"quick_flux_round_{inputs.id}")

                flux_key = f"flux_editor_{inputs.id}"
                if st.button("Préparer le tableau", use_container_width=True, key=f"prepare_flux_{inputs.id}"):
                    if quick_mode == "À partir des flux calculés":
                        st.session_state[flux_key] = make_flux_editor_default(
                            b, global_settings, curve_snapshot, st.session_state.custom_schedules.get(inputs.id)
                        )
                    else:
                        try:
                            inputs_tmp = dict_to_inputs(b, global_settings)
                            full_schedule = generate_coupon_schedule(inputs_tmp)
                            future_dates = [d for d in full_schedule if d > settlement_date]
                            if not future_dates and inputs_tmp.maturity_date > settlement_date:
                                future_dates = [inputs_tmp.maturity_date]
                            n = max(len(future_dates), 1)
                            outstanding = float(inputs_tmp.nominal)
                            rows = []
                            for i, dte in enumerate(future_dates, start=1):
                                prev_d = get_previous_coupon_date(full_schedule, dte, inputs_tmp.accrual_start_date or inputs_tmp.issue_date)
                                yf = year_fraction(prev_d, dte, inputs_tmp.day_count_coupon, inputs_tmp.frequency, prev_d, dte)
                                coupon_amt = 0.0
                                principal_amt = 0.0
                                if quick_mode == "Manuel vide":
                                    pass
                                elif quick_mode == "Zéro coupon":
                                    principal_amt = outstanding if i == n else 0.0
                                elif quick_mode == "In fine":
                                    coupon_amt = outstanding * inputs_tmp.coupon_rate * yf if include_coupon else 0.0
                                    principal_amt = outstanding if i == n else 0.0
                                elif quick_mode == "Amortissement constant":
                                    amort = inputs_tmp.nominal / n
                                    coupon_amt = outstanding * inputs_tmp.coupon_rate * yf if include_coupon else 0.0
                                    principal_amt = min(amort, outstanding)
                                    outstanding = max(0.0, outstanding - principal_amt)
                                if round_flux:
                                    coupon_amt = round(coupon_amt, 2)
                                    principal_amt = round(principal_amt, 2)
                                rows.append({
                                    "date_flux": dte.isoformat(),
                                    "coupon": coupon_amt,
                                    "principal": principal_amt,
                                    "type_flux": quick_mode,
                                })
                            st.session_state[flux_key] = pd.DataFrame(rows)
                        except Exception as e:
                            st.error(f"Erreur génération : {e}")

                if flux_key not in st.session_state:
                    st.session_state[flux_key] = make_flux_editor_default(
                        b, global_settings, curve_snapshot, st.session_state.custom_schedules.get(inputs.id)
                    )

                edited_flux = st.data_editor(
                    st.session_state[flux_key],
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"flux_editor_widget_{inputs.id}",
                    column_config={
                        "date_flux": st.column_config.TextColumn("Date flux"),
                        "coupon": st.column_config.NumberColumn("Coupon", step=0.01),
                        "principal": st.column_config.NumberColumn("Principal", step=0.01),
                        "type_flux": st.column_config.TextColumn("Type flux"),
                    }
                )

                f1, f2 = st.columns(2)
                if f1.button("Utiliser cet échéancier", use_container_width=True, key=f"save_flux_{inputs.id}"):
                    clean_flux = edited_flux.copy()
                    clean_flux["date_flux"] = pd.to_datetime(clean_flux["date_flux"], errors="coerce").dt.strftime("%Y-%m-%d")
                    clean_flux["coupon"] = pd.to_numeric(clean_flux["coupon"], errors="coerce").fillna(0.0)
                    clean_flux["principal"] = pd.to_numeric(clean_flux["principal"], errors="coerce").fillna(0.0)
                    clean_flux = clean_flux.dropna(subset=["date_flux"])
                    keep_cols = ["date_flux", "coupon", "principal"] + (["type_flux"] if "type_flux" in clean_flux.columns else [])
                    st.session_state.custom_schedules[inputs.id] = clean_flux[keep_cols]
                    st.session_state.portfolio[idx]["structure_flux_confirmee"] = True
                    st.success("Échéancier activé et structure confirmée pour ce titre.")
                    st.rerun()

                if f2.button("Supprimer l’échéancier", use_container_width=True, key=f"clear_flux_{inputs.id}"):
                    st.session_state.custom_schedules.pop(inputs.id, None)
                    st.session_state.pop(flux_key, None)
                    st.success("Échéancier supprimé.")
                    st.rerun()
# -------------------------------------------------------------------
# 7. Risques & stress tests
# -------------------------------------------------------------------
with tabs[6]:
    st.subheader("Risques & stress tests")
    if summary_df.empty:
        st.info("Aucune valorisation.")
    else:
        rc = risk_contributions(add_maturity_buckets(summary_df, valuation_date))
        st.markdown("### Contributions au risque")
        st.dataframe(rc, use_container_width=True, hide_index=True)

        scenarios = [
            {"name": "Base", "parallel_bps": 0, "short_bps": 0, "long_bps": 0},
            {"name": "+100 bps parallèle", "parallel_bps": 100, "short_bps": 0, "long_bps": 0},
            {"name": "-100 bps parallèle", "parallel_bps": -100, "short_bps": 0, "long_bps": 0},
            {"name": "Steepening", "parallel_bps": 0, "short_bps": -50, "long_bps": 50},
            {"name": "Flattening", "parallel_bps": 0, "short_bps": 50, "long_bps": -50},
            {"name": "Stress crédit +50", "parallel_bps": 0, "short_bps": 0, "long_bps": 0, "credit_bps": 50},
        ]
        scen = scenario_portfolio(st.session_state.portfolio, global_settings, curve_snapshot, scenarios, st.session_state.custom_schedules, st.session_state.variable_tables)
        st.dataframe(scen, use_container_width=True, hide_index=True)
        fig = pex.bar(scen, x="scenario", y="variation_valeur", title="Impact des scénarios")
        st.plotly_chart(fig, use_container_width=True)


# -------------------------------------------------------------------
# 8. Contrôles
# -------------------------------------------------------------------
with tabs[7]:
    st.subheader("Contrôles qualité et limites")
    st.markdown("### Alertes sur les lignes")
    if alerts_df.empty:
        st.success("Aucune alerte critique détectée.")
    else:
        st.dataframe(alerts_df, use_container_width=True, hide_index=True)

    st.markdown("### Limites de risque")
    l1,l2,l3,l4 = st.columns(4)
    duration_max = l1.number_input("Duration max", value=8.0)
    pvbp_max = l2.number_input("PVBP max", value=1_000_000.0)
    issuer_max = l3.number_input("Poids max par émetteur", value=0.35)
    line_max = l4.number_input("Poids max par ligne", value=0.25)
    limit_df = validate_limits(summary_df, {
        "duration_max": duration_max, "pvbp_max": pvbp_max,
        "poids_emetteur_max": issuer_max, "poids_ligne_max": line_max
    })
    st.dataframe(limit_df, use_container_width=True, hide_index=True)




    st.markdown("### Contrôle AMMC par titre")
    ammc_cols = [c for c in ["id", "emetteur", "type", "nature_ligne", "conformite_ammc", "formule_ammc", "taux_ammc", "Mi_jours", "Mr_jours", "nj_jours", "coupon_long_count", "coupon_long_non_confirme_count", "amortissement_principal_gap", "dirty_price", "clean_price", "message_conformite"] if c in summary_df.columns]
    if ammc_cols:
        st.dataframe(summary_df[ammc_cols], use_container_width=True, hide_index=True)

# -------------------------------------------------------------------
# 10. Exports
# -------------------------------------------------------------------
with tabs[8]:
    st.subheader("Exports")
    raw = portfolio_to_dataframe(st.session_state.portfolio)
    rc = risk_contributions(add_maturity_buckets(summary_df, valuation_date)) if not summary_df.empty else pd.DataFrame()
    scen = scenario_portfolio(st.session_state.portfolio, global_settings, curve_snapshot, [
        {"name": "Base", "parallel_bps": 0, "short_bps": 0, "long_bps": 0},
        {"name": "+100 bps", "parallel_bps": 100, "short_bps": 0, "long_bps": 0},
        {"name": "-100 bps", "parallel_bps": -100, "short_bps": 0, "long_bps": 0},
        {"name": "Steepening", "parallel_bps": 0, "short_bps": -50, "long_bps": 50},
        {"name": "Flattening", "parallel_bps": 0, "short_bps": 50, "long_bps": -50},
    ], st.session_state.custom_schedules, st.session_state.variable_tables) if st.session_state.portfolio else pd.DataFrame()

    hidden_compare_cols = ["dirty_price_dcf", "prix_ammc", "prix_net_ammc", "ecart_app_vs_dcf", "methode_pricing_active"]
    summary_export = summary_df.drop(columns=[c for c in hidden_compare_cols if c in summary_df.columns]) if not summary_df.empty else summary_df

    sheets = {
        "Parametres": pd.DataFrame([{"valuation_date": valuation_date, "settlement_date": settlement_date, "curve_date": desired_curve_date, "curve_msg": curve_msg}]),
        "Portefeuille_saisi": raw,
        "Resume_valorisation": summary_export,
        "Cashflows": all_cf_df,
        "Contributions_risque": rc,
        "Alertes": alerts_df,
        "Erreurs": errors_df,
        "Scenarios": scen,
        "Courbe_BAM": curve_snapshot,
    }
    simplified_export = build_simplified_export(summary_df)
    simplified_sheets = {"Export_simplifie": simplified_export}

    if curve_is_sample(curve_snapshot):
        st.error("Export bloqué : la courbe active est l’échantillon local. Uploadez une vraie courbe BAM pour exporter une valorisation fiable.")
    else:
        st.download_button("⬇️ Télécharger l’export Excel complet", data=excel_bytes(sheets), file_name="valorisation_obligataire_maroc_v16.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        st.download_button("⬇️ Télécharger l’export simplifié Excel", data=excel_bytes(simplified_sheets), file_name="export_simplifie_valorisation_v16.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        try:
            pdf_simple = pdf_simplified_report_bytes(
                "Export simplifié - Dirty price et taux utilisé",
                simplified_export,
                parameters={
                    "Date de valorisation": valuation_date,
                    "Date de règlement": settlement_date,
                    "Nombre de titres": len(st.session_state.portfolio),
                },
            )
            st.download_button("📄 Télécharger l’export simplifié PDF", data=pdf_simple, file_name="export_simplifie_valorisation_v16.pdf", mime="application/pdf", use_container_width=True)
        except Exception as e:
            st.warning(f"PDF simplifié indisponible : {e}")

    if st.button("📌 Enregistrer valorisation du jour"):
        path = save_valuation_history(summary_df, kpis, valuation_date)
        st.success(f"Historique sauvegardé : {path}")

    hist = list_valuation_history()
    st.markdown("### Historique des valorisations")
    st.dataframe(hist, use_container_width=True, hide_index=True)

    if st.button("📄 Générer le rapport PDF détaillé"):
        try:
            if curve_is_sample(curve_snapshot):
                st.error("Rapport bloqué : la courbe active est l’échantillon local. Uploadez une vraie courbe BAM.")
                st.stop()
            pdf = pdf_report_bytes(
                "Rapport de valorisation obligataire Maroc",
                kpis,
                summary_export,
                alerts_df,
                curve_df=curve_snapshot,
                errors_df=errors_df,
                scenarios_df=scen,
                risk_df=rc,
                cashflows_df=all_cf_df,
                parameters={
                    "Date de valorisation": valuation_date,
                    "Date de règlement": settlement_date,
                    "Date courbe demandée": desired_curve_date,
                    "Statut courbe": curve_msg,
                    "Nombre de titres": len(st.session_state.portfolio),
                },
            )
            st.download_button("Télécharger le rapport PDF détaillé", data=pdf, file_name="rapport_valorisation_obligataire_v16.pdf", mime="application/pdf")
        except Exception as e:
            st.error(str(e))
