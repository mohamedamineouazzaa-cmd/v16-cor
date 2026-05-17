
# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from bam_data import interpolate_zero_rate, round_rate_percent_decimals


FREQ_MAP = {"Annuelle": 1, "Semestrielle": 2, "Trimestrielle": 4, "Mensuelle": 12}


@dataclass
class BondInputs:
    id: str
    emetteur: str
    type: str
    valuation_date: date
    settlement_date: date
    issue_date: date
    maturity_date: date
    accrual_start_date: date
    first_coupon_date: Optional[date]
    manual_previous_coupon_date: Optional[date]
    manual_next_coupon_date: Optional[date]
    maroclear_coupon_dates: List[date]
    coupon_schedule_mode: str
    allow_long_coupon_contractual: bool
    nature_ligne: str
    structure_flux_confirmee: bool
    variable_projection_mode: str
    reset_frequency: int
    last_fixing_date: Optional[date]
    next_fixing_date: Optional[date]
    nominal: float
    capital_restant_du_manuel: float
    quantity: float
    coupon_rate: float
    frequency: int
    margin_bps: float
    spread_credit_bps: float
    spread_liquidite_bps: float
    spread_subordination_bps: float
    spread_specifique_bps: float
    ajustement_marche_bps: float
    tax_rate: float
    day_count_coupon: str
    day_count_discount: str
    compounding: str
    interpolation_method: str
    pricing_mode: str
    manual_ytm_rate: float
    use_market_price: bool
    market_clean_price_pct: float
    variable_ref_mode: str
    manual_ref_rate: float
    current_coupon_rate: Optional[float]
    ref_tenor_days: int
    amortization_mode: str
    option_value_pct: float
    stock_price: float
    conversion_price: float
    conversion_ratio_manual: float
    extra_option_time_value_pct: float


def as_date(x: Any, default: Optional[date] = None) -> date:
    if default is None:
        default = date.today()
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    try:
        s = str(x).strip()
        # Streamlit and saved portfolios use ISO format YYYY-MM-DD.
        # Avoid pandas dayfirst=True ambiguity where 2026-09-01 can be read incorrectly.
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            ts = pd.to_datetime(s[:10], format="%Y-%m-%d", errors="coerce")
        else:
            ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(ts):
            return default
        return ts.date()
    except Exception:
        return default


def as_optional_date(x: Any) -> Optional[date]:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    s = str(x).strip()
    if s in ["", "None", "nan", "NaT", "-"]:
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            ts = pd.to_datetime(s[:10], format="%Y-%m-%d", errors="coerce")
        else:
            ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def get_float(d: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        v = d.get(key, default)
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def parse_date_list_pipe(x: Any) -> List[date]:
    if x is None:
        return []
    try:
        if pd.isna(x):
            return []
    except Exception:
        pass
    if isinstance(x, (list, tuple, set)):
        raw = list(x)
    else:
        raw = str(x).replace(",", "|").split("|")
    out = []
    for item in raw:
        d = as_optional_date(item)
        if d is not None:
            out.append(d)
    return sorted(set(out))


def dict_to_inputs(b: Dict[str, Any], global_settings: Dict[str, Any]) -> BondInputs:
    coupon_fixed = get_float(b, "coupon_courant_fixe_pct", 0.0)
    return BondInputs(
        id=str(b.get("id", "")),
        emetteur=str(b.get("emetteur", "")),
        type=str(b.get("type", "Obligation à taux fixe in fine")),
        valuation_date=as_date(global_settings.get("valuation_date")),
        settlement_date=as_date(global_settings.get("settlement_date")),
        issue_date=as_date(b.get("date_emission")),
        maturity_date=as_date(b.get("date_echeance")),
        accrual_start_date=as_date(b.get("date_jouissance", b.get("date_emission")), as_date(b.get("date_emission"))),
        first_coupon_date=as_optional_date(b.get("date_premier_coupon")),
        manual_previous_coupon_date=as_optional_date(b.get("date_coupon_precedent")),
        manual_next_coupon_date=as_optional_date(b.get("date_prochain_coupon")),
        maroclear_coupon_dates=parse_date_list_pipe(b.get("maroclear_coupon_dates", "")),
        coupon_schedule_mode=str(b.get("mode_calendrier_coupon", "Depuis échéance vers arrière")),
        allow_long_coupon_contractual=bool(b.get("autoriser_coupon_long_contractuel", False)),
        nature_ligne=str(b.get("nature_ligne", "Ligne normale")),
        structure_flux_confirmee=bool(b.get("structure_flux_confirmee", False)),
        variable_projection_mode=str(b.get("mode_projection_variable", "Coupon courant fixé puis projection courbe")),
        reset_frequency=FREQ_MAP.get(str(b.get("frequence_reset", b.get("frequence", "Annuelle"))), FREQ_MAP.get(str(b.get("frequence", "Annuelle")), 1)),
        last_fixing_date=as_optional_date(b.get("date_dernier_fixing")),
        next_fixing_date=as_optional_date(b.get("date_prochain_fixing")),
        nominal=get_float(b, "nominal_utilise", get_float(b, "nominal", 0.0)),
        capital_restant_du_manuel=get_float(b, "capital_restant_du_manuel", 0.0),
        quantity=get_float(b, "quantite", 0.0),
        coupon_rate=get_float(b, "taux_coupon_pct", 0.0) / 100.0,
        frequency=FREQ_MAP.get(str(b.get("frequence", "Annuelle")), 1),
        margin_bps=get_float(b, "marge_bps", 0.0),
        spread_credit_bps=get_float(b, "spread_credit_bps", 0.0),
        spread_liquidite_bps=get_float(b, "spread_liquidite_bps", 0.0),
        spread_subordination_bps=get_float(b, "spread_subordination_bps", 0.0),
        spread_specifique_bps=get_float(b, "spread_specifique_bps", 0.0),
        ajustement_marche_bps=get_float(b, "ajustement_marche_bps", 0.0),
        tax_rate=get_float(b, "tax_pct", 0.0) / 100.0,
        day_count_coupon=str(b.get("base_coupon", "ACT/365")),
        day_count_discount=str(b.get("base_actualisation", "ACT/365")),
        compounding=str(b.get("mode_actualisation", "Actuarielle annuelle")),
        interpolation_method=str(b.get("interpolation", "Taux linéaire")),
        pricing_mode=str(b.get("mode_pricing", "Courbe BAM / AMMC")),
        manual_ytm_rate=get_float(b, "taux_ytm_fourni_pct", 0.0) / 100.0,
        use_market_price=bool(b.get("utiliser_prix_marche", False)),
        market_clean_price_pct=get_float(b, "prix_clean_marche_pct", np.nan) / 100.0,
        variable_ref_mode=str(b.get("mode_ref_variable", "Courbe BAM interpolée")),
        manual_ref_rate=get_float(b, "taux_ref_manuel_pct", 0.0) / 100.0,
        current_coupon_rate=(coupon_fixed / 100.0 if coupon_fixed > 0 else None),
        ref_tenor_days=int(get_float(b, "tenor_ref_jours", 364)),
        amortization_mode=str(b.get("mode_amortissement", "Amortissement constant")),
        option_value_pct=get_float(b, "valeur_option_pct", 0.0) / 100.0,
        stock_price=get_float(b, "prix_action", 0.0),
        conversion_price=get_float(b, "prix_conversion", 0.0),
        conversion_ratio_manual=get_float(b, "ratio_conversion_manuel", 0.0),
        extra_option_time_value_pct=get_float(b, "valeur_temps_option_pct", 0.0) / 100.0,
    )


def year_fraction_act_act_isda(start: date, end: date) -> float:
    """
    ACT/ACT ISDA multi-années :
    somme par année civile de jours_effectifs / jours_de_l_année.
    Utilisé comme fallback ACT/ACT lorsque les bornes de période coupon ne sont pas connues.
    """
    if end <= start:
        return 0.0
    total = 0.0
    current = start
    while current < end:
        next_year = date(current.year + 1, 1, 1)
        segment_end = min(end, next_year)
        denom = 366.0 if is_leap_year(current.year) else 365.0
        total += (segment_end - current).days / denom
        current = segment_end
    return total


def year_fraction(
    start: date,
    end: date,
    basis: str = "ACT/365",
    frequency: Optional[int] = None,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> float:
    if end <= start:
        return 0.0
    if basis == "ACT/365":
        return (end - start).days / 365.0
    if basis == "ACT/360":
        return (end - start).days / 360.0
    if basis == "ACT/ACT":
        # ACT/ACT ICMA pour les intérêts courus lorsque les bornes de période coupon sont connues.
        if frequency and period_start and period_end and period_end > period_start:
            return (end - start).days / ((period_end - period_start).days * float(frequency))
        # ACT/ACT ISDA multi-années pour le DCF classique / fallback discount.
        return year_fraction_act_act_isda(start, end)
    if basis in ["30/360", "BOND BASIS"]:
        d1 = min(start.day, 30)
        d2 = end.day
        if d1 == 30 and d2 == 31:
            d2 = 30
        return ((end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)) / 360.0
    return (end - start).days / 365.0


def is_leap_year(y: int) -> bool:
    return (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)


def discount_factor(rate: float, t: float, compounding: str = "Actuarielle annuelle") -> float:
    if t <= 0:
        return 1.0
    if compounding == "Simple":
        return 1.0 / (1.0 + rate * t)
    if compounding == "Continue":
        return math.exp(-rate * t)
    return (1.0 + rate) ** (-t)



def coupon_months(frequency: int) -> int:
    return int(12 / max(1, int(frequency)))


def generate_schedule(issue_date: date, maturity_date: date, frequency: int) -> List[date]:
    if maturity_date <= issue_date:
        return [maturity_date]
    months = coupon_months(frequency)
    dates = []
    d = maturity_date
    while d > issue_date:
        dates.append(d)
        d = d - relativedelta(months=months)
    return sorted(set(dates))


def normal_coupon_yf(inputs: BondInputs) -> float:
    return 1.0 / max(int(getattr(inputs, "frequency", 1) or 1), 1)


def is_long_coupon_period(inputs: BondInputs, start_date: date, end_date: date, threshold: float = 1.10) -> bool:
    """
    Détection en jours calendaires, pas seulement via yf_coupon.
    Avec ACT/ACT ICMA, un coupon long peut avoir yf=1 si on utilise la période longue
    comme dénominateur ; la détection doit donc se faire sur la durée réelle.
    """
    if end_date <= start_date:
        return False
    normal_days = 365.0 / max(int(getattr(inputs, "frequency", 1) or 1), 1)
    return (end_date - start_date).days > normal_days * threshold


def insert_regular_intermediate_coupons(start_date: date, first_coupon: date, months: int) -> List[date]:
    """Insère des dates intermédiaires régulières entre la jouissance et le premier coupon annoncé."""
    out = []
    d = start_date + relativedelta(months=months)
    while d < first_coupon:
        out.append(d)
        d = d + relativedelta(months=months)
    return out


def generate_coupon_schedule(inputs: BondInputs) -> List[date]:
    start = inputs.accrual_start_date or inputs.issue_date
    maturity = inputs.maturity_date
    freq = max(1, int(inputs.frequency))
    months = coupon_months(freq)

    if maturity <= start:
        return [maturity]

    mode = inputs.coupon_schedule_mode or "Depuis échéance vers arrière"
    dates = []

    # V15 : calendrier exact issu de Maroclear CouponPayDate.
    # Le fichier contient souvent les dates futures seulement ; on rétro-propage
    # avec la fréquence pour reconstruire le dernier coupon avant settlement.
    if getattr(inputs, "maroclear_coupon_dates", None):
        dates = [d for d in inputs.maroclear_coupon_dates if start <= d <= maturity]
        if dates:
            first = min(dates)
            d = first - relativedelta(months=months)
            while d > start:
                dates.append(d)
                d = d - relativedelta(months=months)
            # On garde la maturité si elle n'est pas explicitement dans le REP.
            if maturity not in dates:
                dates.append(maturity)

    elif mode == "Depuis premier coupon vers avant" and inputs.first_coupon_date is not None and inputs.first_coupon_date > start:
        # V14.2 : si le premier coupon est anormalement long et non confirmé contractuellement,
        # on insère des dates intermédiaires régulières pour éviter un yf_coupon artificiellement > période normale.
        if (
            not inputs.allow_long_coupon_contractual
            and is_long_coupon_period(inputs, start, inputs.first_coupon_date, threshold=1.10)
        ):
            dates.extend(insert_regular_intermediate_coupons(start, inputs.first_coupon_date, months))
        d = inputs.first_coupon_date
        while d < maturity:
            dates.append(d)
            d = d + relativedelta(months=months)
        if not dates or dates[-1] != maturity:
            dates.append(maturity)

    elif mode == "Coupons précédent/prochain saisis" and inputs.manual_next_coupon_date is not None:
        if inputs.manual_previous_coupon_date is not None:
            dates.append(inputs.manual_previous_coupon_date)
        d = inputs.manual_next_coupon_date
        while d < maturity:
            dates.append(d)
            d = d + relativedelta(months=months)
        if not dates or dates[-1] != maturity:
            dates.append(maturity)

    else:
        dates = generate_schedule(start, maturity, freq)

    cleaned = []
    for d in sorted(set(dates)):
        if d >= start and d <= maturity:
            cleaned.append(d)
    if maturity not in cleaned:
        cleaned.append(maturity)
    return sorted(set(cleaned))


def get_previous_coupon_date(full_schedule: List[date], pay_date: date, start_date: date) -> date:
    previous_dates = [d for d in full_schedule if d < pay_date]
    return previous_dates[-1] if previous_dates else start_date


def find_coupon_period(schedule: List[date], settlement_date: date, issue_date: date) -> Tuple[date, date]:
    if not schedule:
        return issue_date, settlement_date
    future = [d for d in schedule if d > settlement_date]
    next_coupon = future[0] if future else schedule[-1]
    past = [d for d in schedule if d <= settlement_date]
    last_coupon = past[-1] if past else issue_date
    return last_coupon, next_coupon


def spread_total_bps(inputs: BondInputs) -> float:
    return (
        inputs.spread_credit_bps
        + inputs.spread_liquidite_bps
        + inputs.spread_subordination_bps
        + inputs.spread_specifique_bps
        + inputs.ajustement_marche_bps
    )


def taux_courbe_arrondi_plus_spread(zero_rate: float, spread_decimal: float = 0.0, extra_shift_decimal: float = 0.0) -> float:
    """
    Convention V16 :
    1) interpolation du taux courbe ;
    2) arrondi du taux courbe à 3 décimales en pourcentage ;
    3) ajout du spread en décimal ;
    4) arrondi du taux total à 3 décimales en pourcentage.

    Exemple :
    z = 3,221987% -> 3,222%
    spread = 80 bps -> +0,800%
    taux total = 4,022%
    """
    z_arr = round_rate_percent_decimals(zero_rate, 3)
    return round_rate_percent_decimals(z_arr + spread_decimal + extra_shift_decimal, 3)


def ammc_year_base(ref_date: date) -> int:
    return 366 if is_leap_year(ref_date.year) else 365


def within_one_calendar_year(start_date: date, end_date: date) -> bool:
    """
    Seuil AMMC 'moins d'un an / un an' traité en année calendaire.
    Exemple : 01/01/N -> 02/01/N+1 = plus qu'un an, même si le nombre de jours peut être 366.
    """
    if end_date < start_date:
        return False
    return end_date <= start_date + relativedelta(years=1)


def is_fixed_infine_type(inputs: BondInputs) -> bool:
    return inputs.type in [
        "Obligation à taux fixe in fine",
        "Obligation subordonnée",
        "Obligation callable simplifiée",
        "Obligation puttable simplifiée",
        "Obligation convertible simplifiée",
    ]


def normal_coupon_period_days(inputs: BondInputs) -> float:
    return 365.0 / max(int(getattr(inputs, "frequency", 1) or 1), 1)


def is_ligne_posterieure_auto(inputs: BondInputs) -> bool:
    """
    Détection automatique :
    si le premier coupon déclaré est > 1 période normale × 1,1,
    on traite le titre comme ligne postérieure / assimilée.

    V15 : si un calendrier Maroclear CouponPayDate est disponible, on ne déduit pas
    une ligne postérieure depuis le seul champ date_premier_coupon, car ce champ peut
    être simplement la première date future du fichier REP et non le premier coupon
    historique de la souche.
    """
    try:
        if getattr(inputs, "maroclear_coupon_dates", None):
            return False
        first = getattr(inputs, "first_coupon_date", None)
        start = getattr(inputs, "accrual_start_date", None)
        if first is None or start is None:
            return False
        return (first - start).days > normal_coupon_period_days(inputs) * 1.10
    except Exception:
        return False


def is_ligne_posterieure(inputs: BondInputs) -> bool:
    manual = str(getattr(inputs, "nature_ligne", "Ligne normale")).lower().startswith("ligne post")
    return bool(manual or is_ligne_posterieure_auto(inputs))


def forward_rate_from_curve(t1: float, t2: float, curve: pd.DataFrame, method: str) -> float:
    """
    Taux forward actuariel entre t1 et t2 extrait de la courbe BAM.
    Utilisé pour projeter les coupons FRN lorsque l'utilisateur choisit le mode forward.
    """
    t1 = max(float(t1), 0.0)
    t2 = max(float(t2), t1 + 1e-8)
    z1 = interpolate_zero_rate(max(t1, 1/365), curve, method, target_days=max(t1 * 365.0, 1.0))
    z2 = interpolate_zero_rate(max(t2, 1/365), curve, method, target_days=max(t2 * 365.0, 1.0))
    return ((1.0 + z2) ** t2 / ((1.0 + z1) ** t1)) ** (1.0 / (t2 - t1)) - 1.0


def ammc_interpolated_rate(inputs: BondInputs, curve: pd.DataFrame, residual_days: int, shift_bps: float = 0.0) -> float:
    """
    Article 6 : taux unique interpolé à la maturité résiduelle du titre.
    Les spreads saisis sont ajoutés pour les titres non souverains.
    """
    A = ammc_year_base(inputs.settlement_date)
    t = max(residual_days / A, 1 / A)
    tr = interpolate_zero_rate(t, curve, inputs.interpolation_method, target_days=residual_days)
    return taux_courbe_arrondi_plus_spread(
        tr,
        spread_total_bps(inputs) / 10000.0,
        shift_bps / 10000.0,
    )


def ammc_price(inputs: BondInputs, curve: pd.DataFrame, cf: Optional[pd.DataFrame] = None, shift_bps: float = 0.0) -> Dict[str, Any]:
    """
    Prix réglementaire AMMC/CDVM pour les cas standards de la circulaire 02/04.

    V12.2 :
    - le seuil 'un an' est calendaire, pas simplement <= 366 jours ;
    - le prix net fiscal suit la même formule AMMC que le brut, avec fiscalité sur les coupons/intérêts.
    """
    out = {
        "applicable": False,
        "dirty": np.nan,
        "dirty_net": np.nan,
        "tr_ammc": np.nan,
        "formule": "",
        "ecart_dcf": np.nan,
        "base_annee": np.nan,
        "Mi_jours": np.nan,
        "Mr_jours": np.nan,
        "nj_jours": np.nan,
        "nature_ligne": getattr(inputs, "nature_ligne", "Ligne normale"),
        "conformite_ammc": "Hors périmètre formule standard",
        "message_conformite": "",
    }

    if inputs.maturity_date <= inputs.settlement_date or inputs.nominal <= 0:
        out["message_conformite"] = "Titre échu ou nominal invalide."
        return out

    residual_days = max((inputs.maturity_date - inputs.settlement_date).days, 0)
    initial_days = max((inputs.maturity_date - inputs.issue_date).days, 0)
    is_initial_le_1y = within_one_calendar_year(inputs.issue_date, inputs.maturity_date)
    is_residual_le_1y = within_one_calendar_year(inputs.settlement_date, inputs.maturity_date)

    A = ammc_year_base(inputs.settlement_date)
    tr = ammc_interpolated_rate(inputs, curve, residual_days, shift_bps=shift_bps)
    N = inputs.nominal
    tf = inputs.coupon_rate
    tax = max(0.0, min(float(inputs.tax_rate), 1.0))
    is_post_auto = is_ligne_posterieure_auto(inputs)
    is_post = is_ligne_posterieure(inputs)

    out.update({
        "Mi_jours": initial_days,
        "Mr_jours": residual_days,
        "base_annee": A,
        "tr_ammc": tr,
        "ligne_posterieure_auto_detectee": bool(is_post_auto),
    })

    # Formule (1) : BDT / court terme.
    if inputs.type == "BDT / zéro coupon court terme" and is_initial_le_1y:
        interest = N * tf * initial_days / 360.0
        redemption = N + interest
        redemption_net = N + interest * (1.0 - tax)
        denom = 1.0 + tr * residual_days / 360.0
        dirty = redemption / denom
        dirty_net = redemption_net / denom
        out.update({
            "applicable": True,
            "dirty": dirty,
            "dirty_net": dirty_net,
            "formule": "AMMC (1) BDT court terme : N*(1+tf*Mi/360)/(1+tr*Mr/360)",
            "base_annee": 360,
            "conformite_ammc": "Conforme AMMC",
            "message_conformite": "BDT court terme : seuil un an calendaire et prix net fiscal aligné sur la formule AMMC.",
        })
        return out

    # Formule (4.2) prioritaire : ligne postérieure avec un seul flux restant.
    # On la traite explicitement avant la branche résiduelle <= 1 an afin d'activer
    # la convention dédiée lorsque la structure de flux ne contient qu'un flux.
    if is_fixed_infine_type(inputs) and is_post and cf is not None and not cf.empty:
        cf_one = cf.copy()
        cf_one["date_flux_tmp"] = pd.to_datetime(cf_one["date_flux"], errors="coerce")
        cf_one = cf_one.sort_values("date_flux_tmp")
        if len(cf_one) == 1:
            next_coupon_date = cf_one["date_flux_tmp"].iloc[0].date()
            nj = max((next_coupon_date - inputs.settlement_date).days, 0)
            first_offset = nj / A
            out["nj_jours"] = nj
            interest = N * tf * initial_days / A
            numerator = N + interest
            numerator_net = N + interest * (1.0 - tax)
            denom = (1.0 + tr) ** first_offset
            dirty = numerator / denom
            dirty_net = numerator_net / denom
            out.update({
                "applicable": True,
                "dirty": dirty,
                "dirty_net": dirty_net,
                "formule": "AMMC (4.2) ligne postérieure 1 flux : N*(1+tf*Mi/A)/(1+tr)^(nj/A)",
                "conformite_ammc": "Conforme AMMC",
                "message_conformite": ("Ligne postérieure avec un seul flux restant. Prix net fiscal aligné." + (" Détection automatique activée." if is_post_auto else "")),
            })
            return out

    # Formules (2) et (3) : in fine avec maturité résiduelle <= 1 an calendaire.
    if is_fixed_infine_type(inputs) and is_residual_le_1y:
        if is_post or is_initial_le_1y:
            interest = N * tf * initial_days / A
            numerator = N + interest
            numerator_net = N + interest * (1.0 - tax)
            formula = "AMMC (3) ligne postérieure <= 1 an : N*(1+tf*Mi/A)/(1+tr*Mr/360)"
            msg = "Ligne postérieure ou maturité initiale courte : coupon calculé sur Mi/A."
        else:
            interest = N * tf
            numerator = N + interest
            numerator_net = N + interest * (1.0 - tax)
            formula = "AMMC (2) in fine Mr<=1 an : N*(1+tf)/(1+tr*Mr/360)"
            msg = "Ligne normale : coupon annuel complet retenu."

        denom = 1.0 + tr * residual_days / 360.0
        dirty = numerator / denom
        dirty_net = numerator_net / denom
        out.update({
            "applicable": True,
            "dirty": dirty,
            "dirty_net": dirty_net,
            "formule": formula,
            "base_annee": A,
            "conformite_ammc": "Conforme AMMC",
            "message_conformite": msg + " Prix net fiscal aligné sur la même formule.",
        })
        return out

    # Formules (4) : in fine > 1 an.
    if is_fixed_infine_type(inputs) and (not is_residual_le_1y) and cf is not None and not cf.empty:
        cf_future = cf.copy()
        cf_future["date_flux_tmp"] = pd.to_datetime(cf_future["date_flux"], errors="coerce")
        cf_future = cf_future.sort_values("date_flux_tmp")
        n = len(cf_future)

        next_coupon_date = cf_future["date_flux_tmp"].iloc[0].date()
        nj = max((next_coupon_date - inputs.settlement_date).days, 0)
        first_offset = nj / A
        out["nj_jours"] = nj

        # Formule (4.2) : ligne postérieure / 1 flux restant.
        if is_post and n == 1:
            interest = N * tf * initial_days / A
            numerator = N + interest
            numerator_net = N + interest * (1.0 - tax)
            denom = (1.0 + tr) ** first_offset
            dirty = numerator / denom
            dirty_net = numerator_net / denom
            out.update({
                "applicable": True,
                "dirty": dirty,
                "dirty_net": dirty_net,
                "formule": "AMMC (4.2) ligne postérieure 1 flux : N*(1+tf*Mi/A)/(1+tr)^(nj/A)",
                "conformite_ammc": "Conforme AMMC",
                "message_conformite": ("Ligne postérieure avec un seul flux restant. Prix net fiscal aligné." + (" Détection automatique activée." if is_post_auto else "")),
            })
            return out

        # Formule (4.3) : ligne postérieure avant premier coupon / plusieurs flux.
        if is_post and inputs.settlement_date < next_coupon_date and n > 1:
            dirty = 0.0
            dirty_net = 0.0
            freq = max(inputs.frequency, 1)
            coupon_periodique = N * tf / freq
            coupon_periodique_net = coupon_periodique * (1.0 - tax)
            for k in range(2, n + 1):
                exponent = first_offset + (k - 1) / freq
                dirty += coupon_periodique / ((1.0 + tr) ** exponent)
                dirty_net += coupon_periodique_net / ((1.0 + tr) ** exponent)
            principal_exp = first_offset + (n - 1) / freq
            dirty += N / ((1.0 + tr) ** principal_exp)
            dirty_net += N / ((1.0 + tr) ** principal_exp)

            d1c_dem = max((next_coupon_date - inputs.issue_date).days, 0)
            correction = N * tf * d1c_dem / A
            dirty -= correction / ((1.0 + tr) ** first_offset)
            dirty_net -= correction * (1.0 - tax) / ((1.0 + tr) ** first_offset)

            out.update({
                "applicable": True,
                "dirty": dirty,
                "dirty_net": dirty_net,
                "formule": "AMMC (4.3) ligne postérieure avant 1er coupon : flux à partir du 2e coupon moins fraction du 1er coupon",
                "conformite_ammc": "Conforme AMMC avec hypothèse ligne postérieure",
                "message_conformite": ("Formule spéciale ligne postérieure avant premier coupon appliquée. Prix net fiscal aligné." + (" Détection automatique activée." if is_post_auto else "")),
            })
            return out

        # Formule (4.1) : ligne normale.
        dirty = 0.0
        dirty_net = 0.0
        freq = max(inputs.frequency, 1)
        coupon_periodique = N * tf / freq
        coupon_periodique_net = coupon_periodique * (1.0 - tax)
        for k in range(1, n + 1):
            exponent = first_offset + (k - 1) / freq
            dirty += coupon_periodique / ((1.0 + tr) ** exponent)
            dirty_net += coupon_periodique_net / ((1.0 + tr) ** exponent)

        principal_pv = N / ((1.0 + tr) ** (first_offset + (n - 1) / freq))
        dirty += principal_pv
        dirty_net += principal_pv

        out.update({
            "applicable": True,
            "dirty": dirty,
            "dirty_net": dirty_net,
            "formule": "AMMC (4.1) in fine Mr>1 an : coupon constant, taux unique, premier décalage nj/A puis périodes annuelles",
            "conformite_ammc": "Conforme AMMC",
            "message_conformite": "Ligne normale in fine avec coupon unitaire constant. Prix net fiscal aligné sur la formule AMMC.",
        })
        return out

    # Hors périmètre formule standard.
    if inputs.type == "Obligation à taux révisable / variable":
        out["conformite_ammc"] = "Conforme avec hypothèses contractuelles"
        out["message_conformite"] = "Taux variable : la conformité dépend du coupon courant, du fixing et de la note d'information."
    elif inputs.type == "Obligation amortissable":
        out["conformite_ammc"] = "Non conforme — échéancier contractuel requis"
        out["message_conformite"] = "Amortissable : nécessite un échéancier contractuel exact. Le mode automatique reste indicatif."
    elif inputs.type == "Obligation perpétuelle":
        out["conformite_ammc"] = "Indicatif / hors formule standard"
        out["message_conformite"] = "Perpétuelle : formule financière spécifique hors cas standards de la circulaire."
    return out


def load_custom_schedule(schedule_df: pd.DataFrame, inputs: BondInputs, curve: pd.DataFrame) -> pd.DataFrame:
    """Échéancier uploadé : date_flux, coupon, principal. Les montants sont par titre."""
    if schedule_df is None or schedule_df.empty:
        return pd.DataFrame()

    raw = schedule_df.copy()
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    date_col = "date_flux" if "date_flux" in raw.columns else raw.columns[0]
    coupon_col = "coupon" if "coupon" in raw.columns else None
    principal_col = "principal" if "principal" in raw.columns else None

    rows = []
    for i, r in raw.iterrows():
        pay_date = as_date(r.get(date_col))
        if pay_date <= inputs.settlement_date:
            continue
        t = year_fraction(inputs.settlement_date, pay_date, inputs.day_count_discount)
        coupon = float(r.get(coupon_col, 0.0) or 0.0) if coupon_col else 0.0
        principal = float(r.get(principal_col, 0.0) or 0.0) if principal_col else 0.0
        target_days_cf = max((pay_date - inputs.settlement_date).days, 1)
        z = interpolate_zero_rate(t, curve, inputs.interpolation_method, target_days=target_days_cf)
        s = spread_total_bps(inputs) / 10000.0
        taux_actu = taux_courbe_arrondi_plus_spread(z, s)
        df = discount_factor(taux_actu, t, inputs.compounding)
        cf = coupon + principal
        rows.append({
            "id": inputs.id, "emetteur": inputs.emetteur, "type": inputs.type,
            "periode": i + 1, "date_flux": pay_date, "capital_debut": np.nan,
            "jours_coupon": np.nan, "yf_coupon": np.nan, "annees_flux": t,
            "taux_ref_utilise": np.nan, "taux_coupon_utilise": np.nan,
            "coupon_brut": coupon, "coupon_net": coupon * (1.0 - inputs.tax_rate),
            "principal": principal, "cashflow_brut": cf,
            "cashflow_net": coupon * (1.0 - inputs.tax_rate) + principal,
            "taux_zero_interpole": z, "spread_total": s, "taux_actualisation": taux_actu,
            "df": df, "pv_brut": cf * df,
            "pv_net": (coupon * (1.0 - inputs.tax_rate) + principal) * df,
            "capital_fin": np.nan, "source_cashflow": "echeancier_personnalise"
        })
    return pd.DataFrame(rows)


def variable_coupon_from_table(var_df: pd.DataFrame, pay_date: date, default_rate: float) -> float:
    """Table : date_flux,taux_reference_pct,coupon_total_pct optionnel."""
    if var_df is None or var_df.empty:
        return default_rate
    raw = var_df.copy()
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    if "date_flux" not in raw.columns:
        return default_rate
    raw["date_flux_dt"] = pd.to_datetime(raw["date_flux"], dayfirst=True, errors="coerce").dt.date
    m = raw[raw["date_flux_dt"] == pay_date]
    if m.empty:
        return default_rate
    r = m.iloc[0]
    if "coupon_total_pct" in raw.columns and not pd.isna(r.get("coupon_total_pct")):
        return float(r.get("coupon_total_pct")) / 100.0
    if "taux_reference_pct" in raw.columns and not pd.isna(r.get("taux_reference_pct")):
        return float(r.get("taux_reference_pct")) / 100.0 + default_rate
    return default_rate




def get_variable_coupon_rate(
    inputs: BondInputs,
    idx: int,
    pay_date: date,
    curve: pd.DataFrame,
    variable_rates_table: Optional[pd.DataFrame] = None,
) -> Tuple[float, float, str]:
    """
    Retourne (coupon_rate_total, reference_rate_used, source).

    V8 - logique FRN marocaine :
    - Le coupon = taux de référence BAM contractuel + marge.
    - Le coupon courant déjà fixé s'applique au premier flux futur.
    - Pour les coupons non encore fixés, plusieurs modes sont possibles.
    - Le mode "FRN par au prochain reset" ne valorise que jusqu'au prochain reset,
      en supposant que le titre revient près du pair au reset si la marge contractuelle
      est cohérente avec le risque de marché.
    """
    margin = inputs.margin_bps / 10000.0

    if variable_rates_table is not None and not variable_rates_table.empty:
        rate = variable_coupon_from_table(variable_rates_table, pay_date, margin)
        return rate, rate - margin, "table_taux_variables"

    mode = inputs.variable_projection_mode or "Coupon courant fixé puis projection courbe"

    # Premier flux : coupon courant déjà fixé, s'il est fourni.
    if inputs.current_coupon_rate is not None and inputs.current_coupon_rate > 0:
        if idx == 1 and mode in [
            "Coupon courant fixé puis projection courbe",
            "FRN par au prochain reset recommandé",
            "FRN complet projeté courbe + marge",
        ]:
            return inputs.current_coupon_rate, max(0.0, inputs.current_coupon_rate - margin), "coupon_courant_premiere_periode"

        if mode == "Coupon courant constant jusqu'échéance":
            return inputs.current_coupon_rate, max(0.0, inputs.current_coupon_rate - margin), "coupon_courant_constant"

    if mode == "Taux Maroclear/coupon facial constant":
        return inputs.coupon_rate, max(0.0, inputs.coupon_rate - margin), "coupon_maroclear_constant"

    if mode == "Taux référence manuel constant + marge" or inputs.variable_ref_mode == "Taux de référence manuel constant":
        ref = inputs.manual_ref_rate
        return ref + margin, ref, "reference_manuelle_constante"

    if mode == "Projection forwards + marge":
        # Projection plus rigoureuse : taux forward entre la période précédente et la date de flux.
        t2 = max(year_fraction(inputs.settlement_date, pay_date, inputs.day_count_discount), 1/365)
        period = 1.0 / max(inputs.reset_frequency or inputs.frequency, 1)
        t1 = max(t2 - period, 0.0)
        ref = forward_rate_from_curve(t1, t2, curve, inputs.interpolation_method)
        return ref + margin, ref, "forward_bam_plus_marge"

    if mode == "Courbe BAM + marge":
        ref_t = max(inputs.ref_tenor_days / 365.0, 1 / 365.0)
        ref = interpolate_zero_rate(ref_t, curve, inputs.interpolation_method, target_days=inputs.ref_tenor_days)
        return ref + margin, ref, "courbe_bam_plus_marge"

    # Mode courbe BAM par défaut : on projette la référence contractuelle depuis le tenor choisi.
    ref_t = max(inputs.ref_tenor_days / 365.0, 1 / 365.0)
    ref = interpolate_zero_rate(ref_t, curve, inputs.interpolation_method, target_days=inputs.ref_tenor_days)
    return ref + margin, ref, "courbe_bam_plus_marge"


def build_frn_reset_proxy_cashflow(
    inputs: BondInputs,
    curve: pd.DataFrame,
    full_schedule: List[date],
    variable_rates_table: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Valorisation FRN "reset au pair" sans échéancier Excel.

    Principe financier :
    - Une obligation à taux variable se réajuste à chaque date de reset.
    - Juste après le reset, si la marge contractuelle correspond au risque exigé,
      la valeur clean est proche du pair.
    - Entre deux resets, on valorise surtout le coupon déjà fixé jusqu'au prochain reset
      et le retour au pair au prochain reset.

    Modèle :
    P_dirty ≈ (Nominal + Coupon courant de la période) / (1 + taux_discount_court)^t
    Puis P_clean = P_dirty - intérêts courus.

    Le flux "principal" ici est un proxy de valeur de revente au pair au reset,
    pas un vrai remboursement juridique du principal.
    """
    schedule = [d for d in full_schedule if d > inputs.settlement_date]
    if not schedule:
        return pd.DataFrame()

    pay_date = schedule[0]
    prev_date = get_previous_coupon_date(full_schedule, pay_date, inputs.accrual_start_date or inputs.issue_date)

    yf_coupon_full = year_fraction(prev_date, pay_date, inputs.day_count_coupon, inputs.frequency, prev_date, pay_date)
    t = year_fraction(inputs.settlement_date, pay_date, inputs.day_count_discount)

    coupon_rate_used, ref_rate_used, rate_source = get_variable_coupon_rate(
        inputs, 1, pay_date, curve, variable_rates_table
    )
    coupon = inputs.nominal * coupon_rate_used * yf_coupon_full

    # Discount court jusqu'au prochain reset/coupon.
    # On utilise la référence courbe sur la maturité t + spread total.
    target_days_cf = max((pay_date - inputs.settlement_date).days, 1)
    z = interpolate_zero_rate(max(t, 1/365), curve, inputs.interpolation_method, target_days=target_days_cf)
    s = spread_total_bps(inputs) / 10000.0
    taux_actu = taux_courbe_arrondi_plus_spread(z, s)
    df = discount_factor(taux_actu, t, inputs.compounding)

    cf = coupon + inputs.nominal
    return pd.DataFrame([{
        "id": inputs.id, "emetteur": inputs.emetteur, "type": inputs.type,
        "periode": 1, "date_flux": pay_date, "capital_debut": inputs.nominal,
        "jours_coupon": (pay_date - prev_date).days, "yf_coupon": yf_coupon_full,
        "annees_flux": t, "taux_ref_utilise": ref_rate_used,
        "taux_coupon_utilise": coupon_rate_used,
        "source_taux_variable": rate_source,
        "coupon_brut": coupon,
        "coupon_net": coupon * (1.0 - inputs.tax_rate),
        "principal": inputs.nominal,
        "cashflow_brut": cf,
        "cashflow_net": coupon * (1.0 - inputs.tax_rate) + inputs.nominal,
        "taux_zero_interpole": z,
        "spread_total": s,
        "taux_actualisation": taux_actu,
        "df": df,
        "pv_brut": cf * df,
        "pv_net": (coupon * (1.0 - inputs.tax_rate) + inputs.nominal) * df,
        "capital_fin": inputs.nominal,
        "source_cashflow": "frn_par_reset_proxy"
    }])

def build_cashflows(inputs: BondInputs, curve: pd.DataFrame, custom_schedule: Optional[pd.DataFrame] = None,
                    variable_rates_table: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    if custom_schedule is not None and not custom_schedule.empty:
        return load_custom_schedule(custom_schedule, inputs, curve)

    n = inputs.nominal
    if n <= 0:
        return pd.DataFrame()

    freq = max(1, inputs.frequency)
    margin = inputs.margin_bps / 10000.0

    if inputs.type == "Obligation perpétuelle":
        months = int(12 / freq)
        full_schedule = [inputs.settlement_date + relativedelta(months=months * i) for i in range(1, 30 * freq + 1)]
    else:
        full_schedule = generate_coupon_schedule(inputs)

    future_schedule = [d for d in full_schedule if d > inputs.settlement_date]
    if not future_schedule and inputs.type != "Obligation perpétuelle":
        return pd.DataFrame()

    if (
        inputs.type == "Obligation à taux révisable / variable"
        and inputs.variable_projection_mode == "FRN par au prochain reset recommandé"
    ):
        return build_frn_reset_proxy_cashflow(inputs, curve, full_schedule, variable_rates_table)

    rows = []
    total_periods = len(future_schedule)
    total_original_periods = max(1, len(full_schedule))
    past_periods = len([d for d in full_schedule if d <= inputs.settlement_date])

    amort_const_original = n / total_original_periods
    amort_const_future = amort_const_original

    annuity_payment_future = np.nan
    if inputs.type == "Obligation amortissable":
        if inputs.capital_restant_du_manuel and inputs.capital_restant_du_manuel > 0:
            # V14.1 : le CRD manuel pilote tout l'échéancier futur, pas seulement les IC.
            outstanding = max(0.0, float(inputs.capital_restant_du_manuel))
            amort_const_future = outstanding / max(total_periods, 1)
        elif inputs.amortization_mode == "Amortissement constant":
            # Hypothèse automatique simple : amortissement constant depuis l'émission.
            outstanding = max(0.0, n - amort_const_original * past_periods)
            amort_const_future = amort_const_original
        else:
            outstanding = n
            amort_const_future = 0.0

        if inputs.amortization_mode == "Annuités constantes":
            period_rate = inputs.coupon_rate / max(freq, 1)
            if abs(period_rate) < 1e-12:
                annuity_payment_future = outstanding / max(total_periods, 1)
            else:
                annuity_payment_future = outstanding * period_rate / (1.0 - (1.0 + period_rate) ** (-max(total_periods, 1)))
    else:
        outstanding = n

    for idx, pay_date in enumerate(future_schedule, start=1):
        prev_date = get_previous_coupon_date(full_schedule, pay_date, inputs.accrual_start_date or inputs.issue_date)
        yf_coupon = year_fraction(prev_date, pay_date, inputs.day_count_coupon, freq, prev_date, pay_date)
        normal_yf = 1.0 / max(freq, 1)
        normal_days = 365.0 / max(freq, 1)
        coupon_long_flag = bool(((pay_date - prev_date).days > normal_days * 1.10) or (yf_coupon > normal_yf * 1.10))
        coupon_long_non_confirme = bool(coupon_long_flag and not inputs.allow_long_coupon_contractual)
        t = year_fraction(inputs.settlement_date, pay_date, inputs.day_count_discount)
        principal = 0.0
        ref_rate_used = np.nan
        coupon_rate_used = inputs.coupon_rate
        variable_rate_source = ""

        if inputs.type == "BDT / zéro coupon court terme":
            coupon = 0.0
            if idx == total_periods:
                initial_days = max((inputs.maturity_date - inputs.issue_date).days, 0)
                # AMMC formule (1) : le remboursement économique d'un BDT court terme
                # est N*(1+tf*Mi/360), et non le nominal facial seul.
                principal = outstanding * (1.0 + inputs.coupon_rate * initial_days / 360.0)

        elif inputs.type == "Obligation à taux révisable / variable":
            coupon_rate_used, ref_rate_used, variable_rate_source = get_variable_coupon_rate(
                inputs, idx, pay_date, curve, variable_rates_table
            )
            coupon = outstanding * coupon_rate_used * yf_coupon
            if idx == total_periods:
                principal = outstanding

        elif inputs.type == "Obligation amortissable":
            # V15.1 : coupon constant par période sur le CRD.
            # On ne proratise pas à 366/365 pendant les années bissextiles.
            coupon = outstanding * inputs.coupon_rate / max(freq, 1)
            if inputs.amortization_mode == "In fine":
                principal = outstanding if idx == total_periods else 0.0
            elif inputs.amortization_mode == "Annuités constantes":
                if idx == total_periods:
                    principal = outstanding
                else:
                    principal = min(max(float(annuity_payment_future) - coupon, 0.0), outstanding)
            elif inputs.amortization_mode == "Différé d’amortissement / CRD obligatoire" and not (inputs.capital_restant_du_manuel and inputs.capital_restant_du_manuel > 0):
                principal = 0.0
            else:
                # V14.1 : si CRD manuel est renseigné, on amortit le CRD restant sur les flux futurs.
                principal = min(amort_const_future, outstanding)

        else:
            if is_fixed_infine_type(inputs):
                # AMMC / marché marocain : le coupon unitaire d'une obligation fixe in fine
                # est constant par période. Exemple annuel : 100 000 * 4,50% = 4 500.
                # On ne doit pas gonfler le coupon à 4 512,33 pendant une année bissextile.
                coupon = outstanding * inputs.coupon_rate / max(freq, 1)
            else:
                coupon = outstanding * inputs.coupon_rate * yf_coupon

            if idx == total_periods:
                principal = outstanding

                # AMMC formules (2) et (3) pour le dernier flux d'une obligation in fine.
                # Si la maturité résiduelle est <= 1 an, la convention réglementaire utilise
                # le coupon annuel complet (Mi > 1 an) ou le coupon sur maturité initiale (Mi <= 1 an).
                residual_days = max((inputs.maturity_date - inputs.settlement_date).days, 0)
                initial_days = max((inputs.maturity_date - inputs.issue_date).days, 0)
                A = ammc_year_base(inputs.settlement_date)
                if is_fixed_infine_type(inputs) and within_one_calendar_year(inputs.settlement_date, inputs.maturity_date):
                    if within_one_calendar_year(inputs.issue_date, inputs.maturity_date):
                        coupon = outstanding * inputs.coupon_rate * initial_days / A
                    else:
                        coupon = outstanding * inputs.coupon_rate

        if inputs.type == "Obligation perpétuelle":
            principal = 0.0

        gross_cf = coupon + principal
        net_cf = coupon * (1.0 - inputs.tax_rate) + principal

        target_days_cf = max((pay_date - inputs.settlement_date).days, 1)
        z = interpolate_zero_rate(t, curve, inputs.interpolation_method, target_days=target_days_cf)
        s = spread_total_bps(inputs) / 10000.0
        taux_actu = taux_courbe_arrondi_plus_spread(z, s)
        df = discount_factor(taux_actu, t, inputs.compounding)

        rows.append({
            "id": inputs.id, "emetteur": inputs.emetteur, "type": inputs.type,
            "periode": idx, "date_flux": pay_date, "capital_debut": outstanding,
            "crd_manuel_utilise": (inputs.capital_restant_du_manuel if inputs.type == "Obligation amortissable" and inputs.capital_restant_du_manuel > 0 else np.nan),
            "jours_coupon": (pay_date - prev_date).days, "yf_coupon": yf_coupon,
            "yf_coupon_normal": normal_yf, "jours_coupon_normal": normal_days, "coupon_long_flag": coupon_long_flag,
            "coupon_long_non_confirme": coupon_long_non_confirme,
            "annees_flux": t, "taux_ref_utilise": ref_rate_used,
            "taux_coupon_utilise": coupon_rate_used, "coupon_brut": coupon,
            "coupon_net": coupon * (1.0 - inputs.tax_rate), "principal": principal,
            "cashflow_brut": gross_cf, "cashflow_net": net_cf,
            "taux_zero_interpole": z, "spread_total": s,
            "taux_actualisation": taux_actu, "df": df,
            "pv_brut": gross_cf * df, "pv_net": net_cf * df,
            "capital_fin": max(0.0, outstanding - principal),
            "source_cashflow": "genere"
        })
        if inputs.type != "Obligation perpétuelle":
            outstanding = max(0.0, outstanding - principal)

    return pd.DataFrame(rows)


def amortization_outstanding_at_settlement(inputs: BondInputs, schedule: List[date]) -> float:
    """
    Capital restant dû estimé à la date de règlement.
    Priorité :
    1. CRD manuel si renseigné ;
    2. amortissement constant depuis l'émission si aucun CRD manuel ;
    3. nominal initial.
    Le même CRD doit piloter les intérêts courus ET les cash-flows futurs.
    """
    if inputs.type != "Obligation amortissable":
        return inputs.nominal
    if inputs.capital_restant_du_manuel and inputs.capital_restant_du_manuel > 0:
        return max(0.0, float(inputs.capital_restant_du_manuel))

    if inputs.amortization_mode != "Amortissement constant":
        return inputs.nominal

    try:
        full_schedule = [d for d in schedule if d <= inputs.maturity_date]
        total_periods = max(1, len(full_schedule))
        past_periods = len([d for d in full_schedule if d <= inputs.settlement_date])
        amort_const = inputs.nominal / total_periods
        return max(0.0, inputs.nominal - amort_const * past_periods)
    except Exception:
        return inputs.nominal


def compute_accrued_interest(
    inputs: BondInputs,
    schedule: List[date],
    curve: pd.DataFrame,
    variable_rates_table: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    # Titre déjà échu : il ne doit pas générer d'intérêt couru économique.
    if inputs.maturity_date <= inputs.settlement_date:
        return {"last_coupon": inputs.maturity_date, "next_coupon": inputs.maturity_date, "current_coupon_rate": 0.0,
                "yf_accrued": 0.0, "yf_period": 0.0,
                "full_coupon_period": 0.0, "accrued_interest": 0.0}

    accrual_start = inputs.accrual_start_date or inputs.issue_date

    if inputs.settlement_date <= accrual_start:
        nexts = [d for d in schedule if d > inputs.settlement_date]
        next_coupon0 = nexts[0] if nexts else inputs.maturity_date
        return {"last_coupon": accrual_start, "next_coupon": next_coupon0, "current_coupon_rate": 0.0,
                "yf_accrued": 0.0, "yf_period": year_fraction(accrual_start, next_coupon0, inputs.day_count_coupon, inputs.frequency, accrual_start, next_coupon0),
                "full_coupon_period": 0.0, "accrued_interest": 0.0}

    if inputs.type == "BDT / zéro coupon court terme":
        return {"last_coupon": accrual_start, "next_coupon": inputs.maturity_date, "current_coupon_rate": 0.0,
                "yf_accrued": 0.0, "yf_period": year_fraction(accrual_start, inputs.maturity_date, inputs.day_count_coupon, inputs.frequency, accrual_start, inputs.maturity_date),
                "full_coupon_period": 0.0, "accrued_interest": 0.0}

    last_coupon, next_coupon = find_coupon_period(schedule, inputs.settlement_date, accrual_start)

    if inputs.type == "Obligation à taux révisable / variable":
        current_rate, _, _ = get_variable_coupon_rate(inputs, 1, next_coupon, curve, variable_rates_table)
    else:
        current_rate = inputs.coupon_rate

    yf_accrued = year_fraction(last_coupon, inputs.settlement_date, inputs.day_count_coupon, inputs.frequency, last_coupon, next_coupon)
    yf_period = max(year_fraction(last_coupon, next_coupon, inputs.day_count_coupon, inputs.frequency, last_coupon, next_coupon), 1e-12)

    accrual_base = amortization_outstanding_at_settlement(inputs, schedule)
    accrued = accrual_base * current_rate * yf_accrued
    full_coupon = accrual_base * current_rate * yf_period
    return {"last_coupon": last_coupon, "next_coupon": next_coupon, "current_coupon_rate": current_rate,
            "yf_accrued": yf_accrued, "yf_period": yf_period, "full_coupon_period": full_coupon,
            "accrued_interest": accrued, "accrual_base": accrual_base}


def price_from_cf(cf: pd.DataFrame, shift_bps: float, compounding: str, net: bool = False,
                  short_shift_bps: float = 0.0, long_shift_bps: float = 0.0) -> float:
    if cf is None or cf.empty:
        return 0.0
    total = 0.0
    for _, r in cf.iterrows():
        t = float(r["annees_flux"])
        curve_shape_shift = short_shift_bps if t <= 2 else long_shift_bps if t >= 10 else short_shift_bps + (long_shift_bps - short_shift_bps) * ((t - 2) / 8)
        base_rate = float(r["taux_actualisation"]) if "taux_actualisation" in r and not pd.isna(r["taux_actualisation"]) else taux_courbe_arrondi_plus_spread(float(r["taux_zero_interpole"]), float(r["spread_total"]))
        rate = taux_courbe_arrondi_plus_spread(base_rate, 0.0, (shift_bps + curve_shape_shift) / 10000.0)
        df = discount_factor(rate, t, compounding)
        cash = float(r["cashflow_net"] if net else r["cashflow_brut"])
        total += cash * df
    return total


def solve_ytm(cf: pd.DataFrame, price: float, compounding: str) -> float:
    if cf is None or cf.empty or price <= 0:
        return np.nan

    def f(y: float) -> float:
        return sum(float(r["cashflow_brut"]) * discount_factor(y, float(r["annees_flux"]), compounding) for _, r in cf.iterrows()) - price

    lo, hi = -0.90, 1.00
    flo, fhi = f(lo), f(hi)
    for _ in range(20):
        if flo * fhi <= 0:
            break
        hi *= 2
        fhi = f(hi)
    if flo * fhi > 0:
        return np.nan
    for _ in range(100):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-8:
            return mid
        if flo * fm <= 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    return (lo + hi) / 2


def solve_zspread(cf: pd.DataFrame, market_dirty: float, compounding: str) -> float:
    if cf is None or cf.empty or market_dirty <= 0:
        return np.nan

    def f(s_bps: float) -> float:
        return price_from_cf(cf, s_bps, compounding, net=False) - market_dirty

    lo, hi = -2000.0, 5000.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return np.nan
    for _ in range(100):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-7:
            return mid
        if flo * fm <= 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    return (lo + hi) / 2


def price_from_cf_flat_yield(cf: pd.DataFrame, ytm: float, compounding: str, net: bool = False) -> float:
    if cf is None or cf.empty or ytm <= -0.99:
        return 0.0
    total = 0.0
    for _, r in cf.iterrows():
        cash = float(r["cashflow_net"] if net else r["cashflow_brut"])
        total += cash * discount_factor(ytm, float(r["annees_flux"]), compounding)
    return total


def price_short_term_from_ytm(inputs: BondInputs, ytm: float, net: bool = False) -> float:
    residual_days = max((inputs.maturity_date - inputs.settlement_date).days, 0)
    initial_days = max((inputs.maturity_date - inputs.issue_date).days, 0)
    interest = inputs.nominal * inputs.coupon_rate * initial_days / 360.0
    if net:
        interest *= (1.0 - inputs.tax_rate)
    redemption = inputs.nominal + interest
    return redemption / (1.0 + ytm * residual_days / 360.0)


def option_adjusted_spread_approx(cf: pd.DataFrame, market_dirty: float, option_value: float, compounding: str, option_type: str) -> float:
    """
    OAS simplifié : ajuste le prix marché de la valeur optionnelle approximative.
    Callable : option émetteur => prix marché + valeur option.
    Puttable / convertible : option investisseur => prix marché - valeur option.
    """
    if cf is None or cf.empty or market_dirty <= 0 or option_value <= 0:
        return np.nan
    adjusted = market_dirty
    if option_type == "Obligation callable simplifiée":
        adjusted = market_dirty + option_value
    elif option_type in ["Obligation puttable simplifiée", "Obligation convertible simplifiée"]:
        adjusted = max(market_dirty - option_value, 1e-8)
    else:
        return np.nan
    return solve_zspread(cf, adjusted, compounding)


def compute_metrics(inputs: BondInputs, curve: pd.DataFrame, custom_schedule: Optional[pd.DataFrame] = None,
                    variable_rates_table: Optional[pd.DataFrame] = None) -> Tuple[Dict[str, Any], pd.DataFrame, Dict[str, Any]]:
    cf = build_cashflows(inputs, curve, custom_schedule=custom_schedule, variable_rates_table=variable_rates_table)
    schedule = generate_coupon_schedule(inputs)
    accrued = compute_accrued_interest(inputs, schedule, curve, variable_rates_table)

    dirty_dcf = price_from_cf(cf, 0.0, inputs.compounding, net=False)
    dirty_net_dcf = price_from_cf(cf, 0.0, inputs.compounding, net=True)
    dirty = dirty_dcf
    dirty_net = dirty_net_dcf

    ammc = ammc_price(inputs, curve, cf, shift_bps=0.0)
    if custom_schedule is None and ammc.get("applicable", False):
        dirty = float(ammc["dirty"])
        dirty_net = float(ammc.get("dirty_net", dirty_net_dcf))

    if inputs.type == "Obligation perpétuelle":
        long_t = max(curve["tenor_years"].max(), 1.0) if curve is not None and not curve.empty else 30.0
        long_rate = interpolate_zero_rate(long_t, curve, inputs.interpolation_method)
        required = max(long_rate + spread_total_bps(inputs) / 10000.0, 1e-8)
        annual_coupon = inputs.nominal * inputs.coupon_rate
        dirty = annual_coupon / required
        dirty_net = annual_coupon * (1.0 - inputs.tax_rate) / required

    if inputs.pricing_mode == "YTM fourni / gérant" and inputs.manual_ytm_rate > 0:
        if inputs.type == "BDT / zéro coupon court terme":
            dirty = price_short_term_from_ytm(inputs, inputs.manual_ytm_rate, net=False)
            dirty_net = price_short_term_from_ytm(inputs, inputs.manual_ytm_rate, net=True)
        else:
            dirty = price_from_cf_flat_yield(cf, inputs.manual_ytm_rate, inputs.compounding, net=False)
            dirty_net = price_from_cf_flat_yield(cf, inputs.manual_ytm_rate, inputs.compounding, net=True)

    clean = dirty - accrued["accrued_interest"]
    clean_net = dirty_net - accrued["accrued_interest"] * (1.0 - inputs.tax_rate)

    option_value = inputs.nominal * inputs.option_value_pct
    if inputs.type == "Obligation callable simplifiée":
        dirty -= option_value
        clean -= option_value
    elif inputs.type == "Obligation puttable simplifiée":
        dirty += option_value
        clean += option_value

    conversion_ratio = np.nan
    conversion_value = np.nan
    if inputs.type == "Obligation convertible simplifiée":
        if inputs.conversion_ratio_manual > 0:
            conversion_ratio = inputs.conversion_ratio_manual
        elif inputs.conversion_price > 0:
            conversion_ratio = inputs.nominal / inputs.conversion_price
        else:
            conversion_ratio = 0.0
        conversion_value = conversion_ratio * inputs.stock_price
        time_value = inputs.nominal * inputs.extra_option_time_value_pct
        dirty = max(dirty, conversion_value) + time_value
        clean = dirty - accrued["accrued_interest"]

    sens_shift_bps = 10.0
    sens_shift_dec = sens_shift_bps / 10000.0
    if custom_schedule is None and ammc.get("applicable", False):
        p0_for_sens = dirty
        p_up = float(ammc_price(inputs, curve, cf, shift_bps=sens_shift_bps).get("dirty", np.nan))
        p_dn = float(ammc_price(inputs, curve, cf, shift_bps=-sens_shift_bps).get("dirty", np.nan))
        if pd.isna(p_up) or pd.isna(p_dn):
            p0_for_sens = price_from_cf(cf, 0.0, inputs.compounding, net=False)
            p_up = price_from_cf(cf, sens_shift_bps, inputs.compounding, net=False)
            p_dn = price_from_cf(cf, -sens_shift_bps, inputs.compounding, net=False)
    else:
        p0_for_sens = price_from_cf(cf, 0.0, inputs.compounding, net=False)
        p_up = price_from_cf(cf, sens_shift_bps, inputs.compounding, net=False)
        p_dn = price_from_cf(cf, -sens_shift_bps, inputs.compounding, net=False)

    pvbp = (p_dn - p_up) / (2.0 * sens_shift_bps)
    duration = (p_dn - p_up) / (2.0 * max(p0_for_sens, 1e-12) * sens_shift_dec)
    convexity = (p_dn + p_up - 2.0 * p0_for_sens) / (max(p0_for_sens, 1e-12) * (sens_shift_dec ** 2))
    ytm = inputs.manual_ytm_rate if (inputs.pricing_mode == "YTM fourni / gérant" and inputs.manual_ytm_rate > 0) else solve_ytm(cf, dirty, inputs.compounding)

    market_dirty = np.nan
    zspread_market_bps = np.nan
    if inputs.use_market_price and not pd.isna(inputs.market_clean_price_pct) and inputs.market_clean_price_pct > 0:
        market_clean = inputs.nominal * inputs.market_clean_price_pct
        market_dirty = market_clean + accrued["accrued_interest"]
        zspread_market_bps = solve_zspread(cf, market_dirty, inputs.compounding)

    option_value_for_oas = inputs.nominal * inputs.option_value_pct
    oas_bps = option_adjusted_spread_approx(cf, market_dirty, option_value_for_oas, inputs.compounding, inputs.type)

    max_yf_coupon = float(cf["yf_coupon"].dropna().max()) if cf is not None and not cf.empty and "yf_coupon" in cf.columns and not cf["yf_coupon"].dropna().empty else np.nan
    first_coupon_yf = float(cf["yf_coupon"].dropna().iloc[0]) if cf is not None and not cf.empty and "yf_coupon" in cf.columns and not cf["yf_coupon"].dropna().empty else np.nan
    coupon_long_count = int(cf["coupon_long_flag"].fillna(False).sum()) if cf is not None and not cf.empty and "coupon_long_flag" in cf.columns else 0
    coupon_long_non_confirme_count = int(cf["coupon_long_non_confirme"].fillna(False).sum()) if cf is not None and not cf.empty and "coupon_long_non_confirme" in cf.columns else 0
    amortissement_principal_gap = np.nan
    amortissement_principal_sum = np.nan
    amortissement_crd_initial_calcule = np.nan
    if inputs.type == "Obligation amortissable" and cf is not None and not cf.empty and "principal" in cf.columns and "capital_debut" in cf.columns:
        amortissement_crd_initial_calcule = float(cf["capital_debut"].dropna().iloc[0]) if not cf["capital_debut"].dropna().empty else np.nan
        amortissement_principal_sum = float(cf["principal"].fillna(0.0).sum())
        amortissement_principal_gap = amortissement_crd_initial_calcule - amortissement_principal_sum if not pd.isna(amortissement_crd_initial_calcule) else np.nan
    first_coupon_brut = float(cf["coupon_brut"].iloc[0]) if cf is not None and not cf.empty and "coupon_brut" in cf.columns else np.nan
    frn_clean_gap_to_par = np.nan
    if inputs.type == "Obligation à taux révisable / variable" and inputs.nominal:
        frn_clean_gap_to_par = (clean / inputs.nominal) - 1.0

    metrics = {
        "id": inputs.id,
        "emetteur": inputs.emetteur,
        "type": inputs.type,
        "date_echeance": inputs.maturity_date,
        "nominal": inputs.nominal,
        "quantite": inputs.quantity,
        "coupon": inputs.coupon_rate,
        "spread_total_bps": spread_total_bps(inputs),
        "dirty_price": dirty,
        "clean_price": clean,
        "dirty_price_dcf": dirty_dcf,
        "prix_ammc": float(ammc["dirty"]) if ammc.get("applicable", False) else np.nan,
        "prix_net_ammc": float(ammc.get("dirty_net", np.nan)) if ammc.get("applicable", False) else np.nan,
        "ecart_app_vs_dcf": dirty - dirty_dcf,
        "formule_ammc": ammc.get("formule", ""),
        "methode_pricing_active": ("YTM fourni / gérant" if inputs.pricing_mode == "YTM fourni / gérant" and inputs.manual_ytm_rate > 0 else ("AMMC réglementaire" if ammc.get("applicable", False) and custom_schedule is None else "DCF / flux personnalisés")),
        "mode_pricing": inputs.pricing_mode,
        "taux_ytm_fourni": inputs.manual_ytm_rate,
        "maroclear_coupon_dates_count": len(inputs.maroclear_coupon_dates),
        "taux_ammc": ammc.get("tr_ammc", np.nan),
        "coupon_unitaire_ammc": inputs.nominal * inputs.coupon_rate / max(inputs.frequency, 1) if is_fixed_infine_type(inputs) else np.nan,
        "capital_restant_du_accrual": accrued.get("accrual_base", inputs.nominal),
        "capital_restant_du_manuel": inputs.capital_restant_du_manuel,
        "crd_manuel_pilote_cashflows": bool(inputs.type == "Obligation amortissable" and inputs.capital_restant_du_manuel > 0),
        "conformite_ammc": ammc.get("conformite_ammc", ""),
        "message_conformite": ammc.get("message_conformite", ""),
        "nature_ligne": inputs.nature_ligne,
        "ligne_posterieure_auto_detectee": ammc.get("ligne_posterieure_auto_detectee", False),
        "Mi_jours": ammc.get("Mi_jours", np.nan),
        "Mr_jours": ammc.get("Mr_jours", np.nan),
        "nj_jours": ammc.get("nj_jours", np.nan),
        "dirty_price_net": dirty_net,
        "clean_price_net": clean_net,
        "dirty_pct_nominal": dirty / inputs.nominal if inputs.nominal else np.nan,
        "clean_pct_nominal": clean / inputs.nominal if inputs.nominal else np.nan,
        "interets_courus": accrued["accrued_interest"],
        "ytm": ytm,
        "zspread_market_bps": zspread_market_bps,
        "oas_bps": oas_bps,
        "duration_modifiee": duration,
        "convexite": convexity,
        "pvbp": pvbp,
        "dv01": pvbp,
        "valeur_position_dirty": dirty * inputs.quantity,
        "valeur_position_clean": clean * inputs.quantity,
        "interets_courus_position": accrued["accrued_interest"] * inputs.quantity,
        "pvbp_position": pvbp * inputs.quantity,
        "market_dirty_value": market_dirty,
        "max_yf_coupon": max_yf_coupon,
        "first_coupon_yf": first_coupon_yf,
        "coupon_long_count": coupon_long_count,
        "coupon_long_non_confirme_count": coupon_long_non_confirme_count,
        "autoriser_coupon_long_contractuel": inputs.allow_long_coupon_contractual,
        "amortissement_crd_initial_calcule": amortissement_crd_initial_calcule,
        "amortissement_principal_sum": amortissement_principal_sum,
        "amortissement_principal_gap": amortissement_principal_gap,
        "first_coupon_brut": first_coupon_brut,
        "date_jouissance": inputs.accrual_start_date,
        "date_premier_coupon": inputs.first_coupon_date,
        "date_coupon_precedent_saisi": inputs.manual_previous_coupon_date,
        "date_prochain_coupon_saisi": inputs.manual_next_coupon_date,
        "mode_calendrier_coupon": inputs.coupon_schedule_mode,
        "mode_projection_variable": inputs.variable_projection_mode,
        "frn_ecart_clean_au_pair": frn_clean_gap_to_par,
        "date_dernier_fixing": inputs.last_fixing_date,
        "date_prochain_fixing": inputs.next_fixing_date,
        "conversion_ratio": conversion_ratio,
        "conversion_value": conversion_value,
        "sensibilite_option_note": "Sensibilité indicative hors modèle optionnel complet" if inputs.type in ["Obligation callable simplifiée", "Obligation puttable simplifiée", "Obligation convertible simplifiée"] else "",
    }
    # Statut de conformité pour flux personnalisés et structures hors formules standards.
    if custom_schedule is not None and not custom_schedule.empty:
        metrics["conformite_ammc"] = "Conforme avec échéancier utilisateur"
        metrics["message_conformite"] = "Prix calculé sur les flux saisis/confirmés par l'utilisateur."
    if inputs.type == "Obligation amortissable" and custom_schedule is None:
        metrics["conformite_ammc"] = "Non conforme — échéancier contractuel requis"
        metrics["message_conformite"] = "Obligation amortissable : uploadez/confirmez l'échéancier contractuel réel avant toute valorisation réglementaire. Le calcul affiché est indicatif."
    if inputs.type == "Obligation amortissable":
        if inputs.amortization_mode == "Différé d’amortissement / CRD obligatoire" and not (inputs.capital_restant_du_manuel and inputs.capital_restant_du_manuel > 0):
            metrics["conformite_ammc"] = "Non conforme — CRD manuel obligatoire"
            metrics["message_conformite"] = "Différé d’amortissement détecté/saisi : le CRD manuel ou l’échéancier contractuel est obligatoire."
        elif not pd.isna(amortissement_principal_gap) and abs(amortissement_principal_gap) > 0.01:
            metrics["conformite_ammc"] = "Non conforme — somme amortissements ≠ CRD"
            metrics["message_conformite"] = "La somme des principaux futurs ne rembourse pas le CRD calculé. Vérifiez différé, CRD manuel ou échéancier contractuel."
    if coupon_long_non_confirme_count > 0:
        metrics["conformite_ammc"] = "Non conforme — coupon long non confirmé"
        metrics["message_conformite"] = "Coupon long détecté (> période normale × 1,10). Confirmez le coupon long contractuel ou corrigez le calendrier/échéancier."

    return metrics, cf, accrued
