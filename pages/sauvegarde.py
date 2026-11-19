"""
Page Sauvegarde — Export complet des données + historique des backups auto.
Admin uniquement.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from database.supabase_client import get_supabase


def show():
    st.title("💾 Sauvegarde des données")

    if not st.session_state.get("is_admin", False):
        st.error("⛔ Accès réservé à l'administrateur.")
        return

    sb = get_supabase()
    if sb is None:
        st.error("Connexion Supabase requise.")
        return

    today = date.today().strftime("%Y%m%d")

    # ═════════════════════════════════════════════════════════════════════
    # SECTION 1 — Backups automatiques quotidiens (GitHub Actions)
    # ═════════════════════════════════════════════════════════════════════
    st.subheader("🤖 Sauvegardes automatiques quotidiennes")
    st.caption("Un backup complet de la base est créé tous les jours à 3h du matin "
               "et stocké dans ton repo GitHub. Historique conservé : 30 jours.")

    _show_auto_backups()

    st.divider()

    # ═════════════════════════════════════════════════════════════════════
    # SECTION 2 — Backup complet instantané (ZIP à télécharger)
    # ═════════════════════════════════════════════════════════════════════
    st.subheader("📦 Backup complet instantané")
    st.caption("Télécharge toute la base en un seul fichier ZIP (CSV + JSON par table). "
               "À faire avant une modification risquée ou pour archivage local.")

    if st.button("⬇️ Générer et télécharger le backup ZIP maintenant",
                 type="primary", use_container_width=True):
        with st.spinner("Génération du backup complet..."):
            zip_bytes = _generate_full_backup_zip(sb)
            if zip_bytes:
                st.download_button(
                    f"📥 Télécharger vlp_backup_{today}.zip",
                    data=zip_bytes,
                    file_name=f"vlp_backup_{today}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
                st.success(f"✅ Backup prêt ({len(zip_bytes) // 1024} Ko)")

    st.divider()

    # ═════════════════════════════════════════════════════════════════════
    # SECTION 3 — Export table par table (CSV ou Excel)
    # ═════════════════════════════════════════════════════════════════════
    st.subheader("📊 Export table par table")
    st.caption("Télécharge une seule table en CSV ou toutes en Excel.")

    tables = [
        ("reservations",     "📋 Réservations",       "reservations"),
        ("proprietes",       "🏠 Propriétés",          "proprietes"),
        ("avis",             "⭐ Avis / Livre d'or",   "avis"),
        ("tarifs",           "💶 Tarifs",              "tarifs"),
        ("templates_messages","📧 Modèles messages",   "templates"),
        ("messages",         "💬 Messages",            "messages"),
        ("factures",         "🧾 Factures",            "factures"),
        ("employes_menage",  "🧹 Employés ménage",    "employes"),
        ("taches_menage",    "🧹 Tâches ménage",      "taches"),
        ("pointages_menage", "🕒 Pointages",           "pointages"),
        ("evenements",       "🎪 Événements",          "evenements"),
        ("utilisateurs",     "👥 Utilisateurs",        "utilisateurs"),
        ("journal_connexions","📋 Journal connexions", "journal"),
    ]

    col1, col2 = st.columns(2)
    for i, (table, label, fname) in enumerate(tables):
        col = col1 if i % 2 == 0 else col2
        with col:
            try:
                data = sb.table(table).select("*").execute().data or []
                nb = len(data)
                if nb == 0:
                    st.caption(f"{label} — _vide_")
                else:
                    df = pd.DataFrame(data)
                    csv = df.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        f"⬇️ {label} ({nb})",
                        data=csv,
                        file_name=f"vlp_{fname}_{today}.csv",
                        mime="text/csv",
                        key=f"dl_{table}",
                        use_container_width=True,
                    )
            except Exception:
                pass  # table inexistante, on ignore

    st.divider()

    # ── Export TOUT en Excel ──────────────────────────────────────────────────
    if st.button("⬇️ Export complet au format Excel (.xlsx)",
                 use_container_width=True):
        with st.spinner("Génération du fichier Excel..."):
            try:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    for table, label, fname in tables:
                        try:
                            data = sb.table(table).select("*").execute().data or []
                            if data:
                                pd.DataFrame(data).to_excel(
                                    writer, sheet_name=fname[:31], index=False
                                )
                        except Exception:
                            pass
                buf.seek(0)
                st.download_button(
                    f"📥 Télécharger vlp_backup_{today}.xlsx",
                    data=buf.getvalue(),
                    file_name=f"vlp_backup_{today}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
                st.success("✅ Fichier Excel prêt !")
            except Exception as e:
                st.error(f"❌ Erreur : {e}")

    st.divider()

    # ═════════════════════════════════════════════════════════════════════
    # SECTION 4 — Télécharger le code source (scripts GitHub)
    # ═════════════════════════════════════════════════════════════════════
    st.subheader("📥 Télécharger le code source complet")
    st.caption("Récupère tous les scripts GitHub (code de l'app + workflows + backups) "
               "pour les stocker en local. À faire après chaque mise à jour majeure.")

    col_a, col_b = st.columns(2)

    with col_a:
        st.link_button(
            "⬇️ Télécharger le ZIP complet (code + data)",
            url="https://github.com/charleytrigano/vacances-locations-pro-1/archive/refs/heads/main.zip",
            use_container_width=True,
            type="primary",
        )
        st.caption("🎯 À sauvegarder dans : `D:\\LODGEPRO\\Scripts github`")

    with col_b:
        # Fournir le script de sync Windows
        sync_script = r'''@echo off
REM ═══════════════════════════════════════════════════════════════
REM Sync LodgePro — clone ou met à jour le code dans D:\LODGEPRO\Scripts github
REM A executer manuellement ou planifier avec le Planificateur de taches Windows
REM ═══════════════════════════════════════════════════════════════

set DEST=D:\LODGEPRO\Scripts github
set REPO=https://github.com/charleytrigano/vacances-locations-pro-1.git

echo.
echo === Synchronisation LodgePro vers %DEST% ===
echo.

if not exist "%DEST%" (
    echo Premiere synchronisation : clonage du repo...
    git clone %REPO% "%DEST%"
) else (
    echo Mise a jour du repo existant...
    cd /d "%DEST%"
    git pull origin main
)

echo.
echo === Terminee le %date% a %time% ===
pause
'''
        st.download_button(
            "⬇️ Script Windows de sync auto (.bat)",
            data=sync_script.encode("utf-8"),
            file_name="sync_lodgepro.bat",
            mime="application/x-bat",
            use_container_width=True,
        )
        st.caption("💡 À placer sur ton bureau, double-clique pour synchroniser")

    with st.expander("ℹ️ Comment utiliser le script de sync auto"):
        st.markdown("""
        **Première installation (une seule fois) :**

        1. Télécharge le script `sync_lodgepro.bat` (bouton ci-dessus)
        2. Place-le sur ton **Bureau Windows**
        3. Vérifie que **Git est installé** sur ton PC ([git-scm.com](https://git-scm.com/download/win))
        4. Double-clique sur `sync_lodgepro.bat`
        5. Au premier lancement : il clone le repo dans `D:\\LODGEPRO\\Scripts github`
        6. Aux lancements suivants : il met à jour (git pull) avec les derniers changements

        **Automatiser (optionnel) :**

        1. Ouvre le **Planificateur de tâches Windows**
        2. Crée une tâche qui lance `sync_lodgepro.bat` tous les jours à 18h00
        3. Comme ça ta copie locale est TOUJOURS à jour

        **Avantage :**

        Tu auras toujours une copie complète et à jour de l'app sur ton disque D:,
        même si GitHub ou Supabase ont un problème.
        """)

    st.divider()
    st.markdown("### 📅 Bonnes pratiques")
    st.markdown("""
    - ✅ **Sauvegarde auto quotidienne** → active, tourne tous les jours à 3h
    - 💾 **Avant toute mise à jour risquée** → clique sur « Backup complet ZIP maintenant »
    - 📥 **Mensuel** → télécharge l'Excel complet et stocke-le sur Google Drive/OneDrive
    - 🔒 **En cas de perte de la base** → tous les backups sont dans `/backups/` sur GitHub
    """)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _generate_full_backup_zip(sb) -> bytes | None:
    """Génère un ZIP en mémoire avec toutes les tables en CSV + JSON."""
    tables_to_backup = [
        "proprietes", "reservations", "avis", "factures",
        "messages", "tarifs", "templates_messages",
        "utilisateurs", "journal_connexions", "evenements",
        "employes_menage", "taches_menage", "pointages_menage",
        "employe_proprietes", "prospects_demo", "sessions_actives",
        "baremes_fiscaux", "contrats", "chat_messages",
    ]

    buf = io.BytesIO()
    manifest = {
        "date": date.today().isoformat(),
        "created": datetime.now().isoformat(timespec="seconds"),
        "tables": {},
    }

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in tables_to_backup:
            try:
                data = sb.table(table).select("*").execute().data or []
                if data:
                    # CSV
                    df = pd.DataFrame(data)
                    zf.writestr(f"csv/{table}.csv",
                                "﻿" + df.to_csv(index=False))
                    # JSON
                    zf.writestr(f"json/{table}.json",
                                json.dumps(data, ensure_ascii=False,
                                           indent=2, default=str))
                manifest["tables"][table] = len(data)
            except Exception as e:
                manifest["tables"][table] = f"ERROR: {e}"

        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

    buf.seek(0)
    return buf.getvalue()


def _show_auto_backups() -> None:
    """Liste les backups automatiques présents dans /backups/ du repo."""
    backups_dir = Path(__file__).parent.parent / "backups"

    if not backups_dir.exists():
        st.info("📭 Aucune sauvegarde automatique encore disponible. "
                "Le premier backup aura lieu demain à 3h du matin.")
        return

    # Liste des sous-dossiers = dates
    subdirs = sorted(
        [d for d in backups_dir.iterdir() if d.is_dir()],
        reverse=True,
    )

    if not subdirs:
        st.info("📭 Aucune sauvegarde automatique encore disponible.")
        return

    st.success(f"✅ **{len(subdirs)}** sauvegarde(s) automatique(s) dans l'historique "
               f"(dernière : **{subdirs[0].name}**)")

    # Afficher les 10 plus récentes dans un tableau
    rows = []
    for d in subdirs[:10]:
        zip_files = list(d.glob("*.zip"))
        if zip_files:
            zf = zip_files[0]
            size_ko = zf.stat().st_size // 1024
            rows.append({
                "Date":    d.name,
                "Fichier": zf.name,
                "Taille":  f"{size_ko} Ko",
            })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("💡 Pour télécharger un backup, va dans GitHub → `/backups/<date>/` "
                   "et clique sur le fichier .zip.")
