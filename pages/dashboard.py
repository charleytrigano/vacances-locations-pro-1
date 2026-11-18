"""
pages/dashboard.py
───────────────────────────────────────────────
Tableau de bord Vacances-Locations PRO

Corrections appliquées :
  • force_refresh=True sur les lectures de propriétés
    → plus de « ? » à la place du nom de propriété.
  • taux d'occupation plafonné à 100 %
    → plus de 215 % absurde.
  • Bandeau arrivées = veille uniquement, disparait le jour J.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database.reservations_repo import fetch_all as fetch_reservations
from database.proprietes_repo import fetch_all as fetch_proprietes
from database.proprietes_repo import get_proprietes_dict


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _fa(force_refresh: bool = False) -> pd.DataFrame:
    """Lecture réservations → DataFrame propre."""
    data = fetch_reservations(force_refresh=force_refresh) if _accepts_refresh(fetch_reservations) else fetch_reservations()
    df = pd.DataFrame(data or [])
    if df.empty:
        return df

    for col in ("date_arrivee", "date_depart"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    for col in ("ca_brut", "commission", "frais_cb", "prix_net", "menage", "nuitees"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "nuitees" in df.columns and "date_arrivee" in df.columns and "date_depart" in df.columns:
        mask = (df["nuitees"] == 0) & df["date_arrivee"].notna() & df["date_depart"].notna()
        df.loc[mask, "nuitees"] = df.loc[mask].apply(
            lambda r: (r["date_depart"] - r["date_arrivee"]).days, axis=1
        )

    return df


def _accepts_refresh(fn) -> bool:
    import inspect
    try:
        return "force_refresh" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _euro(x: float) -> str:
    try:
        return f"{float(x):,.0f} €".replace(",", " ")
    except Exception:
        return "0 €"


# ─────────────────────────────────────────────────────────
# Bandeau arrivées (J-1)
# ─────────────────────────────────────────────────────────

def _bandeau_arrivees(df: pd.DataFrame, props: dict[int, str]) -> None:
    if df.empty or "date_arrivee" not in df.columns:
        return
    demain = date.today() + timedelta(days=1)
    arrivees = df[df["date_arrivee"] == demain]
    if arrivees.empty:
        return

    st.success(f"🚪 **Arrivée{'s' if len(arrivees) > 1 else ''} prévue{'s' if len(arrivees) > 1 else ''} demain ({demain.strftime('%d/%m/%Y')})**")
    for _, r in arrivees.iterrows():
        prop_nom = props.get(r.get("propriete_id"), "?")
        nom = r.get("nom_client", "—")
        plat = r.get("plateforme", "—")
        tel = r.get("telephone", "") or r.get("telephone_client", "") or "—"
        st.markdown(f"• **{nom}** — {prop_nom} — {plat} — 📞 {tel}")


# ─────────────────────────────────────────────────────────
# Vue admin : tableau récapitulatif des propriétés
# ─────────────────────────────────────────────────────────

def _show_admin_overview() -> None:
    st.subheader("Vue d'ensemble — toutes propriétés")

    df = _fa(force_refresh=True)
    props = get_proprietes_dict(force_refresh=True)

    if df.empty:
        st.info("Aucune réservation enregistrée.")
        return

    df["prop_nom"] = df["propriete_id"].map(props).fillna("?")

    annee = st.selectbox(
        "Année",
        sorted({d.year for d in df["date_arrivee"] if pd.notna(d)}, reverse=True),
        key="dash_admin_year",
    )
    df_y = df[df["date_arrivee"].apply(lambda d: pd.notna(d) and d.year == annee)]

    rows = []
    for pid, pnom in props.items():
        df_p = df_y[df_y["propriete_id"] == pid]
        if df_p.empty:
            continue

        ca_brut = float(df_p.get("ca_brut", pd.Series(0)).sum())
        prix_net = float(df_p.get("prix_net", pd.Series(0)).sum())
        nuitees = int(df_p.get("nuitees", pd.Series(0)).sum())
        nb_res = len(df_p)

        taux_brut = nuitees / 365 * 100 if nuitees else 0
        taux = min(100.0, taux_brut)  # ⚠️ plafonné à 100 %
        rev_nuit = prix_net / nuitees if nuitees else 0

        rows.append({
            "Propriété": pnom,
            "Réservations": nb_res,
            "Nuitées": nuitees,
            "CA Brut": _euro(ca_brut),
            "Prix Net": _euro(prix_net),
            "Revenu / nuit": _euro(rev_nuit),
            "Taux occupation": f"{taux:.0f} %",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info(f"Aucune réservation en {annee}.")

    # Prochaines réservations (toutes propriétés confondues)
    st.subheader("🗓️ Prochaines réservations")
    today = date.today()
    df_future = df[df["date_arrivee"].apply(lambda d: pd.notna(d) and d >= today)].copy()
    df_future = df_future.sort_values("date_arrivee").head(15)
    if df_future.empty:
        st.info("Pas de réservation à venir.")
    else:
        cols = ["prop_nom", "nom_client", "date_arrivee", "date_depart", "plateforme", "ca_brut"]
        cols = [c for c in cols if c in df_future.columns]
        show = df_future[cols].rename(columns={
            "prop_nom": "Propriété",
            "nom_client": "Client",
            "date_arrivee": "Arrivée",
            "date_depart": "Départ",
            "plateforme": "Plateforme",
            "ca_brut": "CA Brut",
        })
        st.dataframe(show, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────
# Vue propriétaire : KPIs d'une seule propriété
# ─────────────────────────────────────────────────────────

def _show_single_property(prop_id: int) -> None:
    props = get_proprietes_dict(force_refresh=True)
    prop_nom = props.get(prop_id, f"Propriété #{prop_id}")

    df = _fa(force_refresh=True)
    if df.empty:
        st.info("Aucune réservation enregistrée.")
        return

    df = df[df["propriete_id"] == prop_id]
    _bandeau_arrivees(df, props)

    if df.empty:
        st.info(f"Aucune réservation pour **{prop_nom}**.")
        return

    annee = st.selectbox(
        "Année",
        sorted({d.year for d in df["date_arrivee"] if pd.notna(d)}, reverse=True),
        key=f"dash_year_{prop_id}",
    )
    df_y = df[df["date_arrivee"].apply(lambda d: pd.notna(d) and d.year == annee)]

    if df_y.empty:
        st.info(f"Aucune réservation en {annee} pour {prop_nom}.")
        return

    ca_brut = float(df_y.get("ca_brut", pd.Series(0)).sum())
    commission = float(df_y.get("commission", pd.Series(0)).sum())
    frais_cb = float(df_y.get("frais_cb", pd.Series(0)).sum())
    prix_net = float(df_y.get("prix_net", pd.Series(0)).sum())
    menage = float(df_y.get("menage", pd.Series(0)).sum())
    nuitees = int(df_y.get("nuitees", pd.Series(0)).sum())
    nb_res = len(df_y)
    rev_nuit = prix_net / nuitees if nuitees else 0
    taux = min(100.0, nuitees / 365 * 100) if nuitees else 0

    st.markdown(f"### 📊 {prop_nom} — {annee}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 CA Brut", _euro(ca_brut))
    c2.metric("🔖 Commissions", _euro(commission))
    c3.metric("💳 Frais CB", _euro(frais_cb))
    c4.metric("💵 Prix Net", _euro(prix_net))
    c5.metric("🧹 Ménage", _euro(menage))

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("📈 Revenu / nuit", _euro(rev_nuit))
    c7.metric("🏡 Taux occupation", f"{taux:.0f} %")
    c8.metric("🌙 Nuitées", nuitees)
    c9.metric("📅 Réservations", nb_res)


# ─────────────────────────────────────────────────────────
# Entrée principale
# ─────────────────────────────────────────────────────────

def show() -> None:
    st.title("📊 Tableau de bord")

    # Vide le cache à chaque rendu (safe, lent : 1 appel réseau de +)
    try:
        from database.proprietes_repo import clear_cache
        clear_cache()
    except Exception:
        pass

    auth = st.session_state.get("auth_properties", [])
    is_admin = st.session_state.get("is_admin", False)

    props = get_proprietes_dict(force_refresh=True)

    if is_admin or (isinstance(auth, list) and len(auth) > 1):
        # Filtre propriété dans la sidebar
        options = [("Toutes", None)] + [(nom, pid) for pid, nom in props.items()]
        labels = [o[0] for o in options]
        choix = st.sidebar.selectbox(
            f"Propriété (Toutes ({len(props)}))",
            labels,
            key="dash_prop_filter",
        )
        prop_id = dict(zip(labels, [o[1] for o in options]))[choix]

        if prop_id is None:
            _show_admin_overview()
        else:
            _show_single_property(prop_id)
    else:
        # Mode propriétaire : une seule propriété
        prop_id = auth[0] if isinstance(auth, list) and auth else st.session_state.get("propriete_id")
        if prop_id is None:
            st.warning("Aucune propriété associée à votre compte.")
            return
        _show_single_property(prop_id)


if __name__ == "__main__":
    show()
