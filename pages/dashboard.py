"""
pages/dashboard.py
───────────────────────────────────────────────
Tableau de bord Vacances-Locations PRO

Respect du système d'authentification :
  • Admin (Charley, is_admin=True)        → voit TOUTES les propriétés
  • Propriétaire déverrouillé (ex: Le Turenne) → voit UNIQUEMENT ses propriétés
  • Pas connecté                               → message d'invitation

Corrections appliquées :
  • Filtre par get_accessible_prop_ids() du auth_service
  • force_refresh=True sur les lectures de propriétés (plus de « ? »)
  • Taux d'occupation plafonné à 100 %
  • Gère le fait que fetch_reservations() renvoie un DataFrame
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database.reservations_repo import fetch_all as fetch_reservations
from database.proprietes_repo import get_proprietes_dict
from services.auth_service import is_admin, get_accessible_prop_ids


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _fa() -> pd.DataFrame:
    """Lecture réservations → DataFrame propre.

    fetch_reservations() (depuis database/reservations_repo.py) renvoie
    DÉJÀ un pd.DataFrame nettoyé par _clean_df() — on le réutilise tel quel
    et on normalise juste les types pour le dashboard.
    """
    try:
        df = fetch_reservations()
    except Exception as e:
        st.error(f"Erreur lecture réservations : {e}")
        return pd.DataFrame()

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return pd.DataFrame()

    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df or [])
        if df.empty:
            return df

    for col in ("date_arrivee", "date_depart"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    for col in ("ca_brut", "commission", "frais_cb", "prix_net", "menage", "nuitees",
                "prix_brut", "commissions"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Harmoniser noms de colonnes legacy
    if "ca_brut" not in df.columns and "prix_brut" in df.columns:
        df["ca_brut"] = df["prix_brut"]
    if "commission" not in df.columns and "commissions" in df.columns:
        df["commission"] = df["commissions"]

    # Calculer nuitées si manquantes
    if "nuitees" in df.columns and "date_arrivee" in df.columns and "date_depart" in df.columns:
        mask = (df["nuitees"] == 0) & df["date_arrivee"].notna() & df["date_depart"].notna()
        df.loc[mask, "nuitees"] = df.loc[mask].apply(
            lambda r: (r["date_depart"] - r["date_arrivee"]).days, axis=1
        )

    return df


def _euro(x) -> str:
    try:
        return f"{float(x):,.0f} €".replace(",", " ")
    except Exception:
        return "0 €"


def _get_authorized_props() -> dict:
    """Retourne {id: nom} des propriétés que l'utilisateur courant peut voir.

    • Admin → toutes les propriétés actives
    • Propriétaire → uniquement les propriétés déverrouillées
    """
    all_props = get_proprietes_dict(force_refresh=True)
    if is_admin():
        return all_props
    allowed = get_accessible_prop_ids()
    if allowed is None:
        return all_props  # admin par défaut
    return {pid: nom for pid, nom in all_props.items() if pid in allowed}


# ─────────────────────────────────────────────────────────
# Bandeau arrivées (J-1)
# ─────────────────────────────────────────────────────────

def _bandeau_arrivees(df: pd.DataFrame, props: dict) -> None:
    if df.empty or "date_arrivee" not in df.columns:
        return
    demain = date.today() + timedelta(days=1)
    arrivees = df[df["date_arrivee"] == demain]
    if arrivees.empty:
        return

    pluriel = "s" if len(arrivees) > 1 else ""
    st.success(f"🚪 **Arrivée{pluriel} prévue{pluriel} demain ({demain.strftime('%d/%m/%Y')})**")
    for _, r in arrivees.iterrows():
        prop_nom = props.get(r.get("propriete_id"), "?")
        nom = r.get("nom_client", "—")
        plat = r.get("plateforme", "—")
        tel = r.get("telephone", "") or r.get("telephone_client", "") or "—"
        st.markdown(f"• **{nom}** — {prop_nom} — {plat} — 📞 {tel}")


# ─────────────────────────────────────────────────────────
# Vue : tableau récapitulatif des propriétés (admin OU multi-props)
# ─────────────────────────────────────────────────────────

def _show_overview(props: dict) -> None:
    st.subheader("Vue d'ensemble — toutes vos propriétés")

    df = _fa()
    if df.empty:
        st.info("Aucune réservation enregistrée.")
        return

    # Ne garder que les réservations des propriétés autorisées
    df = df[df["propriete_id"].isin(props.keys())].copy()
    if df.empty:
        st.info("Aucune réservation enregistrée pour vos propriétés.")
        return

    df["prop_nom"] = df["propriete_id"].map(props).fillna("?")

    _bandeau_arrivees(df, props)

    annees = sorted(
        {d.year for d in df["date_arrivee"] if pd.notna(d)},
        reverse=True,
    )
    if not annees:
        st.info("Aucune date d'arrivée valide dans les réservations.")
        return

    annee = st.selectbox("Année", annees, key="dash_overview_year")
    df_y = df[df["date_arrivee"].apply(lambda d: pd.notna(d) and d.year == annee)]

    rows = []
    for pid, pnom in props.items():
        df_p = df_y[df_y["propriete_id"] == pid]
        if df_p.empty:
            continue

        ca_brut = float(df_p.get("ca_brut", pd.Series(dtype=float)).sum())
        prix_net = float(df_p.get("prix_net", pd.Series(dtype=float)).sum())
        nuitees = int(df_p.get("nuitees", pd.Series(dtype=int)).sum())
        nb_res = len(df_p)

        taux_brut = nuitees / 365 * 100 if nuitees else 0
        taux = min(100.0, taux_brut)
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

    # Prochaines réservations
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
# Vue : KPIs d'une seule propriété
# ─────────────────────────────────────────────────────────

def _show_single_property(prop_id: int, props: dict) -> None:
    prop_nom = props.get(prop_id, f"Propriété #{prop_id}")

    df = _fa()
    if df.empty:
        st.info("Aucune réservation enregistrée.")
        return

    df = df[df["propriete_id"] == prop_id].copy()
    _bandeau_arrivees(df, props)

    if df.empty:
        st.info(f"Aucune réservation pour **{prop_nom}**.")
        return

    annees = sorted(
        {d.year for d in df["date_arrivee"] if pd.notna(d)},
        reverse=True,
    )
    if not annees:
        st.info("Aucune date d'arrivée valide.")
        return

    annee = st.selectbox("Année", annees, key=f"dash_year_{prop_id}")
    df_y = df[df["date_arrivee"].apply(lambda d: pd.notna(d) and d.year == annee)]

    if df_y.empty:
        st.info(f"Aucune réservation en {annee} pour {prop_nom}.")
        return

    ca_brut = float(df_y.get("ca_brut", pd.Series(dtype=float)).sum())
    commission = float(df_y.get("commission", pd.Series(dtype=float)).sum())
    frais_cb = float(df_y.get("frais_cb", pd.Series(dtype=float)).sum())
    prix_net = float(df_y.get("prix_net", pd.Series(dtype=float)).sum())
    menage = float(df_y.get("menage", pd.Series(dtype=float)).sum())
    nuitees = int(df_y.get("nuitees", pd.Series(dtype=int)).sum())
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

    # Vider le cache des propriétés à chaque rendu
    try:
        from database.proprietes_repo import clear_cache
        clear_cache()
    except Exception:
        pass

    # Propriétés auxquelles l'utilisateur courant a accès
    authorized = _get_authorized_props()

    if not authorized:
        st.warning("🔒 Aucune propriété accessible — déverrouillez-en une dans la sidebar.")
        return

    # Admin → vue d'ensemble de toutes les propriétés
    if is_admin():
        _show_overview(authorized)
        return

    # Propriétaire avec plusieurs propriétés → vue d'ensemble (filtrée)
    if len(authorized) > 1:
        # Choix dans la sidebar : toutes ou une en particulier
        choix = st.sidebar.selectbox(
            f"Propriété ({len(authorized)} accessible{'s' if len(authorized)>1 else ''})",
            ["Toutes"] + list(authorized.values()),
            key="dash_prop_filter",
        )
        if choix == "Toutes":
            _show_overview(authorized)
        else:
            prop_id = next(pid for pid, nom in authorized.items() if nom == choix)
            _show_single_property(prop_id, authorized)
        return

    # Propriétaire avec UNE SEULE propriété → vue détaillée directe
    prop_id = list(authorized.keys())[0]
    _show_single_property(prop_id, authorized)


if __name__ == "__main__":
    show()
