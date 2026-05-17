
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import numpy as np
import pandas as pd


def validate_bond(b: Dict[str, Any], valuation_date: date) -> List[Dict[str, Any]]:
    alerts = []
    bid = b.get("id", "")
    btype = b.get("type", "")

    def add(level, message):
        alerts.append({"niveau": level, "id": bid, "message": message})

    try:
        issue_dt = pd.to_datetime(b.get("date_emission"), errors="coerce").date()
        jouissance_dt = pd.to_datetime(b.get("date_jouissance", b.get("date_emission")), errors="coerce").date()
        maturity = pd.to_datetime(b.get("date_echeance"), errors="coerce").date()

        if maturity <= valuation_date and btype != "Obligation perpétuelle":
            add("ERREUR", "Titre déjà échu ou échéance <= date de valorisation.")
        if jouissance_dt > maturity:
            add("ERREUR", "Date de jouissance postérieure à l'échéance.")
        if issue_dt > maturity:
            add("ERREUR", "Date d'émission postérieure à l'échéance.")
        if valuation_date < jouissance_dt:
            add("ALERTE", "Date de valorisation/règlement avant jouissance : intérêts courus forcés à zéro.")

        nature = str(b.get("nature_ligne", "Ligne normale"))
        if nature == "Ligne normale" and issue_dt != jouissance_dt:
            add("ALERTE", "Possible ligne postérieure : date émission différente de la date de jouissance. Vérifier le champ Nature de ligne.")
        if nature == "Ligne normale" and str(b.get("source", "")).lower() == "maroclear":
            nc = str(b.get("nom_court", "") + " " + b.get("nom_long", "")).lower()
            if any(x in nc for x in ["assim", "assimil", "ligne post", "postérieure", "posterieur"]):
                add("ALERTE", "Le libellé suggère une ligne postérieure/assimilée : vérifier Nature de ligne.")
    except Exception:
        add("ERREUR", "Date d'émission/jouissance/échéance invalide.")

    if btype == "BDT / zéro coupon court terme":
        comp = str(b.get("mode_actualisation", ""))
        if comp != "Simple":
            add("ALERTE", "BDT court terme : la formule AMMC utilise un rendement simple. Le moteur AMMC corrige le prix, mais vérifiez la convention affichée.")
    if str(b.get("nature_ligne", "Ligne normale")).startswith("Ligne post") and not b.get("date_premier_coupon"):
        add("ALERTE", "Ligne postérieure : renseigner la date de premier coupon améliore le contrôle AMMC.")

    try:
        nominal = float(b.get("nominal_utilise", b.get("nominal", 0)))
        if nominal <= 0:
            add("ERREUR", "Nominal nul ou négatif.")
        cat = str(b.get("categorie_maroclear", "")).upper()
        if nominal < 1000 or nominal > 1000000:
            add("ALERTE", f"Nominal atypique ({nominal:,.2f}) : peut être normal pour FPCT/convertible/structuré, à vérifier.")
        if cat == "FPCT":
            if not bool(b.get("structure_flux_confirmee", False)):
                add("ERREUR", "FPCT : échéancier personnalisé non confirmé. Valorisation indicative uniquement.")
            else:
                add("INFO", "FPCT : échéancier personnalisé confirmé.")
        if cat == "OBL_CONV":
            add("ALERTE", "Obligation convertible : valorisation obligataire simple incomplète sans option de conversion.")
    except Exception:
        add("ERREUR", "Nominal invalide.")

    try:
        qty = float(b.get("quantite", 0))
        if qty < 0:
            add("ERREUR", "Quantité négative.")
    except Exception:
        add("ERREUR", "Quantité invalide.")

    try:
        coupon = float(b.get("taux_coupon_pct", 0))
        if coupon < 0:
            add("ERREUR", "Coupon négatif.")
        if coupon > 20:
            add("ALERTE", "Coupon très élevé, à vérifier.")
    except Exception:
        add("ERREUR", "Coupon invalide.")

    spread_keys = ["spread_credit_bps", "spread_liquidite_bps", "spread_subordination_bps", "spread_specifique_bps", "ajustement_marche_bps"]
    for k in spread_keys:
        try:
            v = float(b.get(k, 0))
            if v < -1000 or v > 5000:
                add("ALERTE", f"{k} extrême : {v} bps.")
        except Exception:
            add("ALERTE", f"{k} invalide.")

    if btype == "Obligation à taux révisable / variable":
        if float(b.get("marge_bps", 0) or 0) == 0 and float(b.get("coupon_courant_fixe_pct", 0) or 0) == 0:
            add("ALERTE", "Taux révisable sans marge ni coupon courant fixé : vérifier la référence.")
    if b.get("source") == "Maroclear" and b.get("categorie_maroclear") == "":
        add("ALERTE", "Ligne issue du référentiel mais catégorie Maroclear vide.")

    if btype in ["Obligation callable simplifiée", "Obligation puttable simplifiée", "Obligation convertible simplifiée"]:
        add("ALERTE", "Sensibilité indicative hors modèle optionnel complet.")

    return alerts


def validate_valuation_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    """
    Contrôles après valorisation :
    - prix trop élevé sur obligations classiques ;
    - période coupon anormalement longue.
    """
    rows = []
    if summary_df is None or summary_df.empty:
        return pd.DataFrame(rows)

    for _, r in summary_df.iterrows():
        bid = r.get("id", "")
        btype = str(r.get("type", ""))
        clean_pct = r.get("clean_pct_nominal", np.nan)
        max_yf = r.get("max_yf_coupon", np.nan)

        if pd.notna(clean_pct) and clean_pct > 1.30 and btype in ["Obligation à taux fixe in fine", "Obligation subordonnée"]:
            rows.append({
                "niveau": "ALERTE",
                "id": bid,
                "message": f"Clean price > 130% du nominal ({clean_pct:.2%}). Vérifier taux, spread, nominal et calendrier coupons."
            })

        if pd.notna(max_yf) and max_yf > 1.20 and btype in ["Obligation à taux fixe in fine", "Obligation subordonnée", "Obligation à taux révisable / variable"]:
            rows.append({
                "niveau": "ERREUR",
                "id": bid,
                "message": f"Période coupon anormalement longue (yf_coupon max={max_yf:.2f}). Vérifier dates coupon/jouissance."
            })

        if btype == "Obligation à taux révisable / variable" and pd.notna(clean_pct):
            if clean_pct < 0.90 or clean_pct > 1.10:
                rows.append({
                    "niveau": "ALERTE",
                    "id": bid,
                    "message": f"FRN éloigné du pair ({clean_pct:.2%}). Vérifier coupon courant, marge contractuelle, reset et spread exigé."
                })

    return pd.DataFrame(rows)


def validate_portfolio(portfolio: List[Dict[str, Any]], valuation_date: date) -> pd.DataFrame:
    rows = []
    for b in portfolio:
        rows.extend(validate_bond(b, valuation_date))
    return pd.DataFrame(rows)


def validate_limits(summary_df: pd.DataFrame, limits: Dict[str, Any]) -> pd.DataFrame:
    checks = []
    if summary_df is None or summary_df.empty:
        return pd.DataFrame(checks)

    total_clean = summary_df["valeur_position_clean"].sum()
    max_duration = limits.get("duration_max")
    max_pvbp = limits.get("pvbp_max")
    max_issuer_weight = limits.get("poids_emetteur_max")
    max_line_weight = limits.get("poids_ligne_max")

    if max_duration is not None:
        dirty = summary_df["valeur_position_dirty"].sum()
        dur = ((summary_df["valeur_position_dirty"] / dirty) * summary_df["duration_modifiee"].fillna(0)).sum() if dirty else np.nan
        checks.append({"limite": "Duration portefeuille max", "valeur": dur, "limite_param": max_duration, "statut": "OK" if pd.isna(dur) or dur <= max_duration else "DEPASSEMENT"})

    if max_pvbp is not None:
        pvbp = summary_df["pvbp_position"].sum()
        checks.append({"limite": "PVBP total max", "valeur": pvbp, "limite_param": max_pvbp, "statut": "OK" if pvbp <= max_pvbp else "DEPASSEMENT"})

    if max_issuer_weight is not None and total_clean:
        exp = summary_df.groupby("emetteur")["valeur_position_clean"].sum() / total_clean
        worst = exp.max()
        checks.append({"limite": "Poids max par émetteur", "valeur": worst, "limite_param": max_issuer_weight, "statut": "OK" if worst <= max_issuer_weight else "DEPASSEMENT"})

    if max_line_weight is not None and total_clean:
        weights = summary_df["valeur_position_clean"] / total_clean
        worst = weights.max()
        checks.append({"limite": "Poids max par ligne", "valeur": worst, "limite_param": max_line_weight, "statut": "OK" if worst <= max_line_weight else "DEPASSEMENT"})

    return pd.DataFrame(checks)
