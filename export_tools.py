
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
from typing import Dict, Optional

import pandas as pd


def excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheets.items():
            if df is None:
                df = pd.DataFrame()
            df.to_excel(writer, sheet_name=name[:31], index=False)
    return bio.getvalue()


def _fmt_value(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def _safe_table(df: Optional[pd.DataFrame], columns=None, max_rows: int = 20) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if columns:
        keep = [c for c in columns if c in out.columns]
        out = out[keep]
    return out.head(max_rows).fillna("")


def _add_table(story, title, df, styles, colors, max_rows=20, columns=None, font_size=7):
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    story.append(Paragraph(title, styles["Heading2"]))
    if df is None or df.empty:
        story.append(Paragraph("Aucune donnée à afficher.", styles["BodyText"]))
        story.append(Spacer(1, 10))
        return

    tdf = _safe_table(df, columns=columns, max_rows=max_rows).astype(str)
    data = [list(tdf.columns)] + tdf.values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))


def pdf_report_bytes(
    title: str,
    kpis: dict,
    summary_df: pd.DataFrame,
    alerts_df: pd.DataFrame,
    curve_df: Optional[pd.DataFrame] = None,
    errors_df: Optional[pd.DataFrame] = None,
    scenarios_df: Optional[pd.DataFrame] = None,
    risk_df: Optional[pd.DataFrame] = None,
    cashflows_df: Optional[pd.DataFrame] = None,
    parameters: Optional[dict] = None,
) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception as e:
        raise RuntimeError("reportlab n'est pas installé. Lancez: python -m pip install reportlab") from e

    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio,
        pagesize=landscape(A4),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 10)]

    story.append(Paragraph("1. Paramètres de valorisation", styles["Heading2"]))
    params_data = [["Paramètre", "Valeur"]]
    for k, v in (parameters or {}).items():
        params_data.append([str(k), _fmt_value(v)])
    if curve_df is not None and not curve_df.empty:
        params_data.append(["Nombre de points de courbe", str(len(curve_df))])
        if "source" in curve_df.columns:
            params_data.append(["Source courbe", ", ".join(sorted(curve_df["source"].astype(str).dropna().unique())[:3])])
        if "date_valeur" in curve_df.columns and not curve_df["date_valeur"].dropna().empty:
            params_data.append(["Date valeur courbe", str(curve_df["date_valeur"].dropna().astype(str).iloc[0])])
    t_params = Table(params_data, repeatRows=1)
    t_params.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story += [t_params, Spacer(1, 12)]

    story.append(Paragraph("2. Méthodologie synthétique", styles["Heading2"]))
    methodology = """
    La valorisation est réalisée par actualisation des flux futurs. Le prix dirty correspond à la somme des flux actualisés.
    Le prix clean est obtenu en retranchant les intérêts courus. Pour les titres à taux variable, le coupon courant ou la table
    de taux du titre est utilisée lorsqu'elle est renseignée. Les spreads saisis sont ajoutés à la courbe de référence pour
    refléter le risque crédit, liquidité, subordination, spécifique et ajustement marché.
    """
    story += [Paragraph(methodology, styles["BodyText"]), Spacer(1, 12)]

    story.append(Paragraph("3. Synthèse portefeuille", styles["Heading2"]))
    kpi_data = [["Indicateur", "Valeur"]]
    for k, v in (kpis or {}).items():
        kpi_data.append([str(k), _fmt_value(v)])
    t_kpi = Table(kpi_data, repeatRows=1)
    t_kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story += [t_kpi, Spacer(1, 12)]

    summary_cols = [
        "id", "emetteur", "type", "clean_price", "dirty_price", "clean_pct_nominal",
        "ytm", "duration_modifiee", "pvbp_position", "spread_total_bps",
        "conformite_ammc", "formule_ammc", "taux_ammc", "Mi_jours", "Mr_jours", "nj_jours",
        "ligne_posterieure_auto_detectee", "zspread_market_bps", "oas_bps", "date_echeance"
    ]
    _add_table(story, "4. Résumé des titres valorisés", summary_df, styles, colors, max_rows=30, columns=summary_cols, font_size=7)

    risk_cols = ["id", "emetteur", "maturity_bucket", "valeur_position_clean", "duration_modifiee", "pvbp_position"]
    _add_table(story, "6. Contributions au risque", risk_df, styles, colors, max_rows=30, columns=risk_cols, font_size=7)

    _add_table(story, "7. Scénarios de stress", scenarios_df, styles, colors, max_rows=30, font_size=7)

    curve_cols = ["date_echeance", "tenor_years", "taux_moyen_pondere", "source", "date_valeur"]
    _add_table(story, "8. Courbe utilisée", curve_df, styles, colors, max_rows=30, columns=curve_cols, font_size=7)

    cf_cols = ["id", "date_flux", "coupon_brut", "principal", "cashflow_brut", "taux_actualisation", "df", "pv_brut"]
    _add_table(story, "9. Extrait des cash-flows indicatifs", cashflows_df, styles, colors, max_rows=40, columns=cf_cols, font_size=6)

    _add_table(story, "10. Alertes et contrôles", alerts_df, styles, colors, max_rows=30, font_size=7)
    _add_table(story, "11. Erreurs", errors_df, styles, colors, max_rows=30, font_size=7)

    story.append(Paragraph("12. Points de contrôle recommandés", styles["Heading2"]))
    controls = """
    Vérifier la fraîcheur de la courbe, les caractéristiques Maroclear, le nominal utilisé, le coupon courant des FRN,
    la marge contractuelle, les spreads, ainsi que la structure des FPCT ou titres amortissables. Pour les prix de marché,
    le z-spread ne doit être interprété que si un prix clean marché réel a été renseigné.
    """
    story.append(Paragraph(controls, styles["BodyText"]))

    doc.build(story)
    return bio.getvalue()



def pdf_simplified_report_bytes(
    title: str,
    simplified_df: pd.DataFrame,
    parameters: Optional[dict] = None,
) -> bytes:
    """
    Rapport PDF simplifié : uniquement dirty price et taux utilisé par titre.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception as e:
        raise RuntimeError("reportlab est requis pour générer le PDF. Installez-le avec : pip install reportlab") from e

    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 10)]

    if parameters:
        ptxt = "<br/>".join([f"<b>{k}</b> : {v}" for k, v in parameters.items()])
        story.append(Paragraph(ptxt, styles["BodyText"]))
        story.append(Spacer(1, 12))

    if simplified_df is None or simplified_df.empty:
        story.append(Paragraph("Aucune donnée à afficher.", styles["BodyText"]))
    else:
        tdf = simplified_df.fillna("").copy()
        for c in tdf.columns:
            if pd.api.types.is_float_dtype(tdf[c]):
                tdf[c] = tdf[c].map(lambda x: "" if pd.isna(x) else f"{x:,.4f}" if "taux" in c.lower() else f"{x:,.2f}")
        data = [list(tdf.columns)] + tdf.astype(str).values.tolist()
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)

    doc.build(story)
    return bio.getvalue()
