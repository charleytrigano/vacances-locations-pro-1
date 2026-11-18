"""
database/proprietes_repo.py
───────────────────────────────────────────────
Dépôt des propriétés — version SANS cache module-level.

CORRECTION : on supprime le `_cache` global qui gardait
la liste vide en mémoire entre les reboots Streamlit.
À la place : cache Streamlit natif avec TTL court et
possibilité de forcer le refresh.

API publique (compatibilité avec le reste du code) :
  - fetch_all(force_refresh=False) -> list[dict]
  - fetch_dict(force_refresh=False) -> dict[int, str]   (alias)
  - get_proprietes_dict(force_refresh=False) -> dict[int, str]
  - get_propriete(prop_id, force_refresh=False) -> dict | None
  - clear_cache() -> None
"""

from __future__ import annotations

import streamlit as st

from database.supabase_client import get_supabase

TABLE = "proprietes"


def _fallback() -> list[dict]:
    """Jeu de propriétés en dur si Supabase est injoignable."""
    return [
        {"id": 1, "nom": "Le Turenne",   "mot_de_passe": "270344", "type_client": "particulier", "actif": True},
        {"id": 2, "nom": "Villa Tobias", "mot_de_passe": "220448", "type_client": "particulier", "actif": True},
    ]


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_from_db() -> list[dict]:
    """Lecture réelle depuis Supabase, cachée 60 s par Streamlit."""
    sb = get_supabase()
    if sb is None:
        return _fallback()
    try:
        result = (
            sb.table(TABLE)
              .select("*")
              .eq("actif", True)
              .order("id")
              .execute()
        )
        data = result.data or []
        return data if data else _fallback()
    except Exception as e:
        try:
            st.warning(f"Supabase proprietes : {e}")
        except Exception:
            pass
        return _fallback()


def fetch_all(force_refresh: bool = False) -> list[dict]:
    """Retourne toutes les propriétés actives.

    Args:
        force_refresh: si True, vide le cache Streamlit et relit.
    """
    if force_refresh:
        _fetch_from_db.clear()
    return _fetch_from_db()


def get_proprietes_dict(force_refresh: bool = False) -> dict:
    """Retourne {id: nom} pour tous les logements actifs."""
    return {p["id"]: p["nom"] for p in fetch_all(force_refresh=force_refresh)}


def fetch_dict(force_refresh: bool = False) -> dict:
    """Alias historique : identique à get_proprietes_dict().

    Conservé pour la compatibilité avec services/proprietes_service.py
    """
    return get_proprietes_dict(force_refresh=force_refresh)


def get_propriete(prop_id: int, force_refresh: bool = False):
    """Retourne la fiche complète d'une propriété par son id."""
    for p in fetch_all(force_refresh=force_refresh):
        if p["id"] == prop_id:
            return p
    return None


def clear_cache() -> None:
    """Vide le cache — à appeler après une modification."""
    _fetch_from_db.clear()
