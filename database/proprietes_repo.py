"""
database/proprietes_repo.py
───────────────────────────────────────────────
CRUD pour la table proprietes — version SANS cache module-level.

CORRECTION : on supprime le `_cache` global qui gardait
la liste vide en mémoire entre les reboots Streamlit.
À la place : cache Streamlit natif avec TTL court et
possibilité de forcer le refresh.

API publique maintenue pour compatibilité :
  - fetch_all(force_refresh=False)        -> list[dict]
  - fetch_dict(force_refresh=False)       -> dict[int, str]
  - get_proprietes_dict(force_refresh=False) -> dict[int, str]  (alias)
  - get_propriete(prop_id, force_refresh=False) -> dict | None
  - insert_propriete(data)                -> dict
  - update_propriete(prop_id, data)       -> dict
  - delete_propriete(prop_id)             -> bool
  - clear_cache()                         -> None
"""

from __future__ import annotations

import streamlit as st

from database.supabase_client import get_supabase

TABLE = "proprietes"


# ─────────────────────────────────────────────────────────
# Fallback
# ─────────────────────────────────────────────────────────

def _fallback() -> list[dict]:
    """Données par défaut si Supabase non disponible."""
    return [
        {"id": 1, "nom": "Le Turenne",   "adresse": "Bordeaux", "actif": True},
        {"id": 2, "nom": "Villa Tobias", "adresse": "Nice",     "actif": True},
    ]


# ─────────────────────────────────────────────────────────
# Lecture (cachée)
# ─────────────────────────────────────────────────────────

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
    """Retourne toutes les propriétés actives depuis Supabase."""
    if force_refresh:
        _fetch_from_db.clear()
    return _fetch_from_db()


def fetch_dict(force_refresh: bool = False) -> dict:
    """Retourne {id: nom} pour tous les sélecteurs."""
    return {p["id"]: p["nom"] for p in fetch_all(force_refresh=force_refresh)}


def get_proprietes_dict(force_refresh: bool = False) -> dict:
    """Alias de fetch_dict() pour compatibilité avec dashboard.py."""
    return fetch_dict(force_refresh=force_refresh)


def get_propriete(prop_id: int, force_refresh: bool = False):
    """Retourne la fiche complète d'une propriété par son id."""
    for p in fetch_all(force_refresh=force_refresh):
        if p["id"] == prop_id:
            return p
    return None


# ─────────────────────────────────────────────────────────
# Écriture
# ─────────────────────────────────────────────────────────

def insert_propriete(data: dict) -> dict:
    sb = get_supabase()
    if sb is None:
        raise ConnectionError("Supabase non configuré")
    result = sb.table(TABLE).insert(data).execute()
    _fetch_from_db.clear()  # invalide le cache
    return result.data[0] if result.data else {}


def update_propriete(prop_id: int, data: dict) -> dict:
    sb = get_supabase()
    if sb is None:
        raise ConnectionError("Supabase non configuré")
    result = sb.table(TABLE).update(data).eq("id", prop_id).execute()
    _fetch_from_db.clear()  # invalide le cache
    return result.data[0] if result.data else {}


def delete_propriete(prop_id: int) -> bool:
    sb = get_supabase()
    if sb is None:
        return False
    sb.table(TABLE).update({"actif": False}).eq("id", prop_id).execute()
    _fetch_from_db.clear()  # invalide le cache
    return True


# ─────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────

def clear_cache() -> None:
    """Vide le cache — à appeler après une modification externe."""
    _fetch_from_db.clear()
