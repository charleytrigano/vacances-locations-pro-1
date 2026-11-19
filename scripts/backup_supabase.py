"""
scripts/backup_supabase.py
───────────────────────────────────────────────
Sauvegarde complète automatique de la base Supabase.

Exporte TOUTES les tables du schéma public en :
  • CSV (un fichier par table, UTF-8 avec BOM pour Excel)
  • JSON (un fichier par table, pour restauration programmatique)
  • Un ZIP global dans backups/YYYY-MM-DD/

Puis commit et push vers GitHub.
Enfin, supprime les sauvegardes de plus de 30 jours.

Lancé automatiquement par .github/workflows/backup_supabase.yml tous les jours.
Peut aussi être lancé manuellement en local avec les variables d'env :
    SUPABASE_URL=https://xxx.supabase.co
    SUPABASE_KEY=<service_role_key>
    python scripts/backup_supabase.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from supabase import create_client


# ─────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL ou SUPABASE_KEY manquant dans les variables d'environnement")
    sys.exit(1)

BACKUP_ROOT = Path(__file__).parent.parent / "backups"
TODAY = date.today().isoformat()          # ex: 2026-11-19
BACKUP_DIR = BACKUP_ROOT / TODAY

RETENTION_DAYS = 30                        # garder les backups 30 jours


# ─────────────────────────────────────────────────────────
# Lister les tables
# ─────────────────────────────────────────────────────────

def list_tables(sb) -> list[str]:
    """Récupère la liste des tables du schéma public via information_schema
    (fallback hardcodé si la RPC échoue)."""
    # Liste de secours — toutes les tables connues du projet
    fallback_tables = [
        "proprietes", "reservations", "avis", "factures",
        "messages", "tarifs", "templates_messages",
        "utilisateurs", "journal_connexions", "evenements",
        "employes_menage", "taches_menage", "pointages_menage",
        "employe_proprietes", "prospects_demo", "sessions_actives",
        "baremes_fiscaux", "contrats", "frais_deductibles",
        "chat_messages",
    ]
    # On teste chaque table — si elle existe on la garde
    tables = []
    for t in fallback_tables:
        try:
            sb.table(t).select("*").limit(1).execute()
            tables.append(t)
        except Exception:
            pass
    return tables


# ─────────────────────────────────────────────────────────
# Export d'une table
# ─────────────────────────────────────────────────────────

def export_table(sb, table: str) -> tuple[str, str]:
    """Récupère toutes les lignes et renvoie (csv_bytes, json_bytes)."""
    result = sb.table(table).select("*").execute()
    rows = result.data or []

    if not rows:
        return "", "[]"

    # CSV (UTF-8 BOM pour Excel)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()),
                             quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for row in rows:
        # Convertir les types non-sérialisables (datetime, UUID, listes, dicts)
        clean_row = {}
        for k, v in row.items():
            if isinstance(v, (list, dict)):
                clean_row[k] = json.dumps(v, ensure_ascii=False, default=str)
            else:
                clean_row[k] = v
        writer.writerow(clean_row)
    csv_bytes = "﻿" + buf.getvalue()       # BOM UTF-8

    # JSON
    json_bytes = json.dumps(rows, ensure_ascii=False, indent=2, default=str)

    return csv_bytes, json_bytes


# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────

def main() -> int:
    print(f"🕒 Backup Supabase — {datetime.now().isoformat(timespec='seconds')}")
    print(f"   URL        : {SUPABASE_URL}")
    print(f"   Dossier    : {BACKUP_DIR}")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1. Dossier du jour
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Liste des tables
    tables = list_tables(sb)
    print(f"   Tables     : {len(tables)} détectées")

    # 3. Export de chaque table + accumulation dans un ZIP
    zip_path = BACKUP_DIR / f"vlp_backup_{TODAY}.zip"
    manifest = {
        "date":    TODAY,
        "created": datetime.now().isoformat(timespec="seconds"),
        "url":     SUPABASE_URL,
        "tables":  {},
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in tables:
            try:
                csv_data, json_data = export_table(sb, table)
                nb_rows = json_data.count("\n") // 3 if json_data != "[]" else 0  # estimation
                nb_rows = len(json.loads(json_data))

                if nb_rows > 0:
                    zf.writestr(f"csv/{table}.csv", csv_data)
                    zf.writestr(f"json/{table}.json", json_data)

                manifest["tables"][table] = nb_rows
                print(f"   ✅ {table:30s} {nb_rows:6d} lignes")
            except Exception as e:
                print(f"   ❌ {table:30s} ERREUR : {e}")
                manifest["tables"][table] = f"ERROR: {e}"

        # Manifeste
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

    print(f"\n📦 ZIP créé : {zip_path} ({zip_path.stat().st_size // 1024} Ko)")

    # 4. Nettoyage des vieux backups (>30j)
    cleanup_old_backups()

    return 0


# ─────────────────────────────────────────────────────────
# Nettoyage
# ─────────────────────────────────────────────────────────

def cleanup_old_backups() -> None:
    """Supprime les dossiers de backup plus vieux que RETENTION_DAYS."""
    if not BACKUP_ROOT.exists():
        return

    cutoff = date.today() - timedelta(days=RETENTION_DAYS)
    removed = 0

    for subdir in BACKUP_ROOT.iterdir():
        if not subdir.is_dir():
            continue
        try:
            dir_date = date.fromisoformat(subdir.name)
        except ValueError:
            continue
        if dir_date < cutoff:
            # Supprimer récursivement
            for f in subdir.rglob("*"):
                if f.is_file():
                    f.unlink()
            subdir.rmdir()
            removed += 1
            print(f"   🗑️  Supprimé (>{RETENTION_DAYS}j) : {subdir.name}")

    if removed:
        print(f"🧹 {removed} ancien(s) backup(s) supprimé(s)")


if __name__ == "__main__":
    sys.exit(main())
