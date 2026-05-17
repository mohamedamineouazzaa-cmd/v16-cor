
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import re
import unicodedata
from datetime import date
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd


DEBT_CATEGORIES = {
    "BDT", "OBL_ORDN", "OBL_SUBD", "OBL_CONV", "TCN", "FPCT",
    "BDT_INT", "OBL", "OBLIG", "BOND"
}

INTEREST_TYPE_MAP = {
    "FIXD": "Obligation à taux fixe in fine",
    "FIXE": "Obligation à taux fixe in fine",
    "FLTG": "Obligation à taux révisable / variable",
    "FLOT": "Obligation à taux révisable / variable",
    "VAR": "Obligation à taux révisable / variable",
    "DISC": "BDT / zéro coupon court terme",
    "ZC": "BDT / zéro coupon court terme",
}

INSTR_TYPE_MAP = {
    "FRBD": "Obligation à taux fixe in fine",
    "FLRT": "Obligation à taux révisable / variable",
    "AMBD": "Obligation amortissable",
    "ZCBD": "BDT / zéro coupon court terme",
}

CATEGORY_TYPE_OVERRIDES = {
    "OBL_SUBD": "Obligation subordonnée",
    "OBL_CONV": "Obligation convertible simplifiée",
    "BDT": "Obligation à taux fixe in fine",
    "TCN": "Obligation à taux fixe in fine",
    "FPCT": "Obligation amortissable",
}

FREQ_MAP_MAROCLEAR = {
    "ANNUAL": "Annuelle", "YEARLY": "Annuelle", "ANNUEL": "Annuelle", "ANLY": "Annuelle", "1": "Annuelle",
    "SEMIANNUAL": "Semestrielle", "SEMI_ANNUAL": "Semestrielle", "SEMESTRIEL": "Semestrielle", "HFLY": "Semestrielle", "2": "Semestrielle",
    "QUARTERLY": "Trimestrielle", "TRIMESTRIEL": "Trimestrielle", "QTLY": "Trimestrielle", "4": "Trimestrielle",
    "MONTHLY": "Mensuelle", "MENSUEL": "Mensuelle", "12": "Mensuelle",
}


def strip_accents(s: str) -> str:
    s = "" if s is None else str(s)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_col(s: str) -> str:
    s = strip_accents(str(s)).lower().strip()
    for ch in ["'", "’", ".", ",", ";", ":", "(", ")", "%", "\n", "\r", "\t", "-"]:
        s = s.replace(ch, " ")
    return "_".join(s.split())


def clean_str(x: Any) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def normalize_text(x: Any) -> str:
    """
    Normalisation rapide pour moteur de recherche :
    - minuscules
    - suppression accents
    - espaces propres
    Cette fonction sert à créer une colonne indexée une seule fois.
    """
    s = strip_accents(clean_str(x)).lower()
    for ch in ["\n", "\r", "\t", ";", ",", ".", ":", "/", "\\", "-", "_", "'", "’", "(", ")"]:
        s = s.replace(ch, " ")
    return " ".join(s.split())


def parse_number(x: Any, default: float = np.nan) -> float:
    if pd.isna(x):
        return default
    if isinstance(x, (int, float, np.number)):
        return float(x)
    s = str(x).strip().replace("\xa0", " ").replace(" ", "").replace(",", ".").replace("%", "")
    if s in ["", "-", "nan", "None"]:
        return default
    try:
        return float(s)
    except Exception:
        return default


def parse_percent_to_pct(x: Any, default: float = 0.0) -> float:
    """Retourne un taux en pourcentage, ex: 2.5 pour 2.5%."""
    v = parse_number(x, default=np.nan)
    if pd.isna(v):
        return default
    if abs(v) <= 1:
        return v * 100
    return v


def parse_date_any(x: Any) -> pd.Timestamp:
    if pd.isna(x):
        return pd.NaT
    if isinstance(x, pd.Timestamp):
        return x
    s = str(x).strip()
    # Maroclear exporte souvent YYYY-MM-DD HH:MM:SS.0 : parsing ISO sans dayfirst.
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return pd.to_datetime(s[:10], format="%Y-%m-%d", errors="coerce")
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


def iso_date_list(values) -> str:
    """Sérialise une liste de dates déjà parsées en chaîne ISO séparée par |."""
    dates = []
    for x in values:
        if pd.isna(x):
            continue
        ts = x if isinstance(x, pd.Timestamp) else parse_date_any(x)
        if not pd.isna(ts):
            dates.append(ts.date().isoformat())
    return "|".join(sorted(set(dates)))


def _best_col(df: pd.DataFrame, candidates: List[str]) -> str:
    norm_cols = {normalize_col(c): c for c in df.columns}
    for cand in candidates:
        nc = normalize_col(cand)
        if nc in norm_cols:
            return norm_cols[nc]
    return ""


def standardize_maroclear_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    raw = df.copy()
    mapping_candidates = {
        "isin": ["INSTRID", "ISIN", "SECURITYID", "ID"],
        "instr_type": ["INSTRTYPE", "INSTRUMENTTYPE", "TYPE"],
        "category": ["INSTRCTGRY", "INSTRCATEGORY", "CATEGORY", "CATEGORIE"],
        "short_name": ["ENGPREFERREDNAME", "PREFERREDNAME", "SHORTNAME", "NOM COURT"],
        "long_name": ["ENGLONGNAME", "LONGNAME", "DESCRIPTION", "NOM LONG"],
        "issuer_code": ["ISSUERCD", "ISSUER CODE", "CODE EMETTEUR"],
        "issuer_name": ["PREFERREDNAMEISSUER", "ISSUERNAME", "ISSUER", "EMETTEUR"],
        "issue_size": ["ISSUESIZE", "ISSUE SIZE", "TAILLE EMISSION"],
        "issue_capital": ["ISSUECAPITAL", "CAPITAL EMIS"],
        "issue_date": ["ISSUEDT", "ISSUE DATE", "DATE EMISSION"],
        "maturity_date": ["MATURITYDT_L", "MATURITYDT", "MATURITY DATE", "DATE ECHEANCE", "ECHEANCE"],
        "par_value": ["PARVALUE", "NOMINAL", "VALEUR NOMINALE"],
        "new_par_value": ["NEWPARVALUE", "NEW PAR VALUE", "NOMINAL ACTUEL", "NOMINAL RESIDUEL"],
        "interest_type": ["INTERESTTYPE", "INTEREST TYPE", "TYPE TAUX"],
        "interest_rate": ["INTERESTRATE", "INTEREST RATE", "COUPON", "TAUX"],
        "prmy_date": ["PRMYDTLSDUMMYDATE1", "PRMYDTLS DUMMY DATE1", "FIRST COUPON DATE", "DATE PREMIER COUPON"],
        "coupon_frequency": ["INTERESTPERIODCTY", "INTEREST PERIODICITY", "FREQUENCE COUPON"],
        "redemption_type": ["REDEMPTIONTYPE", "REDEMPTION TYPE", "TYPE REMBOURSEMENT"],
        "amort_frequency": ["AMORTFREQ", "AMORTIZATIONFREQ", "FREQUENCE AMORT"],
        "listed": ["EXCHIND", "LISTED", "COTE"],
        "mnemonic": ["MNEMONIQUE", "MNEMONIC", "MNEMO"],
        "agent_id": ["AGENTID", "AGENT"],
        "registrar_name": ["PREFERREDNAMEREGISTRAR", "REGISTRAR"],
        "status": ["INSTRSTATUS", "STATUS", "STATUT"],
        "coupon_pay_date": ["CouponPayDate", "COUPONPAYDATE", "DATE COUPON"],
        "base_security_id": ["BASESECURITYID", "BASE SECURITY ID"],
    }

    out = pd.DataFrame()
    for std, cands in mapping_candidates.items():
        col = _best_col(raw, cands)
        out[std] = raw[col] if col else np.nan

    # conversions
    out["isin"] = out["isin"].apply(clean_str)
    out["instr_type"] = out["instr_type"].apply(lambda x: clean_str(x).upper())
    out["category"] = out["category"].apply(lambda x: clean_str(x).upper())
    out["short_name"] = out["short_name"].apply(clean_str)
    out["long_name"] = out["long_name"].apply(clean_str)
    out["issuer_code"] = out["issuer_code"].apply(clean_str)
    out["issuer_name"] = out["issuer_name"].apply(clean_str)
    out["mnemonic"] = out["mnemonic"].apply(clean_str)
    out["interest_type"] = out["interest_type"].apply(lambda x: clean_str(x).upper())
    out["status"] = out["status"].apply(lambda x: clean_str(x).upper())
    out["issue_date"] = out["issue_date"].apply(parse_date_any)
    out["maturity_date"] = out["maturity_date"].apply(parse_date_any)
    out["coupon_pay_date"] = out["coupon_pay_date"].apply(parse_date_any)
    out["prmy_date"] = out["prmy_date"].apply(parse_date_any)
    out["par_value"] = out["par_value"].apply(parse_number)
    out["new_par_value"] = out["new_par_value"].apply(parse_number)
    out["issue_size"] = out["issue_size"].apply(parse_number)
    out["issue_capital"] = out["issue_capital"].apply(parse_number)
    out["interest_rate_pct"] = out["interest_rate"].apply(parse_percent_to_pct)
    out["coupon_frequency_label"] = out["coupon_frequency"].apply(map_frequency)
    out["app_bond_type"] = out.apply(map_to_app_bond_type, axis=1)

    # Agrégation Maroclear :
    # Le fichier REP MCL contient souvent plusieurs lignes par ISIN, une par CouponPayDate.
    # V15 conserve ces dates au lieu de garder arbitrairement la première ligne.
    group_keys = ["isin", "category", "instr_type"]
    out["_row_order"] = np.arange(len(out))
    date_agg = (
        out.dropna(subset=["coupon_pay_date"])
           .groupby(group_keys, dropna=False)["coupon_pay_date"]
           .apply(lambda s: iso_date_list(s.tolist()))
           .rename("maroclear_coupon_dates")
    )
    first_idx = out.groupby(group_keys, dropna=False)["_row_order"].idxmin()
    out = out.loc[first_idx].copy().drop(columns=["_row_order"])
    out = out.merge(date_agg.reset_index(), on=group_keys, how="left")
    out["maroclear_coupon_dates"] = out["maroclear_coupon_dates"].fillna("")
    out["coupon_dates_count"] = out["maroclear_coupon_dates"].apply(lambda x: len(str(x).split("|")) if str(x).strip() else 0)
    out["coupon_pay_date"] = out["maroclear_coupon_dates"].apply(lambda x: parse_date_any(str(x).split("|")[0]) if str(x).strip() else pd.NaT)

    # Index de recherche pré-calculé.
    # Cela évite de retraiter 20k-30k lignes à chaque frappe dans la barre de recherche.
    out["search_blob"] = (
        out["isin"].astype(str) + " " +
        out["mnemonic"].astype(str) + " " +
        out["issuer_name"].astype(str) + " " +
        out["issuer_code"].astype(str) + " " +
        out["short_name"].astype(str) + " " +
        out["long_name"].astype(str) + " " +
        out["category"].astype(str) + " " +
        out["instr_type"].astype(str) + " " +
        out["interest_type"].astype(str)
    ).apply(normalize_text)

    # dette plausible
    out["is_debt"] = out.apply(is_debt_instrument, axis=1)
    out["is_active"] = out["status"].isin(["ACTI", "ACTIVE", "ACTIF"])
    return out.reset_index(drop=True)


def is_debt_instrument(row: pd.Series) -> bool:
    category = clean_str(row.get("category", "")).upper()
    instr_type = clean_str(row.get("instr_type", "")).upper()
    interest_type = clean_str(row.get("interest_type", "")).upper()

    if category in DEBT_CATEGORIES:
        return True
    if instr_type in ["FRBD", "FLRT", "AMBD", "ZCBD"]:
        return True
    if interest_type in ["FIXD", "FLTG", "FLOT", "DISC"]:
        return True
    return False


def map_frequency(x: Any) -> str:
    s = clean_str(x).upper().replace("-", "_").replace(" ", "_")
    if s in FREQ_MAP_MAROCLEAR:
        return FREQ_MAP_MAROCLEAR[s]
    # Tentative si champ numérique sous forme 1.0, 2.0, etc.
    try:
        n = int(float(s))
        return {1: "Annuelle", 2: "Semestrielle", 4: "Trimestrielle", 12: "Mensuelle"}.get(n, "Annuelle")
    except Exception:
        return "Annuelle"


def map_to_app_bond_type(row: pd.Series) -> str:
    category = clean_str(row.get("category", "")).upper()
    instr_type = clean_str(row.get("instr_type", "")).upper()
    interest_type = clean_str(row.get("interest_type", "")).upper()
    redemption_type = clean_str(row.get("redemption_type", "")).upper()
    issue_date = parse_date_any(row.get("issue_date"))
    maturity_date = parse_date_any(row.get("maturity_date"))

    # Priorité au remboursement amortissable : AMBD/AMOR doit rester amortissable.
    if instr_type == "AMBD" or "AMOR" in redemption_type:
        return "Obligation amortissable"

    # TCN court terme : formule court terme 360 jours.
    if category == "TCN":
        return "BDT / zéro coupon court terme"

    if category in CATEGORY_TYPE_OVERRIDES:
        if interest_type in ["FLTG", "FLOT", "VAR"]:
            return INTEREST_TYPE_MAP[interest_type]
        return CATEGORY_TYPE_OVERRIDES[category]

    if instr_type in INSTR_TYPE_MAP:
        return INSTR_TYPE_MAP[instr_type]
    if interest_type in INTEREST_TYPE_MAP:
        return INTEREST_TYPE_MAP[interest_type]
    return "Obligation à taux fixe in fine"


def read_maroclear_bytes(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    """
    Lecture depuis bytes pour permettre le cache Streamlit côté app.
    """
    name = file_name.lower()
    bio = io.BytesIO(file_bytes)
    if name.endswith(".csv"):
        content = file_bytes.decode("utf-8", errors="replace")
        sep = ";" if content.count(";") >= content.count(",") else ","
        df = pd.read_csv(io.StringIO(content), sep=sep, engine="python")
    else:
        # Le fichier REP MCL est souvent un xlsx avec une feuille Feuil1.
        df = pd.read_excel(bio, sheet_name=0)
    return standardize_maroclear_columns(df)


def read_maroclear_file(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    return read_maroclear_bytes(uploaded_file.getvalue(), uploaded_file.name)


def search_reference(ref_df: pd.DataFrame, query: str = "", only_debt: bool = True, only_active: bool = True,
                     category: str = "Tous", issuer: str = "Tous", interest_type: str = "Tous",
                     max_rows: int = 300, maturity_after=None) -> pd.DataFrame:
    """
    Recherche optimisée :
    - utilise search_blob pré-calculé ;
    - utilise regex=False ;
    - applique les filtres avant le texte ;
    - évite les apply() ligne par ligne pendant la recherche.
    """
    if ref_df is None or ref_df.empty:
        return pd.DataFrame()

    df = ref_df
    mask = pd.Series(True, index=df.index)

    if only_debt and "is_debt" in df.columns:
        mask &= df["is_debt"].fillna(False)
    if only_active and "is_active" in df.columns:
        mask &= df["is_active"].fillna(False)
    if category != "Tous":
        mask &= df["category"].eq(category)
    if issuer and issuer != "Tous":
        issuer_q = normalize_text(issuer)
        if issuer_q:
            mask &= df["issuer_name"].astype(str).map(normalize_text).str.contains(issuer_q, regex=False, na=False)
    if interest_type != "Tous":
        mask &= df["interest_type"].eq(interest_type)
    if maturity_after is not None and "maturity_date" in df.columns:
        mat = pd.to_datetime(df["maturity_date"], errors="coerce")
        mask &= mat.isna() | (mat.dt.date > maturity_after)

    q = normalize_text(query)
    if q:
        blob = df["search_blob"] if "search_blob" in df.columns else (
            df["isin"].astype(str) + " " + df["mnemonic"].astype(str) + " " +
            df["issuer_name"].astype(str) + " " + df["short_name"].astype(str) + " " + df["long_name"].astype(str)
        ).map(normalize_text)

        # Recherche multi-mots : tous les mots doivent être présents.
        for term in q.split():
            if len(term) >= 2:
                mask &= blob.str.contains(term, regex=False, na=False)
            else:
                mask &= blob.str.contains(term, regex=False, na=False)

    keep = [
        "isin", "mnemonic", "issuer_name", "category", "instr_type", "interest_type",
        "app_bond_type", "interest_rate_pct", "coupon_frequency_label",
        "issue_date", "maturity_date", "par_value", "new_par_value", "issue_size", "issue_capital", "status", "short_name", "long_name"
    ]
    return df.loc[mask, [c for c in keep if c in df.columns]].head(max_rows).reset_index(drop=True)


def reference_quality_checks(ref_df: pd.DataFrame) -> pd.DataFrame:
    if ref_df is None or ref_df.empty:
        return pd.DataFrame(columns=["controle", "nombre", "details"])

    checks = []
    debt = ref_df[ref_df["is_debt"]].copy()

    checks.append({"controle": "Titres de dette détectés", "nombre": len(debt), "details": "Catégories/type de dette reconnus"})
    checks.append({"controle": "Titres actifs", "nombre": int(debt["is_active"].sum()), "details": "INSTRSTATUS = ACTI / ACTIVE"})
    checks.append({"controle": "Titres non actifs", "nombre": int((~debt["is_active"]).sum()), "details": "À éviter sauf besoin historique"})
    checks.append({"controle": "Échéance manquante", "nombre": int(debt["maturity_date"].isna().sum()), "details": "Champ MATURITYDT_L vide/non lisible"})
    checks.append({"controle": "Nominal manquant", "nombre": int(debt["par_value"].isna().sum()), "details": "Champ PARVALUE/NEWPARVALUE vide"})
    checks.append({"controle": "Coupon manquant ou nul", "nombre": int((debt["interest_rate_pct"].isna() | (debt["interest_rate_pct"] == 0)).sum()), "details": "Normal pour zéro-coupon, à vérifier sinon"})
    checks.append({"controle": "Type de taux non reconnu", "nombre": int((debt["interest_type"].astype(str).str.len() == 0).sum()), "details": "INTERESTTYPE vide"})
    matured = int((debt["maturity_date"].dt.date < date.today()).fillna(False).sum())
    checks.append({"controle": "Titres déjà échus", "nombre": matured, "details": "Date d'échéance < aujourd'hui"})
    return pd.DataFrame(checks)



def choose_nominal_for_app(instrument: Dict[str, Any], force_mode: str = "auto", manual_nominal: float = np.nan) -> Dict[str, Any]:
    """
    Choix intelligent du nominal utilisé par l'app.

    force_mode:
    - auto : règle automatique
    - parvalue : utilise PARVALUE Maroclear
    - newparvalue : utilise NEWPARVALUE Maroclear
    - standard_100000 : force 100 000
    - manuel : utilise manual_nominal
    """
    category = clean_str(instrument.get("category", "")).upper()
    instr_type = clean_str(instrument.get("instr_type", "")).upper()
    app_type = clean_str(instrument.get("app_bond_type", ""))
    par_value = parse_number(instrument.get("par_value", np.nan), default=np.nan)
    new_par_value = parse_number(instrument.get("new_par_value", np.nan), default=np.nan)
    issue_size = parse_number(instrument.get("issue_size", np.nan), default=np.nan)
    issue_capital = parse_number(instrument.get("issue_capital", np.nan), default=np.nan)

    alerts = []

    def valid(x):
        return not pd.isna(x) and float(x) > 0

    if force_mode == "manuel" and valid(manual_nominal):
        nominal = float(manual_nominal)
        nominal_source = "Forcé manuellement"
    elif force_mode == "standard_100000":
        nominal = 100000.0
        nominal_source = "Standard 100 000 forcé"
    elif force_mode == "newparvalue" and valid(new_par_value):
        nominal = float(new_par_value)
        nominal_source = "Maroclear NEWPARVALUE"
    elif force_mode == "parvalue" and valid(par_value):
        nominal = float(par_value)
        nominal_source = "Maroclear PARVALUE"
    else:
        # AUTO
        if app_type == "Obligation amortissable" and valid(new_par_value):
            nominal = float(new_par_value)
            nominal_source = "Maroclear NEWPARVALUE - nominal résiduel possible"
        elif valid(par_value):
            nominal = float(par_value)
            nominal_source = "Maroclear PARVALUE"
        else:
            nominal = 100000.0
            nominal_source = "Défaut 100 000 - PARVALUE manquant"
            alerts.append("PARVALUE manquant : nominal 100 000 proposé par défaut.")

    if category in ["FPCT", "OBL_CONV"] or instr_type in ["ZCBD"] or app_type in ["Obligation convertible simplifiée", "BDT / zéro coupon court terme"]:
        if nominal != 100000.0:
            alerts.append("Nominal non standard autorisé : instrument FPCT / convertible / zéro coupon / structuré.")

    if valid(nominal) and (nominal < 1000 or nominal > 1000000):
        alerts.append(f"Nominal atypique détecté : {nominal:,.2f}. Vérifier PARVALUE / NEWPARVALUE / note d'information.")

    if category == "FPCT":
        alerts.append("FPCT : utiliser si possible un échéancier personnalisé date_flux/coupon/principal.")
    if category == "OBL_CONV":
        alerts.append("Obligation convertible : la valeur de l'option de conversion doit être traitée séparément si données disponibles.")
    if app_type == "Obligation amortissable" and valid(new_par_value):
        alerts.append("Titre amortissable : NEWPARVALUE peut représenter le nominal résiduel.")

    return {
        "nominal_utilise": float(nominal),
        "type_nominal": nominal_source,
        "nominal_maroclear_parvalue": float(par_value) if valid(par_value) else np.nan,
        "nominal_maroclear_newparvalue": float(new_par_value) if valid(new_par_value) else np.nan,
        "issue_size_maroclear": float(issue_size) if valid(issue_size) else np.nan,
        "issue_capital_maroclear": float(issue_capital) if valid(issue_capital) else np.nan,
        "alertes_nominal": " | ".join(alerts),
    }


def instrument_to_portfolio_row(instrument: Dict[str, Any], quantity: float = 1.0,
                                spread_credit_bps: float = 0.0, spread_liquidite_bps: float = 0.0,
                                market_clean_price_pct: float = np.nan,
                                nominal_mode: str = "auto",
                                manual_nominal: float = np.nan) -> Dict[str, Any]:
    isin = clean_str(instrument.get("isin", ""))
    issuer_name = clean_str(instrument.get("issuer_name", "")) or clean_str(instrument.get("issuer_code", ""))
    app_type = clean_str(instrument.get("app_bond_type", "")) or "Obligation à taux fixe in fine"

    coupon = parse_number(instrument.get("interest_rate_pct", 0.0), default=0.0)
    nominal_info = choose_nominal_for_app(instrument, force_mode=nominal_mode, manual_nominal=manual_nominal)
    nominal_used = nominal_info["nominal_utilise"]

    issue_date = parse_date_any(instrument.get("issue_date"))
    maturity_date = parse_date_any(instrument.get("maturity_date"))
    coupon_dates_str = clean_str(instrument.get("maroclear_coupon_dates", ""))
    coupon_dates = [d for d in coupon_dates_str.split("|") if d]
    first_coupon_from_mcl = coupon_dates[0] if coupon_dates else ""
    quantity = float(quantity)

    row = {
        "id": isin or clean_str(instrument.get("mnemonic", "")) or "MCL_UNKNOWN",
        "source": "Maroclear",
        "emetteur": issuer_name,
        "nom_court": clean_str(instrument.get("short_name", "")),
        "nom_long": clean_str(instrument.get("long_name", "")),
        "mnemonique": clean_str(instrument.get("mnemonic", "")),
        "categorie_maroclear": clean_str(instrument.get("category", "")),
        "type_maroclear": clean_str(instrument.get("instr_type", "")),
        "type_taux_maroclear": clean_str(instrument.get("interest_type", "")),
        "type_remboursement_maroclear": clean_str(instrument.get("redemption_type", "")),
        "frequence_amort_maroclear": clean_str(instrument.get("amort_frequency", "")),
        "type": app_type,
        "date_emission": issue_date.date().isoformat() if not pd.isna(issue_date) else date.today().isoformat(),
        "date_jouissance": issue_date.date().isoformat() if not pd.isna(issue_date) else date.today().isoformat(),
        "date_echeance": maturity_date.date().isoformat() if not pd.isna(maturity_date) else date(date.today().year + 5, 12, 31).isoformat(),
        "mode_calendrier_coupon": "Maroclear CouponPayDate" if coupon_dates_str else "Depuis échéance vers arrière",
        "maroclear_coupon_dates": coupon_dates_str,
        "maroclear_coupon_dates_count": len(coupon_dates),
        "maroclear_prmy_date": parse_date_any(instrument.get("prmy_date")).date().isoformat() if not pd.isna(parse_date_any(instrument.get("prmy_date"))) else "",
        "autoriser_coupon_long_contractuel": False,
        "nature_ligne": "Ligne normale",
        "structure_flux_confirmee": bool(coupon_dates_str),
        "date_premier_coupon": first_coupon_from_mcl,
        "date_coupon_precedent": "",
        "date_prochain_coupon": "",
        "nominal": float(nominal_used),
        "nominal_utilise": float(nominal_used),
        "quantite": quantity,
        "nominal_total_detenu": float(nominal_used) * quantity,
        "taux_coupon_pct": float(coupon),
        "frequence": clean_str(instrument.get("coupon_frequency_label", "Annuelle")) or "Annuelle",
        "marge_bps": 0.0,
        "spread_credit_bps": float(spread_credit_bps),
        "spread_liquidite_bps": float(spread_liquidite_bps),
        "spread_subordination_bps": 25.0 if clean_str(instrument.get("category", "")).upper() == "OBL_SUBD" else 0.0,
        "spread_specifique_bps": 0.0,
        "ajustement_marche_bps": 0.0,
        "tax_pct": 0.0,
        "base_coupon": "ACT/360" if app_type == "BDT / zéro coupon court terme" else "ACT/365",
        "base_actualisation": "ACT/360" if app_type == "BDT / zéro coupon court terme" else "ACT/365",
        "mode_actualisation": "Simple" if app_type == "BDT / zéro coupon court terme" else "Actuarielle annuelle",
        "interpolation": "Taux linéaire",
        "mode_pricing": "Courbe BAM / AMMC",
        "taux_ytm_fourni_pct": 0.0,
        "utiliser_prix_marche": not pd.isna(market_clean_price_pct),
        "prix_clean_marche_pct": market_clean_price_pct,
        "mode_ref_variable": "Courbe BAM interpolée",
        "mode_projection_variable": "FRN par au prochain reset recommandé",
        "frequence_reset": "Annuelle",
        "date_dernier_fixing": "",
        "date_prochain_fixing": "",
        "taux_ref_manuel_pct": 2.50,
        "coupon_courant_fixe_pct": float(coupon) if app_type == "Obligation à taux révisable / variable" else 0.0,
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
    row.update(nominal_info)
    return row

def enrich_simple_portfolio(simple_df: pd.DataFrame, ref_df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], pd.DataFrame]:
    """
    Transforme un portefeuille simple :
    ISIN;Quantite;Prix clean marche pct;Spread credit bps;Spread liquidite bps
    en lignes complètes grâce au référentiel Maroclear.
    """
    rows = []
    errors = []
    if simple_df is None or simple_df.empty:
        return [], pd.DataFrame()

    cols = {normalize_col(c): c for c in simple_df.columns}
    isin_col = cols.get("isin") or cols.get("instrid") or cols.get("id")
    qty_col = cols.get("quantite") or cols.get("quantity")
    px_col = cols.get("prix_clean_marche_pct") or cols.get("prix_marche") or cols.get("clean_price")
    sp_col = cols.get("spread_credit_bps") or cols.get("spread_bps") or cols.get("spread")
    liq_col = cols.get("spread_liquidite_bps") or cols.get("liquidity_spread_bps")

    if not isin_col:
        return [], pd.DataFrame([{"erreur": "Colonne ISIN introuvable"}])

    for idx, row in simple_df.iterrows():
        isin = clean_str(row.get(isin_col, ""))
        qty = parse_number(row.get(qty_col, 1.0) if qty_col else 1.0, default=1.0)
        px = parse_number(row.get(px_col, np.nan) if px_col else np.nan, default=np.nan)
        sp = parse_number(row.get(sp_col, 0.0) if sp_col else 0.0, default=0.0)
        liq = parse_number(row.get(liq_col, 0.0) if liq_col else 0.0, default=0.0)

        match = ref_df[ref_df["isin"].astype(str) == isin]
        if match.empty:
            errors.append({"ligne": idx + 1, "isin": isin, "erreur": "ISIN non trouvé dans Maroclear"})
            continue
        rows.append(instrument_to_portfolio_row(match.iloc[0].to_dict(), quantity=qty, spread_credit_bps=sp, spread_liquidite_bps=liq, market_clean_price_pct=px))

    return rows, pd.DataFrame(errors)


def build_issuer_risk_curve(ref_df: pd.DataFrame, issuer: str) -> pd.DataFrame:
    """
    Courbe de prime de risque par émetteur — Art. 7, version opérationnelle.
    Utilise les colonnes de spread/prime disponibles dans le référentiel si elles existent.
    Colonnes détectées : spread_emission, spread_issuance, issue_spread, prime_risque_bps, spread_bps.
    """
    if ref_df is None or ref_df.empty or not issuer:
        return pd.DataFrame()
    df = ref_df.copy()
    cols_norm = {c: str(c).lower().strip() for c in df.columns}
    issuer_cols = [c for c, n in cols_norm.items() if "issuer" in n or "emetteur" in n or "emetteur" in n]
    maturity_cols = [c for c, n in cols_norm.items() if "maturity" in n or "echeance" in n]
    issue_cols = [c for c, n in cols_norm.items() if "issue" in n and "date" in n or "emission" in n and "date" in n]
    spread_cols = [
        c for c, n in cols_norm.items()
        if ("spread" in n or "prime" in n) and ("bps" in n or "emission" in n or "risque" in n or "issue" in n)
    ]
    if not issuer_cols or not maturity_cols or not spread_cols:
        return pd.DataFrame()

    ic, mc, sc = issuer_cols[0], maturity_cols[0], spread_cols[0]
    out = df[df[ic].astype(str).str.contains(str(issuer), case=False, na=False)].copy()
    if out.empty:
        return pd.DataFrame()

    out["date_echeance"] = pd.to_datetime(out[mc], errors="coerce")
    out["prime_risque_bps"] = pd.to_numeric(out[sc], errors="coerce")
    if issue_cols:
        out["date_emission"] = pd.to_datetime(out[issue_cols[0]], errors="coerce")
    else:
        out["date_emission"] = pd.NaT
    out = out.dropna(subset=["date_echeance", "prime_risque_bps"])
    if out.empty:
        return pd.DataFrame()
    out = out.sort_values(["date_echeance", "date_emission"]).groupby("date_echeance", as_index=False).tail(1)
    return out[["date_echeance", "prime_risque_bps", "date_emission"]].sort_values("date_echeance").reset_index(drop=True)


def interpolate_issuer_risk_premium(ref_df: pd.DataFrame, issuer: str, target_maturity: pd.Timestamp) -> float:
    curve = build_issuer_risk_curve(ref_df, issuer)
    if curve.empty:
        return float("nan")
    t0 = pd.Timestamp.today().normalize()
    x = (pd.to_datetime(curve["date_echeance"]) - t0).dt.days.astype(float).values
    y = curve["prime_risque_bps"].astype(float).values
    target = (pd.Timestamp(target_maturity) - t0).days
    order = np.argsort(x)
    x, y = x[order], y[order]
    if target <= x[0]:
        return float(y[0])
    if target >= x[-1]:
        return float(y[-1])
    return float(np.interp(target, x, y))
