# -*- coding: utf-8 -*-
"""
Tests unitaires V13 — formules AMMC principales.

Lancer :
python tests.py
"""
from __future__ import annotations

from datetime import date
import math
import pandas as pd

from pricing_engine import dict_to_inputs, compute_metrics, generate_coupon_schedule


def flat_curve(rate: float, settlement: date, maturity: date):
    return pd.DataFrame({
        "date_echeance": pd.to_datetime([maturity]),
        "transaction_mdh": [0],
        "taux_moyen_pondere": [rate],
        "date_valeur": pd.to_datetime([settlement]),
        "source": ["test"],
        "days_to_maturity": [(maturity - settlement).days],
        "tenor_years": [(maturity - settlement).days / 365],
    })


def base_bond(**kw):
    b = {
        "id": "TEST",
        "emetteur": "TRESOR",
        "type": "Obligation à taux fixe in fine",
        "categorie_maroclear": "BDT",
        "nature_ligne": "Ligne normale",
        "date_emission": "2020-01-01",
        "date_jouissance": "2020-01-01",
        "date_echeance": "2030-01-01",
        "nominal_utilise": 100000,
        "quantite": 1,
        "taux_coupon_pct": 4.0,
        "frequence": "Annuelle",
        "spread_credit_bps": 0,
        "spread_liquidite_bps": 0,
        "spread_subordination_bps": 0,
        "spread_specifique_bps": 0,
        "ajustement_marche_bps": 0,
        "tax_pct": 0,
        "base_coupon": "ACT/ACT",
        "base_actualisation": "ACT/ACT",
        "mode_actualisation": "Actuarielle annuelle",
        "interpolation": "Taux linéaire",
        "utiliser_prix_marche": False,
        "prix_clean_marche_pct": float("nan"),
    }
    b.update(kw)
    return b


def assert_close(a, b, tol=1e-6):
    assert abs(a - b) <= tol, f"{a} != {b}"


def test_bdt_court_terme():
    settlement = date(2025, 11, 10)
    maturity = date(2026, 5, 11)
    issue = date(2025, 5, 12)
    rate = 0.025
    b = base_bond(
        type="BDT / zéro coupon court terme",
        date_emission=issue.isoformat(),
        date_jouissance=issue.isoformat(),
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=3.0,
        mode_actualisation="Simple",
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, _, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    Mi = (maturity - issue).days
    Mr = (maturity - settlement).days
    expected = 100000 * (1 + 0.03 * Mi / 360) / (1 + rate * Mr / 360)
    assert_close(m["dirty_price"], expected, 1e-6)
    assert m["formule_ammc"].startswith("AMMC (1)")


def test_infine_mr_moins_un_an():
    settlement = date(2025, 7, 5)
    maturity = date(2026, 1, 1)
    rate = 0.03
    b = base_bond(date_echeance=maturity.isoformat(), taux_coupon_pct=4.0)
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, _, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    Mr = (maturity - settlement).days
    expected = 100000 * (1 + 0.04) / (1 + rate * Mr / 360)
    assert_close(m["dirty_price"], expected, 1e-6)
    assert m["formule_ammc"].startswith("AMMC (2)")


def test_ligne_normale_5_ans():
    settlement = date(2026, 5, 12)
    maturity = date(2031, 12, 4)
    rate = 0.03222
    b = base_bond(
        date_emission="2021-12-04",
        date_jouissance="2021-12-04",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.5,
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    n = len(cf)
    nj = (pd.to_datetime(cf["date_flux"].iloc[0]).date() - settlement).days
    A = 365
    first_offset = nj / A
    coupon = 100000 * 0.045
    expected = sum(coupon / ((1 + rate) ** (first_offset + k - 1)) for k in range(1, n + 1))
    expected += 100000 / ((1 + rate) ** (first_offset + n - 1))
    assert_close(m["dirty_price"], expected, 1e-6)
    assert m["formule_ammc"].startswith("AMMC (4.1)")


def test_ligne_posterieure_un_flux():
    settlement = date(2029, 7, 1)
    maturity = date(2030, 1, 1)
    rate = 0.03
    b = base_bond(
        nature_ligne="Ligne postérieure",
        date_emission="2029-03-01",
        date_jouissance="2029-01-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    A = 365
    Mi = (maturity - date(2029, 3, 1)).days
    nj = (pd.to_datetime(cf["date_flux"].iloc[0]).date() - settlement).days
    expected = 100000 * (1 + 0.04 * Mi / A) / ((1 + rate) ** (nj / A))
    assert_close(m["dirty_price"], expected, 1e-6)
    assert m["formule_ammc"].startswith("AMMC (4.2)") or m["formule_ammc"].startswith("AMMC (3)")


def test_ligne_posterieure_avant_premier_coupon_auto():
    settlement = date(2026, 3, 1)
    maturity = date(2030, 1, 1)
    rate = 0.03
    b = base_bond(
        nature_ligne="Ligne normale",
        mode_calendrier_coupon="Depuis premier coupon vers avant",
        date_premier_coupon="2027-07-01",
        date_emission="2026-01-15",
        date_jouissance="2026-01-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    assert m["ligne_posterieure_auto_detectee"] is True
    assert m["formule_ammc"].startswith("AMMC (4.3)")


def test_interpolation_ammc_en_jours():
    from bam_data import interpolate_zero_rate
    curve = pd.DataFrame({
        "days_to_maturity": [100, 200],
        "tenor_years": [100/365, 200/365],
        "taux_moyen_pondere": [0.02, 0.04],
    })
    # M = 150 jours => taux = 2% + (4%-2%)*(150-100)/(200-100) = 3%
    r = interpolate_zero_rate(150/365, curve, "Taux linéaire", target_days=150)
    assert_close(r, 0.03, 1e-12)


def test_act_act_isda_multi_annees():
    from pricing_engine import year_fraction
    # Du 01/07/2027 au 01/07/2029 :
    # 184/365 + 366/366 + 181/365
    expected = 184/365 + 366/366 + 181/365
    got = year_fraction(date(2027, 7, 1), date(2029, 7, 1), "ACT/ACT")
    assert_close(got, expected, 1e-12)


def test_frn_reset_proxy_no_crash():
    settlement = date(2026, 5, 14)
    maturity = date(2028, 5, 14)
    rate = 0.025
    b = base_bond(
        id="FRN",
        type="Obligation à taux révisable / variable",
        date_emission="2023-05-14",
        date_jouissance="2023-05-14",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=3.0,
        mode_projection_variable="FRN par au prochain reset recommandé",
        coupon_courant_fixe_pct=3.0,
        frequence="Annuelle",
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, acc = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    assert not cf.empty
    assert "taux_actualisation" in cf.columns
    assert cf["taux_actualisation"].notna().all()
    assert m["dirty_price"] > 0


def test_infine_semestrielle_exposants_freq():
    settlement = date(2026, 1, 1)
    maturity = date(2028, 1, 1)
    rate = 0.03
    b = base_bond(
        id="SEMI",
        date_emission="2024-01-01",
        date_jouissance="2024-01-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        frequence="Semestrielle",
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    n = len(cf)
    coupon = 100000 * 0.04 / 2
    nj = (pd.to_datetime(cf["date_flux"].iloc[0]).date() - settlement).days
    first_offset = nj / 365
    expected = sum(coupon / ((1 + rate) ** (first_offset + (k - 1) / 2)) for k in range(1, n + 1))
    expected += 100000 / ((1 + rate) ** (first_offset + (n - 1) / 2))
    assert_close(m["dirty_price"], expected, 1e-3)


def test_amortissable_ic_sur_crd_manuel():
    settlement = date(2026, 7, 1)
    maturity = date(2030, 1, 1)
    rate = 0.03
    b = base_bond(
        id="AMORT",
        type="Obligation amortissable",
        date_emission="2020-01-01",
        date_jouissance="2020-01-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        frequence="Annuelle",
        capital_restant_du_manuel=30000,
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, acc = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    assert_close(acc["accrual_base"], 30000, 1e-9)
    assert acc["accrued_interest"] < 100000 * 0.04
    assert "Non conforme" in m["conformite_ammc"]


def test_amortissable_crd_manuel_pilote_cashflows():
    settlement = date(2026, 7, 1)
    maturity = date(2030, 1, 1)
    rate = 0.03
    b = base_bond(
        id="AMORT_CRD_CF",
        type="Obligation amortissable",
        date_emission="2020-01-01",
        date_jouissance="2020-01-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        frequence="Annuelle",
        capital_restant_du_manuel=30000,
        mode_amortissement="Amortissement constant",
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, acc = compute_metrics(inp, flat_curve(rate, settlement, maturity))

    # Le CRD manuel doit piloter le capital début du premier flux futur.
    assert_close(float(cf["capital_debut"].iloc[0]), 30000.0, 1e-9)

    # La somme du principal futur doit rembourser exactement le CRD manuel.
    assert_close(float(cf["principal"].sum()), 30000.0, 1e-6)

    # Les intérêts courus doivent aussi utiliser le même CRD.
    assert_close(float(acc["accrual_base"]), 30000.0, 1e-9)

    # Diagnostic métrique.
    assert m["crd_manuel_pilote_cashflows"] is True


def test_coupon_long_non_autorise_insere_date_intermediaire():
    settlement = date(2018, 4, 1)
    maturity = date(2021, 6, 1)
    rate = 0.03
    b = base_bond(
        id="LONG_NO",
        date_emission="2018-03-01",
        date_jouissance="2018-03-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        frequence="Annuelle",
        mode_calendrier_coupon="Depuis premier coupon vers avant",
        date_premier_coupon="2019-06-01",
        autoriser_coupon_long_contractuel=False,
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    assert cf["yf_coupon"].max() <= (1.0 / inp.frequency) * 1.10 + 1e-9
    assert int(m["coupon_long_non_confirme_count"]) == 0


def test_coupon_long_autorise_est_signale_mais_accepte():
    settlement = date(2018, 4, 1)
    maturity = date(2021, 6, 1)
    rate = 0.03
    b = base_bond(
        id="LONG_YES",
        date_emission="2018-03-01",
        date_jouissance="2018-03-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        frequence="Annuelle",
        mode_calendrier_coupon="Depuis premier coupon vers avant",
        date_premier_coupon="2019-06-01",
        autoriser_coupon_long_contractuel=True,
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    assert int(m["coupon_long_count"]) >= 1
    assert cf["jours_coupon"].max() > 365 * 1.10
    assert int(m["coupon_long_non_confirme_count"]) == 0


def test_amortissable_annuites_constantes_rembourse_crd():
    settlement = date(2026, 1, 1)
    maturity = date(2030, 1, 1)
    rate = 0.03
    b = base_bond(
        id="AMORT_ANN",
        type="Obligation amortissable",
        date_emission="2020-01-01",
        date_jouissance="2020-01-01",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        frequence="Annuelle",
        capital_restant_du_manuel=50000,
        mode_amortissement="Annuités constantes",
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    assert_close(float(cf["capital_debut"].iloc[0]), 50000.0, 1e-9)
    assert_close(float(cf["principal"].sum()), 50000.0, 1e-6)


def test_maroclear_couponpaydate_aggregation_and_mapping():
    from maroclear_ref import standardize_maroclear_columns, instrument_to_portfolio_row
    raw = pd.DataFrame([
        {
            "INSTRID": "MA_TEST_TCN", "INSTRTYPE": "FRBD", "INSTRCTGRY": "TCN",
            "ENGPREFERREDNAME": "BT TEST", "ENGLONGNAME": "BT TEST",
            "ISSUERCD": "X", "PREFERREDNAMEISSUER": "ISSUER",
            "ISSUEDT": "2025-12-25", "MATURITYDT_L": "2026-06-25",
            "PARVALUE": 100000, "NEWPARVALUE": 100000,
            "INTERESTTYPE": "FIXD", "INTERESTPERIODCTY": "HFLY", "INTERESTRATE": 3.09,
            "REDEMPTIONTYPE": "BLET", "AMORTFREQ": None, "INSTRSTATUS": "ACTI",
            "CouponPayDate": "2026-06-25",
        },
        {
            "INSTRID": "MA_TEST_TCN", "INSTRTYPE": "FRBD", "INSTRCTGRY": "TCN",
            "ENGPREFERREDNAME": "BT TEST", "ENGLONGNAME": "BT TEST",
            "ISSUERCD": "X", "PREFERREDNAMEISSUER": "ISSUER",
            "ISSUEDT": "2025-12-25", "MATURITYDT_L": "2026-06-25",
            "PARVALUE": 100000, "NEWPARVALUE": 100000,
            "INTERESTTYPE": "FIXD", "INTERESTPERIODCTY": "HFLY", "INTERESTRATE": 3.09,
            "REDEMPTIONTYPE": "BLET", "AMORTFREQ": None, "INSTRSTATUS": "ACTI",
            "CouponPayDate": "2026-06-25",
        },
    ])
    ref = standardize_maroclear_columns(raw)
    assert len(ref) == 1
    assert ref.iloc[0]["app_bond_type"] == "BDT / zéro coupon court terme"
    assert ref.iloc[0]["coupon_frequency_label"] == "Semestrielle"
    assert int(ref.iloc[0]["coupon_dates_count"]) == 1
    row = instrument_to_portfolio_row(ref.iloc[0].to_dict(), quantity=1)
    assert row["mode_calendrier_coupon"] == "Maroclear CouponPayDate"
    assert row["base_coupon"] == "ACT/360"
    assert row["spread_credit_bps"] == 0.0


def test_maroclear_schedule_backfills_previous_coupon():
    b = base_bond(
        id="MCL_SCHED",
        date_emission="2024-07-31",
        date_jouissance="2024-07-31",
        date_echeance="2035-06-18",
        taux_coupon_pct=3.55,
        frequence="Annuelle",
        mode_calendrier_coupon="Maroclear CouponPayDate",
        maroclear_coupon_dates="2026-06-18|2027-06-18|2028-06-18|2029-06-18|2030-06-18|2031-06-18|2032-06-18|2033-06-18|2034-06-18|2035-06-18",
        date_premier_coupon="2026-06-18",
    )
    inp = dict_to_inputs(b, {"valuation_date": date(2026, 5, 14), "settlement_date": date(2026, 5, 14)})
    sched = generate_coupon_schedule(inp)
    # La date précédente 2025-06-18 est reconstruite pour calculer les IC correctement.
    assert date(2025, 6, 18) in sched
    assert sched[-1] == date(2035, 6, 18)


def test_amortissable_coupon_constant_bissextile():
    settlement = date(2026, 5, 14)
    maturity = date(2051, 5, 3)
    rate = 0.04
    b = base_bond(
        id="AMORT_LEAP",
        type="Obligation amortissable",
        date_emission="2021-05-03",
        date_jouissance="2021-05-03",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=3.59,
        frequence="Annuelle",
        mode_calendrier_coupon="Maroclear CouponPayDate",
        maroclear_coupon_dates="2022-05-03|2023-05-03|2024-05-03|2025-05-03|2026-05-03|2027-05-03|2028-05-03|2029-05-03|2030-05-03|2031-05-03|2032-05-03|2033-05-03|2034-05-03|2035-05-03|2036-05-03|2037-05-03|2038-05-03|2039-05-03|2040-05-03|2041-05-03|2042-05-03|2043-05-03|2044-05-03|2045-05-03|2046-05-03|2047-05-03|2048-05-03|2049-05-03|2050-05-03|2051-05-03",
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(rate, settlement, maturity))
    # Flux 2028 inclut une période 366 jours dans certains calendriers, mais le coupon doit rester CRD*tf/freq.
    r2028 = cf[pd.to_datetime(cf["date_flux"]).dt.date == date(2028, 5, 3)].iloc[0]
    expected_coupon = float(r2028["capital_debut"]) * 0.0359
    assert_close(float(r2028["coupon_brut"]), expected_coupon, 1e-9)


def test_taux_actualisation_affiche_arrondi():
    settlement = date(2026, 5, 14)
    maturity = date(2028, 5, 14)
    curve = pd.DataFrame({
        "date_echeance": pd.to_datetime([maturity]),
        "transaction_mdh": [0],
        "taux_moyen_pondere": [0.03221987],
        "date_valeur": pd.to_datetime([settlement]),
        "source": ["test"],
        "days_to_maturity": [(maturity - settlement).days],
        "tenor_years": [(maturity - settlement).days / 365],
    })
    b = base_bond(date_echeance=maturity.isoformat(), taux_coupon_pct=4.0)
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    _, cf, _ = compute_metrics(inp, curve)
    assert_close(float(cf["taux_actualisation"].iloc[0]), 0.03222, 1e-12)


def test_differe_amortissement_crd_obligatoire():
    settlement = date(2026, 5, 14)
    maturity = date(2031, 5, 14)
    b = base_bond(
        id="AMORT_GRACE",
        type="Obligation amortissable",
        date_emission="2021-05-14",
        date_jouissance="2021-05-14",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        frequence="Annuelle",
        mode_amortissement="Différé d’amortissement / CRD obligatoire",
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    m, cf, _ = compute_metrics(inp, flat_curve(0.04, settlement, maturity))
    assert "CRD manuel obligatoire" in m["conformite_ammc"]


def test_spread_added_after_curve_rounding():
    from pricing_engine import taux_courbe_arrondi_plus_spread
    # 3.221987% doit d'abord devenir 3.222%, puis +80 bps = 4.022%.
    got = taux_courbe_arrondi_plus_spread(0.03221987, 0.0080)
    assert_close(got, 0.04022, 1e-12)


def test_cashflow_taux_actualisation_spread_after_rounding():
    settlement = date(2026, 5, 14)
    maturity = date(2028, 5, 14)
    curve = pd.DataFrame({
        "date_echeance": pd.to_datetime([maturity]),
        "transaction_mdh": [0],
        "taux_moyen_pondere": [0.03221987],
        "date_valeur": pd.to_datetime([settlement]),
        "source": ["test"],
        "days_to_maturity": [(maturity - settlement).days],
        "tenor_years": [(maturity - settlement).days / 365],
    })
    b = base_bond(
        id="SPREAD_ROUND",
        date_echeance=maturity.isoformat(),
        taux_coupon_pct=4.0,
        spread_credit_bps=80,
    )
    inp = dict_to_inputs(b, {"valuation_date": settlement, "settlement_date": settlement})
    _, cf, _ = compute_metrics(inp, curve)
    assert_close(float(cf["taux_zero_interpole"].iloc[0]), 0.03222, 1e-12)
    assert_close(float(cf["spread_total"].iloc[0]), 0.00800, 1e-12)
    assert_close(float(cf["taux_actualisation"].iloc[0]), 0.04022, 1e-12)


if __name__ == "__main__":
    tests = [
        test_bdt_court_terme,
        test_infine_mr_moins_un_an,
        test_ligne_normale_5_ans,
        test_ligne_posterieure_un_flux,
        test_ligne_posterieure_avant_premier_coupon_auto,
        test_interpolation_ammc_en_jours,
        test_act_act_isda_multi_annees,
        test_frn_reset_proxy_no_crash,
        test_infine_semestrielle_exposants_freq,
        test_amortissable_ic_sur_crd_manuel,
        test_amortissable_crd_manuel_pilote_cashflows,
        test_coupon_long_non_autorise_insere_date_intermediaire,
        test_coupon_long_autorise_est_signale_mais_accepte,
        test_amortissable_annuites_constantes_rembourse_crd,
        test_maroclear_couponpaydate_aggregation_and_mapping,
        test_maroclear_schedule_backfills_previous_coupon,
        test_amortissable_coupon_constant_bissextile,
        test_taux_actualisation_affiche_arrondi,
        test_differe_amortissement_crd_obligatoire,
        test_spread_added_after_curve_rounding,
        test_cashflow_taux_actualisation_spread_after_rounding,
    ]
    for t in tests:
        t()
        print("OK", t.__name__)
    print("Tous les tests AMMC V16 sont OK.")
