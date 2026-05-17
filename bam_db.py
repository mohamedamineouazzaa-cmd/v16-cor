
# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Tuple, Dict, Any

import pandas as pd

LOCAL_CACHE_DIR = Path.home() / ".streamlit_obligations_maroc_v5"
DB_PATH = LOCAL_CACHE_DIR / "courbes_bam.sqlite"


def _connect():
    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS bam_curves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_valeur TEXT NOT NULL,
            date_echeance TEXT NOT NULL,
            transaction_mdh REAL,
            taux_moyen_pondere REAL,
            source TEXT,
            inserted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date_valeur, date_echeance, source)
        )
        """
    )
    return con


def save_curve_sqlite(df: pd.DataFrame, source: str = "") -> None:
    if df is None or df.empty:
        return
    cols = ["date_valeur", "date_echeance", "transaction_mdh", "taux_moyen_pondere", "source"]
    data = df.copy()
    if "source" not in data.columns:
        data["source"] = source or "BAM"
    data["source"] = data["source"].fillna(source or "BAM").astype(str)
    data["date_valeur"] = pd.to_datetime(data["date_valeur"], errors="coerce").dt.strftime("%Y-%m-%d")
    data["date_echeance"] = pd.to_datetime(data["date_echeance"], errors="coerce").dt.strftime("%Y-%m-%d")
    data = data.dropna(subset=["date_valeur", "date_echeance", "taux_moyen_pondere"])
    con = _connect()
    try:
        for _, r in data[cols].iterrows():
            con.execute(
                """
                INSERT OR REPLACE INTO bam_curves
                (date_valeur, date_echeance, transaction_mdh, taux_moyen_pondere, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    r["date_valeur"],
                    r["date_echeance"],
                    float(r.get("transaction_mdh", 0.0) or 0.0),
                    float(r["taux_moyen_pondere"]),
                    str(r.get("source", source or "BAM")),
                ),
            )
        con.commit()
    finally:
        con.close()


def load_latest_curve_sqlite() -> Tuple[pd.DataFrame, Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute("SELECT MAX(date_valeur) FROM bam_curves").fetchone()
        if not row or not row[0]:
            return pd.DataFrame(), {}
        date_valeur = row[0]
        df = pd.read_sql_query(
            "SELECT date_echeance, transaction_mdh, taux_moyen_pondere, date_valeur, source FROM bam_curves WHERE date_valeur=?",
            con,
            params=(date_valeur,),
        )
        if df.empty:
            return pd.DataFrame(), {}
        df["date_echeance"] = pd.to_datetime(df["date_echeance"])
        df["date_valeur"] = pd.to_datetime(df["date_valeur"])
        return df, {"date_valeur": date_valeur, "source": "SQLite local", "rows": len(df)}
    finally:
        con.close()
