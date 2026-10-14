"""Lightweight internationalization (i18n).

Language switching happens live, without a page reload, by binding every
translatable element's text to a per-client :class:`LangState` object. When the
selected language changes, NiceGUI's binding system updates all bound elements.
The choice is also persisted to ``app.storage.user`` and to the user's account
row in the database.
"""

from __future__ import annotations

from nicegui import app, binding, ui

DEFAULT_LANGUAGE = 'en'

# Selectable languages: code -> native display name.
LANGUAGES: dict[str, str] = {
    'en': 'English',
    'de': 'Deutsch',
    'fr': 'Français',
}

# key -> {lang: text}.  Missing translations fall back to English, then the key.
_TRANSLATIONS: dict[str, dict[str, str]] = {
    # Sidebar navigation
    'nav.dashboard':      {'en': 'Dashboard', 'de': 'Dashboard', 'fr': "Tableau de bord"},
    'nav.shipping':       {'en': 'Shipping', 'de': 'Versand', 'fr': "Expéditions"},
    'nav.production':     {'en': 'Production', 'de': 'Produktion', 'fr': "Production"},
    'nav.orders':         {'en': 'Orders', 'de': 'Aufträge', 'fr': "Commandes"},
    'nav.pallets':        {'en': 'Pallets', 'de': 'Paletten', 'fr': "Palettes"},
    'nav.packing':        {'en': 'Packing', 'de': 'Verpackung', 'fr': "Conditionnement"},
    'nav.print_demo':     {'en': 'Print Demo', 'de': 'Druckdemo', 'fr': "Démo d’impression"},
    'nav.icons':          {'en': 'Icons', 'de': 'Symbole', 'fr': "Icônes"},
    'nav.design_system':  {'en': 'Design System', 'de': 'Designsystem', 'fr': "Design System"},
    'nav.users':          {'en': 'Users', 'de': 'Benutzer', 'fr': "Utilisateurs"},
    'action.collapse':    {'en': 'Collapse', 'de': 'Einklappen', 'fr': "Réduire"},

    # Mobile burger sheet & About dialog
    'menu.all_sections':  {'en': 'All sections', 'de': 'Alle Bereiche', 'fr': "Toutes les sections"},
    'menu.about':         {'en': 'About', 'de': 'Über', 'fr': "À propos"},
    'menu.menu':          {'en': 'Menu', 'de': 'Menü', 'fr': "Menu"},
    'nav.home':           {'en': 'Home', 'de': 'Start', 'fr': "Accueil"},
    'about.title':        {'en': 'About This App', 'de': 'Über diese App', 'fr': "À propos de cette application"},
    'about.body':         {'en': 'Built with NiceGUI and Python. A modern, fully responsive web application.',
                           'de': 'Erstellt mit NiceGUI und Python. Eine moderne, vollständig responsive Web-Anwendung.',
                           'fr': "Construite avec NiceGUI et Python. Une application web moderne et entièrement responsive."},
    'about.source':       {'en': 'View source code on GitHub:', 'de': 'Quellcode auf GitHub ansehen:', 'fr': "Voir le code source sur GitHub :"},
    'about.repo':         {'en': 'GitHub Repository', 'de': 'GitHub-Repository', 'fr': "Dépôt GitHub"},
    'action.close':       {'en': 'Close', 'de': 'Schließen', 'fr': "Fermer"},

    # Account dropdown
    'account.account':    {'en': 'Account', 'de': 'Konto', 'fr': "Compte"},
    'account.settings':   {'en': 'Settings', 'de': 'Einstellungen', 'fr': "Paramètres"},
    'account.logout':     {'en': 'Logout', 'de': 'Abmelden', 'fr': "Déconnexion"},
    'account.guest':      {'en': 'Guest', 'de': 'Gast', 'fr': "Invité"},
    'language.label':     {'en': 'Language', 'de': 'Sprache', 'fr': "Langue"},

    # User settings page
    'settings.title':          {'en': 'Account settings', 'de': 'Kontoeinstellungen', 'fr': "Paramètres du compte"},
    'settings.subtitle':       {'en': 'Manage your profile and preferences', 'de': 'Verwalte dein Profil und deine Einstellungen', 'fr': "Gérez votre profil et vos préférences"},
    'settings.profile':        {'en': 'Profile', 'de': 'Profil', 'fr': "Profil"},
    'settings.profile_desc':   {'en': 'Update your photo and personal details.', 'de': 'Aktualisiere dein Foto und deine persönlichen Daten.', 'fr': "Mettez à jour votre photo et vos informations personnelles."},
    'settings.preferences_desc':{'en': 'Language and appearance of the app, saved to your account.', 'de': 'Sprache und Erscheinungsbild der App, im Konto gespeichert.', 'fr': "Langue et apparence de l’application, enregistrées dans votre compte."},
    'settings.theme':          {'en': 'Theme', 'de': 'Design', 'fr': "Thème"},
    'settings.theme_light':    {'en': 'Light', 'de': 'Hell', 'fr': "Clair"},
    'settings.theme_dark':     {'en': 'Dark', 'de': 'Dunkel', 'fr': "Sombre"},
    'settings.theme_saved':    {'en': 'Theme saved', 'de': 'Design gespeichert', 'fr': "Thème enregistré"},
    'settings.federated_pw':   {'en': 'Your password is managed by your identity provider',
                                'de': 'Ihr Passwort wird von Ihrem Identitätsanbieter verwaltet',
                                'fr': "Votre mot de passe est géré par votre fournisseur d’identité"},
    'settings.federated_pw_desc': {'en': 'This account signs in through an external provider (e.g. Keycloak). '
                                          'To change your password, use the provider\'s own account page.',
                                   'de': 'Dieses Konto meldet sich über einen externen Anbieter an (z. B. Keycloak). '
                                         'Um Ihr Passwort zu ändern, nutzen Sie die Kontoseite des Anbieters.',
                                         'fr': "Ce compte se connecte via un fournisseur externe (ex. Keycloak). Pour changer votre mot de passe, utilisez la page de compte du fournisseur."},
    'settings.change_pw_provider': {'en': 'Provider sign-in page', 'de': 'Anmelde-Seite des Anbieters', 'fr': "Page de connexion du fournisseur"},
    'settings.security_desc':  {'en': 'Set a strong, unique password to protect your account.', 'de': 'Lege ein starkes, einzigartiges Passwort zum Schutz deines Kontos fest.', 'fr': "Définissez un mot de passe fort et unique pour protéger votre compte."},
    'settings.photo':          {'en': 'Profile photo', 'de': 'Profilbild', 'fr': "Photo de profil"},
    'settings.upload_photo':   {'en': 'Upload photo', 'de': 'Foto hochladen', 'fr': "Téléverser une photo"},
    'settings.remove_photo':   {'en': 'Remove', 'de': 'Entfernen', 'fr': "Retirer"},
    'settings.display_name':   {'en': 'Display name', 'de': 'Anzeigename', 'fr': "Nom affiché"},
    'settings.email':          {'en': 'Email', 'de': 'E-Mail', 'fr': "E-mail"},
    'settings.username':       {'en': 'Username', 'de': 'Benutzername', 'fr': "Nom d’utilisateur"},
    'settings.role':           {'en': 'Role', 'de': 'Rolle', 'fr': "Rôle"},
    'settings.save':           {'en': 'Save changes', 'de': 'Änderungen speichern', 'fr': "Enregistrer les modifications"},
    'settings.saved':          {'en': 'Profile updated.', 'de': 'Profil aktualisiert.', 'fr': "Profil mis à jour."},
    'settings.preferences':    {'en': 'Preferences', 'de': 'Einstellungen', 'fr': "Préférences"},
    'settings.security':       {'en': 'Security', 'de': 'Sicherheit', 'fr': "Sécurité"},
    'settings.change_password':{'en': 'Change password', 'de': 'Passwort ändern', 'fr': "Changer le mot de passe"},
    'settings.new_password':   {'en': 'New password', 'de': 'Neues Passwort', 'fr': "Nouveau mot de passe"},
    'settings.confirm_password':{'en': 'Confirm password', 'de': 'Passwort bestätigen', 'fr': "Confirmer le mot de passe"},
    'settings.update_password':{'en': 'Update password', 'de': 'Passwort aktualisieren', 'fr': "Mettre à jour le mot de passe"},
    'settings.password_updated':{'en': 'Password updated.', 'de': 'Passwort aktualisiert.', 'fr': "Mot de passe mis à jour."},
    'settings.invalid_email':  {'en': 'Please enter a valid email address.', 'de': 'Bitte eine gültige E-Mail-Adresse eingeben.', 'fr': "Veuillez saisir une adresse e-mail valide."},
    'settings.language_saved': {'en': 'Language updated.', 'de': 'Sprache aktualisiert.', 'fr': "Langue mise à jour."},
    'settings.image_too_large':{'en': 'Image is too large (max 2 MB).', 'de': 'Bild ist zu groß (max. 2 MB).', 'fr': "L’image est trop volumineuse (max 2 Mo)."},
    'settings.image_bad_format': {'en': 'Unsupported image format — only PNG and JPEG are allowed.', 'de': 'Nicht unterstütztes Bildformat — nur PNG und JPEG sind erlaubt.', 'fr': "Format d’image non pris en charge — seuls PNG et JPEG sont autorisés."},
    'settings.image_rejected': {'en': 'File rejected: unsupported format or larger than 2 MB (PNG/JPEG only).', 'de': 'Datei abgelehnt: nicht unterstütztes Format oder größer als 2 MB (nur PNG/JPEG).', 'fr': "Fichier rejeté : format non pris en charge ou supérieur à 2 Mo (PNG/JPEG uniquement)."},
    'settings.saved_profile': {'en': 'Profile updated. Reload the page to see the changes everywhere.', 'de': 'Profil aktualisiert. Laden Sie die Seite neu, um die Änderungen überall zu sehen.', 'fr': "Profil mis à jour. Rechargez la page pour voir les changements partout."},
    'settings.clear_changes': {'en': 'Clear changes', 'de': 'Änderungen verwerfen', 'fr': "Annuler les modifications"},
    'settings.changes_cleared': {'en': 'Changes discarded — saved values restored.', 'de': 'Änderungen verworfen — gespeicherte Werte wiederhergestellt.', 'fr': "Modifications annulées — valeurs enregistrées restaurées."},
    'settings.password_not_met':{'en': 'Password does not meet the requirements.', 'de': 'Passwort erfüllt die Anforderungen nicht.', 'fr': "Le mot de passe ne répond pas aux exigences."},

    # Avatar dropzone
    'dropzone.title':          {'en': 'Drag & drop an image here', 'de': 'Bild hierher ziehen & ablegen', 'fr': "Glissez-déposez une image ici"},
    'dropzone.hint':           {'en': 'or click to browse · PNG, JPG up to 2 MB', 'de': 'oder klicken zum Auswählen · PNG, JPG bis 2 MB', 'fr': "ou cliquez pour parcourir · PNG, JPG jusqu’à 2 Mo"},

    # Password requirements
    'password.req.length':     {'en': '{min}\u2013{max} characters', 'de': '{min}\u2013{max} Zeichen', 'fr': "{min}–{max} caractères"},
    'password.req.upper':      {'en': 'At least one uppercase letter', 'de': 'Mindestens ein Großbuchstabe', 'fr': "Au moins une majuscule"},
    'password.req.lower':      {'en': 'At least one lowercase letter', 'de': 'Mindestens ein Kleinbuchstabe', 'fr': "Au moins une minuscule"},
    'password.req.number':     {'en': 'At least one number', 'de': 'Mindestens eine Zahl', 'fr': "Au moins un chiffre"},
    'password.req.special':    {'en': 'At least one special character', 'de': 'Mindestens ein Sonderzeichen', 'fr': "Au moins un caractère spécial"},
    'password.match':          {'en': 'Passwords match', 'de': 'Passwörter stimmen überein', 'fr': "Les mots de passe correspondent"},

    # Dashboard view
    'dashboard.title':          {'en': 'Dashboard', 'de': 'Dashboard', 'fr': "Tableau de bord"},
    'dashboard.subtitle':       {'en': 'Live overview · refreshes on demand', 'de': 'Live-Übersicht · aktualisiert bei Bedarf', 'fr': "Vue en direct · actualisée à la demande"},
    'dashboard.refresh':        {'en': 'Refresh', 'de': 'Aktualisieren', 'fr': "Actualiser"},
    'dashboard.kpi.orders':     {'en': 'Total Orders', 'de': 'Aufträge gesamt', 'fr': "Commandes totales"},
    'dashboard.kpi.revenue':    {'en': 'Revenue total', 'de': 'Umsatz gesamt', 'fr': "Revenus totaux"},
    'dashboard.kpi.shipments':  {'en': 'Active Shipments', 'de': 'Aktive Sendungen', 'fr': "Expéditions actives"},
    'dashboard.kpi.throughput': {'en': 'Production Rate', 'de': 'Produktionsrate', 'fr': "Cadence de production"},
    'dashboard.revenue_trend':  {'en': 'Revenue Trend', 'de': 'Umsatzverlauf', 'fr': "Tendance des revenus"},
    'dashboard.order_status':   {'en': 'Order Status', 'de': 'Auftragsstatus', 'fr': "Statut des commandes"},
    'dashboard.daily_orders':   {'en': 'Daily Orders', 'de': 'Tägliche Aufträge', 'fr': "Commandes quotidiennes"},
    'dashboard.throughput':     {'en': 'Production Throughput', 'de': 'Produktionsdurchsatz', 'fr': "Débit de production"},

    # Shipping view
    'shipping.title':     {'en': 'Shipping', 'de': 'Versand', 'fr': "Expéditions"},
    'shipping.subtitle':  {'en': 'Manage outbound shipments and carrier assignments.', 'de': 'Ausgehende Sendungen und Frachtführerzuordnungen verwalten.', 'fr': "Gérez les expéditions sortantes et les transporteurs."},
    'shipping.add':       {'en': '+ Add Shipment', 'de': '+ Sendung hinzufügen', 'fr': "+ Ajouter une expédition"},

    # Production view
    'production.title':     {'en': 'Production', 'de': 'Produktion', 'fr': "Production"},
    'production.subtitle':  {'en': 'Monitor line status, work orders and throughput.', 'de': 'Linienstatus, Arbeitsaufträge und Durchsatz überwachen.', 'fr': "Suivez l’état des lignes, les ordres de fabrication et le débit."},
    'production.add':       {'en': '+ New Work Order', 'de': '+ Neuer Arbeitsauftrag', 'fr': "+ Nouvel ordre de fabrication"},

    # Orders view
    'orders.title':     {'en': 'Orders', 'de': 'Aufträge', 'fr': "Commandes"},
    'orders.subtitle':  {'en': 'Track and manage incoming customer orders.', 'de': 'Eingehende Kundenaufträge verfolgen und verwalten.', 'fr': "Suivez et gérez les commandes clients entrantes."},
    'orders.add':       {'en': '+ New Order', 'de': '+ Neuer Auftrag', 'fr': "+ Nouvelle commande"},

    # Pallets view
    'pallets.title':     {'en': 'Pallets', 'de': 'Paletten', 'fr': "Palettes"},
    'pallets.subtitle':  {'en': 'Track pallet inventory, locations and capacity utilisation.', 'de': 'Palettenbestand, Standorte und Kapazitätsauslastung verfolgen.', 'fr': "Suivez l’inventaire des palettes, les emplacements et le taux d’utilisation."},
    'pallets.add':       {'en': '+ Register Pallet', 'de': '+ Palette registrieren', 'fr': "+ Enregistrer une palette"},

    # Packing view
    'packing.title':     {'en': 'Packings', 'de': 'Verpackungen', 'fr': "Conditionnement"},
    'packing.subtitle':  {'en': 'Manage packing jobs across all stages.', 'de': 'Verpackungsaufträge über alle Phasen hinweg verwalten.', 'fr': "Gérez les tâches de conditionnement à toutes les étapes."},
    'packing.add':       {'en': '+ New Job', 'de': '+ Neuer Auftrag', 'fr': "+ Nouvelle tâche"},

    # Icons view
    'icons.title':     {'en': 'Icon Browser', 'de': 'Symbol-Browser', 'fr': "Navigateur d’icônes"},
    'icons.subtitle':  {'en': '{tabler} Tabler icons + {material} Material icons — click any icon to copy its class string.', 'de': '{tabler} Tabler-Symbole + {material} Material-Symbole — auf ein Symbol klicken, um seine Klasse zu kopieren.', 'fr': "{tabler} icônes Tabler + {material} icônes Material — cliquez sur une icône pour copier sa classe."},

    # Design System view
    'design_system.title':     {'en': 'Design System', 'de': 'Designsystem', 'fr': "Design System"},
    'design_system.subtitle':  {'en': 'Every CSS component & utility token at a glance.', 'de': 'Alle CSS-Komponenten & Utility-Token auf einen Blick.', 'fr': "Tous les composants CSS et tokens d’utilité en un coup d’œil."},

    # Print Demo view
    'print_demo.title':     {'en': 'Print Demo', 'de': 'Druckdemo', 'fr': "Démo d’impression"},
    'print_demo.subtitle':  {'en': 'Live examples of every print_component mode — click any card to open the print dialog.', 'de': 'Live-Beispiele für jeden print_component-Modus — auf eine Karte klicken, um den Druckdialog zu öffnen.', 'fr': "Exemples en direct de chaque mode de print_component — cliquez sur une carte pour ouvrir le dialogue d’impression."},

    # App Settings stub view
    'appsettings.welcome':  {'en': 'Welcome to the Settings', 'de': 'Willkommen bei den Einstellungen', 'fr': "Bienvenue dans les paramètres"},
    'appsettings.label':    {'en': 'Settings', 'de': 'Einstellungen', 'fr': "Paramètres"},

    # Application settings: logging
    'appsettings.title':        {'en': 'App Settings', 'de': 'App-Einstellungen', 'fr': "Paramètres de l’application"},
    'appsettings.subtitle':     {'en': 'Configure application-wide behaviour.', 'de': 'Appweites Verhalten konfigurieren.', 'fr': "Configurez le comportement global de l’application."},
    'appsettings.logging':      {'en': 'Logging', 'de': 'Protokollierung', 'fr': "Journalisation"},
    'appsettings.logging_desc': {'en': 'Choose how much detail is written to the rolling log files.', 'de': 'Lege fest, wie detailliert in die rollierenden Protokolldateien geschrieben wird.', 'fr': "Choisissez le niveau de détail écrit dans les fichiers de log rotatifs."},
    'appsettings.log_level':    {'en': 'Log level', 'de': 'Protokollebene', 'fr': "Niveau de log"},
    'appsettings.log_file':     {'en': 'Log file', 'de': 'Protokolldatei', 'fr': "Fichier de log"},
    'appsettings.level_saved':  {'en': 'Log level set to {level}.', 'de': 'Protokollebene auf {level} gesetzt.', 'fr': "Niveau de log défini sur {level}."},
    'appsettings.admin_only':   {'en': 'Application settings are available to administrators only.', 'de': 'App-Einstellungen sind nur für Administratoren verfügbar.', 'fr': "Les paramètres de l’application sont réservés aux administrateurs."},
    'appsettings.logo':          {'en': 'Application logo', 'de': 'Anwendungslogo', 'fr': "Logo de l’application"},
    'appsettings.logo_desc':     {'en': 'Upload an SVG, PNG or JPG logo. It is stored in the database, shown in the header and on the login page, and the browser tab icon is regenerated automatically (ICO from raster formats, SVG as-is).', 'de': 'Lade ein Logo im SVG-, PNG- oder JPG-Format hoch. Es wird in der Datenbank gespeichert, in Kopfzeile und Login-Seite angezeigt, und das Browser-Tab-Symbol wird automatisch neu erzeugt (ICO aus Rasterformaten, SVG direkt).', 'fr': "Téléversez un logo SVG, PNG ou JPG. Il est stocké en base, affiché dans l’en-tête et sur la page de connexion, et l’icône d’onglet du navigateur est régénérée automatiquement (ICO depuis les formats raster, SVG tel quel)."},
    'appsettings.logo_reset_btn': {'en': 'Reset to default', 'de': 'Auf Standard zurücksetzen', 'fr': "Rétablir le logo par défaut"},
    'appsettings.logo_saved':     {'en': 'Logo updated.', 'de': 'Logo aktualisiert.', 'fr': "Logo mis à jour."},
    'appsettings.logo_reset':     {'en': 'Logo reset to the bundled default.', 'de': 'Logo auf das mitgelieferte Standardlogo zurückgesetzt.', 'fr': "Logo réinitialisé sur celui par défaut."},
    'appsettings.logo_too_large': {'en': 'Logo too large (max 2 MB).', 'de': 'Logo zu groß (max. 2 MB).', 'fr': "Logo trop volumineux (max 2 Mo)."},
    'appsettings.logo_bad_format': {'en': 'Unsupported format (SVG, PNG or JPG only).', 'de': 'Nicht unterstütztes Format (nur SVG, PNG oder JPG).', 'fr': "Format non pris en charge (SVG, PNG ou JPG uniquement)."},
    'appsettings.logo_save_failed': {'en': 'Could not save the logo.', 'de': 'Logo konnte nicht gespeichert werden.', 'fr': "Impossible d’enregistrer le logo."},
    'appsettings.tab.general':  {'en': 'General', 'de': 'Allgemein', 'fr': "Général"},
    'appsettings.tab.users':    {'en': 'Users & roles', 'de': 'Benutzer & Rollen', 'fr': "Utilisateurs & rôles"},
    'appsettings.tab.sessions': {'en': 'Sessions', 'de': 'Sitzungen', 'fr': "Sessions"},
    'appsettings.tab.audit':    {'en': 'Audit log', 'de': 'Audit-Protokoll', 'fr': "Journal d’audit"},
    'appsettings.tab.idps':      {'en': 'Providers', 'de': 'Anbieter', 'fr': "Fournisseurs"},
    'appsettings.tab.roles':     {'en': 'Roles', 'de': 'Rollen', 'fr': "Rôles"},

    # Audit log view
    'audit.title':        {'en': 'Audit Log', 'de': 'Audit-Protokoll', 'fr': "Journal d’audit"},
    'audit.subtitle':     {'en': 'A chronological record of who did what across the app.', 'de': 'Chronologische Aufzeichnung, wer was in der App getan hat.', 'fr': "Un relevé chronologique de qui a fait quoi dans l’application."},
    'audit.admin_only':   {'en': 'The audit log is available to administrators only.', 'de': 'Das Audit-Protokoll ist nur für Administratoren verfügbar.', 'fr': "Le journal d’audit est réservé aux administrateurs."},
    'audit.empty':        {'en': 'No activity recorded yet.', 'de': 'Noch keine Aktivität aufgezeichnet.', 'fr': "Aucune activité enregistrée pour l’instant."},
    'audit.showing':      {'en': 'Showing {shown} of {total} entries', 'de': 'Zeige {shown} von {total} Einträgen', 'fr': "{shown} entrées affichées sur {total}"},
    'audit.col.time':     {'en': 'Time (UTC)', 'de': 'Zeit (UTC)', 'fr': "Heure (UTC)"},
    'audit.col.user':     {'en': 'User', 'de': 'Benutzer', 'fr': "Utilisateur"},
    'audit.col.action':   {'en': 'Action', 'de': 'Aktion', 'fr': "Action"},
    'audit.col.details':  {'en': 'Details', 'de': 'Details', 'fr': "Détails"},
    'audit.col.ip':       {'en': 'IP', 'de': 'IP', 'fr': "IP"},
    'audit.filter.all':   {'en': 'All actions', 'de': 'Alle Aktionen', 'fr': "Toutes les actions"},
    'audit.filter.selected': {'en': '{n} action(s) selected', 'de': '{n} Aktion(en) ausgewählt', 'fr': "{n} action(s) sélectionnée(s)"},
    'audit.filter.category': {'en': 'Category', 'de': 'Kategorie', 'fr': "Catégorie"},
    'audit.filter.actions':  {'en': 'Actions', 'de': 'Aktionen', 'fr': "Actions"},
    'audit.filter.reset':    {'en': 'Reset filter', 'de': 'Filter zurücksetzen', 'fr': "Réinitialiser le filtre"},
    'audit.clear':        {'en': 'Clear log', 'de': 'Protokoll leeren', 'fr': "Vider le journal"},
    'audit.clear_title':  {'en': 'Clear audit log', 'de': 'Audit-Protokoll leeren', 'fr': "Vider le journal d’audit"},
    'audit.clear_confirm':{'en': 'This permanently deletes all audit entries. Continue?', 'de': 'Dadurch werden alle Audit-Einträge dauerhaft gelöscht. Fortfahren?', 'fr': "Cela supprime définitivement toutes les entrées d’audit. Continuer ?"},
    'audit.cleared':      {'en': 'Audit log cleared ({n} entries removed).', 'de': 'Audit-Protokoll geleert ({n} Einträge entfernt).', 'fr': "Journal d’audit vidé ({n} entrées supprimées)."},

    # Audit log action labels
    'audit.action.login':             {'en': 'Signed in', 'de': 'Angemeldet', 'fr': "Connexion"},
    'audit.action.login_failed':      {'en': 'Failed sign-in', 'de': 'Fehlgeschlagene Anmeldung', 'fr': "Échec de connexion"},
    'audit.action.logout':            {'en': 'Signed out', 'de': 'Abgemeldet', 'fr': "Déconnexion"},
    'audit.action.password_changed':  {'en': 'Changed password', 'de': 'Passwort geändert', 'fr': "Mot de passe changé"},
    'audit.action.password_reset':    {'en': 'Reset password', 'de': 'Passwort zurückgesetzt', 'fr': "Mot de passe réinitialisé"},
    'audit.action.user_created':      {'en': 'Created user', 'de': 'Benutzer erstellt', 'fr': "Utilisateur créé"},
    'audit.action.user_deleted':      {'en': 'Deleted user', 'de': 'Benutzer gelöscht', 'fr': "Utilisateur supprimé"},
    'audit.action.role_changed':      {'en': 'Changed role', 'de': 'Rolle geändert', 'fr': "Rôle changé"},
    'audit.action.user_activated':    {'en': 'Activated user', 'de': 'Benutzer aktiviert', 'fr': "Utilisateur activé"},
    'audit.action.user_deactivated':  {'en': 'Deactivated user', 'de': 'Benutzer deaktiviert', 'fr': "Utilisateur désactivé"},
    'audit.action.profile_updated':   {'en': 'Updated profile', 'de': 'Profil aktualisiert', 'fr': "Profil mis à jour"},
    'audit.action.language_changed':  {'en': 'Changed language', 'de': 'Sprache geändert', 'fr': "Langue changée"},
    'audit.action.session_revoked':   {'en': 'Revoked session', 'de': 'Sitzung widerrufen', 'fr': "Session révoquée"},
    'audit.action.job_submitted':     {'en': 'Submitted job', 'de': 'Job übermittelt', 'fr': "Job soumis"},
    'audit.action.job_cancelled':     {'en': 'Cancelled job', 'de': 'Job abgebrochen', 'fr': "Job annulé"},
    'audit.action.oidc_login':        {'en': 'Signed in (OIDC)', 'de': 'Angemeldet (OIDC)', 'fr': "Connexion (OIDC)"},
    'audit.action.idp_created':       {'en': 'Added provider', 'de': 'Anbieter hinzugefügt', 'fr': "Fournisseur ajouté"},
    'audit.action.idp_updated':       {'en': 'Updated provider', 'de': 'Anbieter aktualisiert', 'fr': "Fournisseur mis à jour"},
    'audit.action.idp_deleted':       {'en': 'Removed provider', 'de': 'Anbieter entfernt', 'fr': "Fournisseur supprimé"},
    'audit.action.theme_changed':     {'en': 'Changed theme', 'de': 'Design geändert', 'fr': "Thème changé"},

    # Audit filter groups
    'audit.group.sessions':     {'en': 'Sign-in / sessions', 'de': 'Anmeldung / Sitzungen', 'fr': "Connexion / sessions"},
    'audit.group.accounts':     {'en': 'Accounts & passwords', 'de': 'Konten & Passwörter', 'fr': "Comptes & mots de passe"},
    'audit.group.roles':        {'en': 'Roles', 'de': 'Rollen', 'fr': "Rôles"},
    'audit.group.preferences':  {'en': 'User preferences', 'de': 'Benutzereinstellungen', 'fr': "Préférences utilisateur"},
    'audit.group.idps':         {'en': 'Identity providers', 'de': 'Identitätsanbieter', 'fr': "Fournisseurs d'identité"},
    'audit.group.jobs':         {'en': 'Jobs', 'de': 'Jobs', 'fr': "Jobs"},

    # Header navigation (jobs / sessions / providers entries)
    'nav.jobs':           {'en': 'Jobs', 'de': 'Jobs', 'fr': "Jobs"},
    'nav.submit_job':     {'en': 'Submit job', 'de': 'Job übermitteln', 'fr': "Soumettre un job"},
    'nav.sessions':       {'en': 'Sessions', 'de': 'Sitzungen', 'fr': "Sessions"},
    'nav.providers':      {'en': 'Providers', 'de': 'Anbieter', 'fr': "Fournisseurs"},

    # Sessions page (admin)
    'sessions.title':         {'en': 'Connected sessions', 'de': 'Verbundene Sitzungen', 'fr': "Sessions connectées"},
    'sessions.subtitle':      {'en': 'Sessions grouped by user — web, OIDC and automation clients',
                               'de': 'Sitzungen nach Benutzer gruppiert — Web-, OIDC- und Automatisierungsclients',
                               'fr': "Sessions regroupées par utilisateur — clients web, OIDC et automatisation"},
    'sessions.admin_only':    {'en': 'Admin only', 'de': 'Nur für Administratoren', 'fr': "Administrateur uniquement"},
    'sessions.admin_only_desc': {'en': 'You need the admin role to view connected sessions.',
                                 'de': 'Du benötigst die Administrator-Rolle, um verbundene Sitzungen zu sehen.',
                                 'fr': "Vous devez avoir le rôle administrateur pour voir les sessions connectées."},
    'sessions.empty':         {'en': 'No connected client right now.', 'de': 'Derzeit kein verbundener Client.', 'fr': "Aucun client connecté actuellement."},
    'sessions.col.user':      {'en': 'User', 'de': 'Benutzer', 'fr': "Utilisateur"},
    'sessions.col.client':    {'en': 'Client', 'de': 'Client', 'fr': "Client"},
    'sessions.col.ip':        {'en': 'IP', 'de': 'IP', 'fr': "IP"},
    'sessions.col.last_activity': {'en': 'Last activity', 'de': 'Letzte Aktivität', 'fr': "Dernière activité"},
    'sessions.you':            {'en': 'you', 'de': 'du', 'fr': "vous"},
    'sessions.other_sessions': {'en': '+{n} other session(s)', 'de': '+{n} weitere Sitzung(en)', 'fr': "+{n} autre(s) session(s)"},
    'sessions.kick_title':    {'en': 'Kick session', 'de': 'Sitzung beenden', 'fr': "Déconnecter la session"},
    'sessions.kick_confirm':  {'en': 'Revoke session {sid}…?', 'de': 'Sitzung {sid}… widerrufen?', 'fr': "Révoquer la session {sid}… ?"},
    'sessions.revoked':       {'en': 'Session revoked', 'de': 'Sitzung widerrufen', 'fr': "Session révoquée"},
    'sessions.revoke':        {'en': 'Revoke this session', 'de': 'Diese Sitzung widerrufen', 'fr': "Révoquer cette session"},
    'sessions.not_possible':  {'en': 'Not possible', 'de': 'Nicht möglich', 'fr': "Impossible"},

    # Jobs board
    'jobs.title':        {'en': 'Jobs', 'de': 'Jobs', 'fr': "Jobs"},
    'jobs.subtitle':     {'en': 'Asynchronous jobs executed by the worker fleet',
                          'de': 'Asynchrone Jobs, ausgeführt durch die Worker-Flotte',
                          'fr': "Jobs asynchrones exécutés par la flotte de workers"},
    'jobs.total':        {'en': 'Total jobs', 'de': 'Jobs insgesamt', 'fr': "Jobs au total"},
    'jobs.last_n':       {'en': 'last 200 submissions', 'de': 'letzte 200 Übermittlungen', 'fr': "200 dernières soumissions"},
    'jobs.pct':          {'en': '{pct}% of jobs', 'de': '{pct}% der Jobs', 'fr': "{pct}% des jobs"},
    'jobs.col.queued':   {'en': 'Queued', 'de': 'Wartend', 'fr': "En file"},
    'jobs.col.queued_desc':    {'en': 'Waiting for a worker to claim it', 'de': 'Wartet auf einen freien Worker', 'fr': "En attente d’un worker"},
    'jobs.col.running':  {'en': 'Running', 'de': 'Läuft', 'fr': "En cours"},
    'jobs.col.running_desc':   {'en': 'Currently executed by a worker', 'de': 'Wird gerade von einem Worker ausgeführt', 'fr': "En cours d’exécution par un worker"},
    'jobs.col.succeeded': {'en': 'Succeeded', 'de': 'Erfolgreich', 'fr': "Réussi"},
    'jobs.col.succeeded_desc': {'en': 'Finished without error', 'de': 'Ohne Fehler abgeschlossen', 'fr': "Terminé sans erreur"},
    'jobs.col.failed':   {'en': 'Failed', 'de': 'Fehlgeschlagen', 'fr': "Échoué"},
    'jobs.col.failed_desc':    {'en': 'Terminated with an error', 'de': 'Mit einem Fehler beendet', 'fr': "Terminé avec une erreur"},
    'jobs.col.cancelled': {'en': 'Cancelled', 'de': 'Abgebrochen', 'fr': "Annulé"},
    'jobs.col.cancelled_desc': {'en': 'Aborted before completion', 'de': 'Vor Abschluss abgebrochen', 'fr': "Interrompu avant la fin"},
    'jobs.filtered_on':  {'en': 'Filtered on: {status}', 'de': 'Gefiltert nach: {status}', 'fr': "Filtre : {status}"},
    'jobs.clear_filter': {'en': 'Clear filter', 'de': 'Filter zurücksetzen', 'fr': "Effacer le filtre"},
    'jobs.empty':        {'en': 'No job submitted yet — use the "Submit job" button.',
                          'de': 'Noch kein Job übermittelt — nutze die Schaltfläche „Job übermitteln“.',
                          'fr': "Aucun job soumis pour l’instant — utilisez le bouton « Soumettre un job »."},
    'jobs.details':         {'en': 'Details', 'de': 'Details', 'fr': "Détails"},
    'jobs.priority_hint':   {'en': 'Priority: workers claim jobs from p5 (last) to p1 (first). This job runs at priority {p}.',
                             'de': 'Priorität: Worker holen Jobs von p5 (zuletzt) bis p1 (zuerst). Dieser Job läuft mit Priorität {p}.',
                             'fr': "Priorité : les workers récupèrent les jobs de p5 (dernier) à p1 (premier). Ce job s’exécute à la priorité {p}."},
    'jobs.type.demo_sleep':  {'en': 'Demo action: sleeps for the requested duration.',
                              'de': 'Demo-Aktion: schläft für die angegebene Dauer.',
                              'fr': "Action de démo : dort pendant la durée demandée."},
    'jobs.params.demo_sleep': {'en': "params: seconds — how long to sleep (default 5).",
                               'de': "params: seconds — Dauer in Sekunden (Standard 5).",
                               'fr': "params : seconds — durée d’attente en secondes (défaut 5)."},
    'jobs.type.cleanup_sessions': {'en': 'Maintenance: deletes ended login sessions older than the retention window.',
                                   'de': 'Wartung: löscht beendete Anmeldesitzungen, die älter als die Aufbewahrungsfrist sind.',
                                   'fr': "Maintenance : supprime les sessions terminées plus anciennes que la fenêtre de rétention."},
    'jobs.type_name.demo_sleep':  {'en': 'Demo sleep', 'de': 'Demo-Sleep', 'fr': "Démo sleep"},
    'jobs.type_name.cleanup_sessions': {'en': 'Session cleanup', 'de': 'Sitzungs-Bereinigung', 'fr': "Nettoyage des sessions"},
    'jobs.params.cleanup_sessions': {'en': "params: keep_days — delete sessions ended more than this many days ago (default 7).",
                                     'de': "params: keep_days — Sitzungen löschen, die vor mehr Tagen beendet wurden (Standard 7).",
                                     'fr': "params : keep_days — supprime les sessions terminées depuis plus de ce nombre de jours (défaut 7)."},
    'jobs.params_label':    {'en': 'Parameters', 'de': 'Parameter', 'fr': "Paramètres"},
    'jobs.result_label':    {'en': 'Result', 'de': 'Ergebnis', 'fr': "Résultat"},
    'jobs.error_label':     {'en': 'Error', 'de': 'Fehler', 'fr': "Erreur"},
    'jobs.schedules_title': {'en': 'Scheduled jobs', 'de': 'Geplante Jobs', 'fr': "Jobs planifiés"},
    'jobs.schedules_desc':  {'en': 'Recurring jobs submitted automatically by the scheduler.',
                             'de': 'Wiederkehrende Jobs, die vom Scheduler automatisch eingereicht werden.',
                             'fr': "Jobs récurrents soumis automatiquement par le planificateur."},
    'jobs.enabled':         {'en': 'Enabled', 'de': 'Aktiviert', 'fr': "Activé"},
    'jobs.disabled':        {'en': 'Disabled', 'de': 'Deaktiviert', 'fr': "Désactivé"},
    'jobs.run_now':         {'en': 'Run now', 'de': 'Jetzt ausführen', 'fr': "Exécuter maintenant"},
    'jobs.run_now_msg':     {'en': "Job '{type}' submitted.", 'de': "Job '{type}' eingereicht.", 'fr': "Job « {type} » soumis."},
    'jobs.edit_schedule':   {'en': 'Edit schedule #{id}', 'de': 'Zeitplan #{id} bearbeiten', 'fr': "Modifier le plan #{id}"},
    'jobs.cron_label':      {'en': 'CRON expression', 'de': 'CRON-Ausdruck', 'fr': "Expression CRON"},
    'jobs.cron_hint':       {'en': 'Minute Hour Day Month Weekday — e.g. "0 3 * * *" = daily at 03:00.',
                             'de': 'Minute Stunde Tag Monat Wochentag — z. B. "0 3 * * *" = täglich um 03:00 Uhr.',
                             'fr': "Minute Heure Jour Mois Jour de semaine — ex. « 0 3 * * * » = tous les jours à 03h00."},
    'jobs.invalid_json':    {'en': 'Parameters must be valid JSON.', 'de': 'Parameter müssen gültiges JSON sein.', 'fr': "Les paramètres doivent être du JSON valide."},
    'jobs.schedule_saved':  {'en': 'Schedule saved.', 'de': 'Zeitplan gespeichert.', 'fr': "Plan enregistré."},
    'jobs.schedule_deleted': {'en': 'Schedule deleted.', 'de': 'Zeitplan gelöscht.', 'fr': "Plan supprimé."},
    'jobs.delete_schedule_confirm': {'en': 'Delete schedule #{id}? Its jobs will no longer be submitted automatically.',
                                     'de': 'Zeitplan #{id} löschen? Dessen Jobs werden nicht mehr automatisch eingereicht.',
                                     'fr': "Supprimer le plan #{id} ? Ses jobs ne seront plus soumis automatiquement."},
    'jobs.delete_schedule_title': {'en': 'Delete schedule', 'de': 'Zeitplan löschen', 'fr': "Supprimer le plan"},
    'jobs.tip.enable':      {'en': 'Enable schedule', 'de': 'Zeitplan aktivieren', 'fr': "Activer le plan"},
    'jobs.tip.disable':     {'en': 'Disable schedule', 'de': 'Zeitplan deaktivieren', 'fr': "Désactiver le plan"},
    'jobs.tip.edit':        {'en': 'Edit schedule', 'de': 'Zeitplan bearbeiten', 'fr': "Modifier le plan"},
    'jobs.tip.delete':      {'en': 'Delete schedule', 'de': 'Zeitplan löschen', 'fr': "Supprimer le plan"},
    'jobs.submit_new':   {'en': 'Submit a new job', 'de': 'Neuen Job übermitteln', 'fr': "Soumettre un nouveau job"},
    'jobs.cancel':       {'en': 'Cancel', 'de': 'Abbrechen', 'fr': "Annuler"},
    'jobs.cancel_title': {'en': 'Cancel job', 'de': 'Job abbrechen', 'fr': "Annuler le job"},
    'jobs.cancel_confirm': {'en': 'Cancel job #{id}?', 'de': 'Job #{id} abbrechen?', 'fr': "Annuler le job #{id} ?"},
    'jobs.cancelled_msg': {'en': 'Job #{id} cancelled', 'de': 'Job #{id} abgebrochen', 'fr': "Job #{id} annulé"},
    'jobs.not_possible': {'en': 'Not possible', 'de': 'Nicht möglich', 'fr': "Impossible"},

    # Job submission page
    'jobsubmit.title':        {'en': 'Submit a job', 'de': 'Job übermitteln', 'fr': "Soumettre un job"},
    'jobsubmit.subtitle':     {'en': 'Queue an action for asynchronous execution by the workers',
                               'de': 'Eine Aktion zur asynchronen Ausführung durch die Worker einreihen',
                               'fr': "Mettre une action en file pour exécution asynchrone par les workers"},
    'jobsubmit.definition':   {'en': 'Job definition', 'de': 'Job-Definition', 'fr': "Définition du job"},
    'jobsubmit.job_type':     {'en': 'Job type', 'de': 'Job-Typ', 'fr': "Type de job"},
    'jobsubmit.params':       {'en': 'Parameters (JSON)', 'de': 'Parameter (JSON)', 'fr': "Paramètres (JSON)"},
    'jobsubmit.priority':     {'en': 'Priority (0 = first)', 'de': 'Priorität (0 = zuerst)', 'fr': "Priorité (0 = premier)"},
    'jobsubmit.priority_hint': {'en': 'Lower value = claimed first by the workers',
                                'de': 'Niedrigerer Wert = wird zuerst von den Workern übernommen',
                                'fr': "Valeur plus basse = récupéré en premier par les workers"},
    'jobsubmit.submit':       {'en': 'Submit job', 'de': 'Job übermitteln', 'fr': "Soumettre"},
    'jobsubmit.invalid_params': {'en': 'Invalid parameters: {err}', 'de': 'Ungültige Parameter: {err}', 'fr': "Paramètres invalides : {err}"},
    'jobsubmit.queued_msg':  {'en': 'Job #{id} queued ({status})', 'de': 'Job #{id} eingereiht ({status})', 'fr': "Job #{id} mis en file ({status})"},
    'jobsubmit.last_submission': {'en': 'Last submission', 'de': 'Letzte Übermittlung', 'fr': "Dernière soumission"},
    'jobsubmit.none_yet':    {'en': 'No job submitted from this page yet.',
                              'de': 'Von dieser Seite wurde noch kein Job übermittelt.',
                              'fr': "Aucun job soumis pour l’instant."},
    'jobsubmit.queued_state': {'en': 'Job #{id} is queued.', 'de': 'Job #{id} ist eingereiht.', 'fr': "Le job #{id} est en file."},
    'jobsubmit.follow':      {'en': 'Follow it in the job list', 'de': 'In der Job-Liste verfolgen', 'fr': "Le suivre dans la liste des jobs"},

    # Login page
    'login.title':      {'en': 'Infrastructure Login', 'de': 'Infrastruktur-Anmeldung', 'fr': "Connexion Infrastructure"},
    'login.username':    {'en': 'Username', 'de': 'Benutzername', 'fr': "Nom d’utilisateur"},
    'login.password':    {'en': 'Password', 'de': 'Passwort', 'fr': "Mot de passe"},
    'login.sign_in':     {'en': 'Sign in', 'de': 'Anmelden', 'fr': "Se connecter"},
    'login.or_sign_in_with': {'en': 'or sign in with', 'de': 'oder anmelden mit', 'fr': "ou se connecter avec"},
    'login.msg_timeout': {'en': 'Your session expired due to inactivity. Please log in again.',
                          'de': 'Deine Sitzung ist wegen Inaktivität abgelaufen. Bitte melde dich erneut an.',
                          'fr': "Votre session a expiré pour cause d’inactivité. Veuillez vous reconnecter."},
    'login.msg_revoked': {'en': 'You were logged out from another tab or session. Please log in again.',
                          'de': 'Du wurdest in einem anderen Tab oder einer anderen Sitzung abgemeldet. Bitte melde dich erneut an.',
                          'fr': "Vous avez été déconnecté depuis un autre onglet ou une autre session. Veuillez vous reconnecter."},
    'login.msg_expired': {'en': 'Your session has expired. Please log in again.',
                          'de': 'Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.',
                          'fr': "Votre session a expiré. Veuillez vous reconnecter."},

    # Identity providers page (admin)
    'idps.title':        {'en': 'Identity providers', 'de': 'Identitätsanbieter', 'fr': "Fournisseurs d’identité"},
    'idps.subtitle':     {'en': 'OIDC sources for external sign-in (e.g. Keycloak realms)',
                          'de': 'OIDC-Quellen für die externe Anmeldung (z. B. Keycloak-Realms)',
                          'fr': "Sources OIDC pour la connexion externe (ex. realms Keycloak)"},
    'idps.admin_only':   {'en': 'Admin only', 'de': 'Nur für Administratoren', 'fr': "Administrateur uniquement"},
    'idps.admin_only_desc': {'en': 'You need the admin role to manage identity providers.',
                              'de': 'Du benötigst die Administrator-Rolle, um Identitätsanbieter zu verwalten.',
                              'fr': "Vous devez avoir le rôle administrateur pour gérer les fournisseurs d’identité."},
    'idps.empty':        {'en': 'No identity provider configured yet — only local users can log in.',
                          'de': 'Noch kein Identitätsanbieter konfiguriert — nur lokale Benutzer können sich anmelden.',
                          'fr': "Aucun fournisseur d’identité configuré — seuls les utilisateurs locaux peuvent se connecter."},
    'idps.col.name':     {'en': 'Name', 'de': 'Name', 'fr': "Nom"},
    'idps.col.issuer':   {'en': 'Issuer', 'de': 'Aussteller', 'fr': "Émetteur"},
    'idps.col.client_id': {'en': 'Client ID', 'de': 'Client-ID', 'fr': "Client ID"},
    'idps.col.role':     {'en': 'Default role', 'de': 'Standardrolle', 'fr': "Rôle par défaut"},
    'idps.col.options':  {'en': 'Options', 'de': 'Optionen', 'fr': "Options"},
    'idps.add_title':    {'en': 'Add an identity provider', 'de': 'Identitätsanbieter hinzufügen', 'fr': "Ajouter un fournisseur d’identité"},
    'idps.add_desc':     {'en': 'Declare an external OIDC source (e.g. a Keycloak realm). Its users will be able to sign in with their provider credentials.',
                          'de': 'Deklariere eine externe OIDC-Quelle (z. B. einen Keycloak-Realm). Dessen Benutzer können sich mit ihren Anbieter-Zugangsdaten anmelden.',
                          'fr': "Déclarez une source OIDC externe (ex. un realm Keycloak). Ses utilisateurs pourront se connecter avec leurs identifiants du fournisseur."},
    'idps.f_name':       {'en': 'Name — label shown on the login page button', 'de': 'Name — Beschriftung der Anmelde-Schaltfläche', 'fr': "Nom — libellé affiché sur le bouton de la page de connexion"},
    'idps.f_issuer':     {'en': 'Issuer URL — base URL of the realm on the identity provider (no /.well-known suffix)',
                          'de': 'Aussteller-URL — Basis-URL des Realms beim Identitätsanbieter (ohne /.well-known-Suffix)',
                          'fr': "URL de l’émetteur — URL de base du realm sur le fournisseur d’identité (sans suffixe /.well-known)"},
    'idps.f_client_id':  {'en': 'Client ID — confidential client declared on the IdP', 'de': 'Client-ID — der auf dem IdP deklarierte vertrauliche Client', 'fr': "Client ID — client confidentiel déclaré sur l’IdP"},
    'idps.f_secret':     {'en': 'Client secret — Credentials tab of the client', 'de': 'Client-Geheimnis — Tab „Credentials“ des Clients', 'fr': "Secret client — onglet Credentials du client"},
    'idps.f_secret_keep': {'en': 'Client secret — leave empty to keep the current one',
                           'de': 'Client-Geheimnis — leer lassen, um das aktuelle zu behalten',
                           'fr': "Secret client — laisser vide pour conserver l’actuel"},
    'idps.f_role':       {'en': 'Default role — role given to users auto-provisioned at first login',
                          'de': 'Standardrolle — Rolle für beim ersten Login automatisch erstellte Benutzer',
                          'fr': "Rôle par défaut — rôle attribué aux utilisateurs créés automatiquement à la première connexion"},
    'idps.tip':          {'en': 'Tip: declare the redirect URI on the client: ', 'de': 'Tipp: deklariere die Weiterleitungs-URI beim Client: ', 'fr': "Astuce : déclarez l’URI de redirection sur le client : "},
    'idps.enable':       {'en': 'Enabled', 'de': 'Aktiviert', 'fr': "Activé"},
    'idps.disabled':     {'en': 'Disabled', 'de': 'Deaktiviert', 'fr': "Désactivé"},
    'idps.edit':         {'en': 'Edit', 'de': 'Bearbeiten', 'fr': "Modifier"},
    'idps.delete':       {'en': 'Delete', 'de': 'Löschen', 'fr': "Supprimer"},
    'idps.save':         {'en': 'Save provider', 'de': 'Anbieter speichern', 'fr': "Enregistrer le fournisseur"},
    'idps.add':          {'en': 'Add provider', 'de': 'Anbieter hinzufügen', 'fr': "Ajouter un fournisseur"},
    'idps.cancel':       {'en': 'Cancel', 'de': 'Abbrechen', 'fr': "Annuler"},
    'idps.edit_title':   {'en': 'Edit provider', 'de': 'Anbieter bearbeiten', 'fr': "Modifier le fournisseur"},
    'idps.delete_title':  {'en': 'Delete provider', 'de': 'Anbieter löschen', 'fr': "Supprimer le fournisseur"},
    'idps.delete_confirm': {'en': 'Remove provider {name}? Users will no longer be able to sign in with it.',
                            'de': 'Anbieter {name} entfernen? Benutzer können sich dann nicht mehr darüber anmelden.',
                            'fr': "Supprimer le fournisseur {name} ? Ses utilisateurs ne pourront plus s’y connecter."},
    'idps.jit':          {'en': 'Auto-create users on first login (JIT provisioning)',
                           'de': 'Benutzer beim ersten Login automatisch erstellen (JIT-Provisionierung)',
                           'fr': "Créer automatiquement les utilisateurs à la première connexion (provisioning JIT)"},
    'idps.required':     {'en': 'Name, issuer URL, client ID and secret are all required.',
                          'de': 'Name, Aussteller-URL, Client-ID und Client-Geheimnis sind alle erforderlich.',
                          'fr': "Nom, URL de l’émetteur, client ID et secret sont tous obligatoires."},
    'idps.verify_fail':  {'en': 'Verification failed', 'de': 'Verifizierung fehlgeschlagen', 'fr': "Échec de la vérification"},
    'idps.verify_ok':    {'en': 'Discovery OK.\ntoken_endpoint: {ep}', 'de': 'Discovery OK.\ntoken_endpoint: {ep}', 'fr': "Discovery OK.\ntoken_endpoint : {ep}"},
    'idps.reachable':    {'en': "Provider '{name}' reachable", 'de': "Anbieter '{name}' erreichbar", 'fr': "Fournisseur « {name} » accessible"},
    'idps.not_possible': {'en': 'Not possible', 'de': 'Nicht möglich', 'fr': "Impossible"},
    'idps.tip.enable':   {'en': 'Enable provider', 'de': 'Anbieter aktivieren', 'fr': "Activer le fournisseur"},
    'idps.tip.disable':   {'en': 'Disable provider', 'de': 'Anbieter deaktivieren', 'fr': "Désactiver le fournisseur"},
    'idps.tip.verify':    {'en': 'Verify connection', 'de': 'Verbindung prüfen', 'fr': "Vérifier la connexion"},
    'idps.tip.edit':      {'en': 'Edit provider', 'de': 'Anbieter bearbeiten', 'fr': "Modifier le fournisseur"},
    'idps.tip.delete':    {'en': 'Delete provider', 'de': 'Anbieter löschen', 'fr': "Supprimer le fournisseur"},
    'idps.verifying':     {'en': "Checking provider '{name}'…", 'de': "Anbieter '{name}' wird geprüft…", 'fr': "Vérification du fournisseur « {name} »…"},
    'idps.toggle_msg':    {'en': "Provider '{name}' {state}", 'de': "Anbieter '{name}' {state}", 'fr': "Fournisseur « {name} » {state}"},
    'idps.deleted_msg':   {'en': "Provider '{name}' removed.", 'de': "Anbieter '{name}' entfernt.", 'fr': "Fournisseur « {name} » supprimé."},
    'idps.created_msg':   {'en': "Provider '{name}' created.", 'de': "Anbieter '{name}' erstellt.", 'fr': "Fournisseur « {name} » créé."},
    'idps.saved':        {'en': 'Provider saved.', 'de': 'Anbieter gespeichert.', 'fr': "Fournisseur enregistré."},
    'idps.deleted':       {'en': 'Provider removed.', 'de': 'Anbieter entfernt.', 'fr': "Fournisseur supprimé."},

    # Change-password page
    'changepw.title':   {'en': 'Set a new password', 'de': 'Neues Passwort festlegen', 'fr': "Définir un nouveau mot de passe"},
    'changepw.desc':    {'en': 'You must choose a new password before continuing.',
                         'de': 'Du musst ein neues Passwort festlegen, bevor du fortfährst.',
                         'fr': "Vous devez choisir un nouveau mot de passe avant de continuer."},
    'changepw.save':    {'en': 'Save password', 'de': 'Passwort speichern',
                         'fr': 'Enregistrer le mot de passe'},

    # Common actions & words
    'common.export':      {'en': 'Export', 'de': 'Exportieren', 'fr': "Exporter"},
    'common.refresh':     {'en': 'Refresh', 'de': 'Aktualisieren', 'fr': "Actualiser"},
    'common.view_all':    {'en': 'View all', 'de': 'Alle anzeigen', 'fr': "Tout voir"},
    'common.cancel':      {'en': 'Cancel', 'de': 'Abbrechen', 'fr': "Annuler"},
    'common.create':      {'en': 'Create', 'de': 'Erstellen', 'fr': "Créer"},
    'common.delete':      {'en': 'Delete', 'de': 'Löschen', 'fr': "Supprimer"},
    'common.move':        {'en': 'Move', 'de': 'Verschieben', 'fr': "Déplacer"},
    'common.inspect':     {'en': 'Inspect', 'de': 'Prüfen', 'fr': "Inspecter"},
    'common.customer':    {'en': 'Customer', 'de': 'Kunde', 'fr': "Client"},
    'common.product':     {'en': 'Product', 'de': 'Produkt', 'fr': "Produit"},
    'common.status':      {'en': 'Status', 'de': 'Status', 'fr': "Statut"},
    'common.date':        {'en': 'Date', 'de': 'Datum', 'fr': "Date"},
    'common.total':       {'en': 'Total', 'de': 'Gesamt', 'fr': "Total"},

    # Shared status labels
    'status.pending':     {'en': 'Pending', 'de': 'Ausstehend', 'fr': "En attente"},
    'status.in_transit':  {'en': 'In Transit', 'de': 'Unterwegs', 'fr': "En transit"},
    'status.delivered':   {'en': 'Delivered', 'de': 'Zugestellt', 'fr': "Livré"},
    'status.cancelled':   {'en': 'Cancelled', 'de': 'Storniert', 'fr': "Annulé"},
    'status.running':     {'en': 'Running', 'de': 'Läuft', 'fr': "En cours"},
    'status.paused':      {'en': 'Paused', 'de': 'Pausiert', 'fr': "En pause"},
    'status.error':       {'en': 'Error', 'de': 'Fehler', 'fr': "Erreur"},
    'status.open':        {'en': 'Open', 'de': 'Offen', 'fr': "Ouvert"},
    'status.processing':  {'en': 'Processing', 'de': 'In Bearbeitung', 'fr': "En traitement"},
    'status.fulfilled':   {'en': 'Fulfilled', 'de': 'Erfüllt', 'fr': "Réalisé"},
    'status.on_hold':     {'en': 'On Hold', 'de': 'Wartend', 'fr': "En suspens"},
    'status.available':   {'en': 'Available', 'de': 'Verfügbar', 'fr': "Disponible"},
    'status.in_use':      {'en': 'In Use', 'de': 'In Benutzung', 'fr': "En utilisation"},
    'status.damaged':     {'en': 'Damaged', 'de': 'Beschädigt', 'fr': "Endommagé"},
    'status.active':      {'en': 'Active', 'de': 'Aktiv', 'fr': "Actif"},
    'status.inactive':    {'en': 'Inactive', 'de': 'Inaktiv', 'fr': "Inactif"},

    # Dashboard extras
    'dashboard.last_30_days':  {'en': 'Last 30 days', 'de': 'Letzte 30 Tage', 'fr': "30 derniers jours"},
    'dashboard.this_month':    {'en': 'This month', 'de': 'Diesen Monat', 'fr': "Ce mois-ci"},
    'dashboard.last_7_days':   {'en': 'Last 7 days', 'de': 'Letzte 7 Tage', 'fr': "7 derniers jours"},
    'dashboard.last_24h':      {'en': 'Last 24 h', 'de': 'Letzte 24 Std.', 'fr': "Dernières 24 h"},
    'dashboard.refreshed':     {'en': 'Dashboard refreshed', 'de': 'Dashboard aktualisiert', 'fr': "Tableau de bord actualisé"},
    'dashboard.vs_yesterday':  {'en': 'vs yesterday', 'de': 'ggü. gestern', 'fr': "par rapport à hier"},
    'dashboard.series.revenue':   {'en': 'Revenue', 'de': 'Umsatz', 'fr': "Revenus"},
    'dashboard.series.forecast':  {'en': 'Forecast', 'de': 'Prognose', 'fr': "Prévision"},
    'dashboard.series.completed': {'en': 'Completed', 'de': 'Abgeschlossen', 'fr': "Terminés"},
    'dashboard.series.returned':  {'en': 'Returned', 'de': 'Retouren', 'fr': "Retournés"},
    'dashboard.series.actual':    {'en': 'Actual', 'de': 'Ist', 'fr': "Réel"},
    'dashboard.series.target':    {'en': 'Target', 'de': 'Ziel', 'fr': "Objectif"},

    # Shipping view details
    'shipping.kpi.shipments':  {'en': 'Shipments', 'de': 'Sendungen', 'fr': "Expéditions"},
    'shipping.sub.this_week':  {'en': 'this week', 'de': 'diese Woche', 'fr': "cette semaine"},
    'shipping.sub.active':     {'en': 'currently active', 'de': 'aktuell aktiv', 'fr': "actuellement actives"},
    'shipping.sub.completed':  {'en': 'completed', 'de': 'abgeschlossen', 'fr': "terminées"},
    'shipping.sub.awaiting':   {'en': 'awaiting pickup', 'de': 'wartet auf Abholung', 'fr': "en attente d’enlèvement"},
    'shipping.search':         {'en': 'Search shipments…', 'de': 'Sendungen suchen…', 'fr': "Rechercher des expéditions…"},
    'shipping.col.id':         {'en': 'Shipment ID', 'de': 'Sendungs-ID', 'fr': "ID d’expédition"},
    'shipping.col.destination':{'en': 'Destination', 'de': 'Ziel', 'fr': "Destination"},
    'shipping.col.carrier':    {'en': 'Carrier', 'de': 'Frachtführer', 'fr': "Transporteur"},
    'shipping.col.eta':        {'en': 'ETA', 'de': 'Voraussichtlich', 'fr': "ETA"},
    'shipping.col.weight':     {'en': 'Weight (kg)', 'de': 'Gewicht (kg)', 'fr': "Poids (kg)"},
    'shipping.export_started': {'en': 'Export started', 'de': 'Export gestartet', 'fr': "Export démarré"},
    'shipping.added_title':    {'en': 'Shipment added', 'de': 'Sendung hinzugefügt', 'fr': "Expédition ajoutée"},

    # Production view details
    'production.kpi.active_lines': {'en': 'Active Lines', 'de': 'Aktive Linien', 'fr': "Lignes actives"},
    'production.kpi.units_today':  {'en': 'Units Today', 'de': 'Einheiten heute', 'fr': "Unités aujourd’hui"},
    'production.kpi.efficiency':   {'en': 'Efficiency', 'de': 'Effizienz', 'fr': "Efficacité"},
    'production.kpi.shifts':       {'en': 'Shifts', 'de': 'Schichten', 'fr': "Équipes"},
    'production.kpi.alerts':       {'en': 'Alerts', 'de': 'Warnungen', 'fr': "Alertes"},
    'production.sub.running':      {'en': 'currently running', 'de': 'aktuell aktiv', 'fr': "en cours"},
    'production.sub.of_target':    {'en': 'of {n} target', 'de': 'von {n} Ziel', 'fr': "sur {n} cible"},
    'production.sub.vs_target':    {'en': 'vs daily target', 'de': 'ggü. Tagesziel', 'fr': "par rapport à l’objectif quotidien"},
    'production.sub.shifts':       {'en': 'Morning / Afternoon / Night', 'de': 'Früh / Spät / Nacht', 'fr': "Matin / Après-midi / Nuit"},
    'production.sub.errors':       {'en': 'lines in error state', 'de': 'Linien im Fehlerzustand', 'fr': "lignes en erreur"},
    'production.line_status':      {'en': 'Line Status', 'de': 'Linienstatus', 'fr': "État des lignes"},
    'production.lines_count':      {'en': '{n} production lines', 'de': '{n} Produktionslinien', 'fr': "{n} lignes de production"},
    'production.col.line':         {'en': 'Line', 'de': 'Linie', 'fr': "Ligne"},
    'production.col.shift':        {'en': 'Shift', 'de': 'Schicht', 'fr': "Équipe"},
    'production.col.progress':     {'en': 'Progress', 'de': 'Fortschritt', 'fr': "Progression"},
    'production.col.actual_target':{'en': 'Actual / Target', 'de': 'Ist / Ziel', 'fr': "Réel / Objectif"},
    'production.throughput_today': {'en': 'Throughput Today', 'de': 'Durchsatz heute', 'fr': "Débit aujourd’hui"},
    'production.units_per_hour':   {'en': 'Units per hour — running lines only', 'de': 'Einheiten pro Stunde — nur laufende Linien', 'fr': "Unités par heure — lignes en cours uniquement"},
    'production.refreshed':        {'en': 'Line data refreshed', 'de': 'Liniendaten aktualisiert', 'fr': "Données des lignes actualisées"},
    'production.wo_soon':          {'en': 'Work order form coming soon', 'de': 'Arbeitsauftragsformular folgt bald', 'fr': "Formulaire d’ordre de fabrication bientôt disponible"},
    'production.shift.morning':    {'en': 'Morning', 'de': 'Früh', 'fr': "Matin"},
    'production.shift.afternoon':  {'en': 'Afternoon', 'de': 'Spät', 'fr': "Après-midi"},
    'production.shift.night':      {'en': 'Night', 'de': 'Nacht', 'fr': "Nuit"},

    # Orders view details
    'orders.kpi.total':       {'en': 'Total Orders', 'de': 'Aufträge gesamt', 'fr': "Commandes totales"},
    'orders.kpi.revenue':     {'en': 'Revenue', 'de': 'Umsatz', 'fr': "Revenus"},
    'orders.kpi.fulfilled':   {'en': 'Fulfilled', 'de': 'Erfüllt', 'fr': "Réalisées"},
    'orders.kpi.processing':  {'en': 'Processing', 'de': 'In Bearbeitung', 'fr': "En traitement"},
    'orders.kpi.cancelled':   {'en': 'Cancelled', 'de': 'Storniert', 'fr': "Annulées"},
    'orders.sub.this_week':   {'en': 'this week', 'de': 'diese Woche', 'fr': "cette semaine"},
    'orders.sub.completed':   {'en': 'completed', 'de': 'abgeschlossen', 'fr': "terminées"},
    'orders.sub.in_progress': {'en': 'in progress', 'de': 'in Bearbeitung', 'fr': "en cours"},
    'orders.status_breakdown':{'en': 'Status Breakdown', 'de': 'Statusaufteilung', 'fr': "Répartition par statut"},
    'orders.orders_revenue':  {'en': 'Orders & Revenue — This Week', 'de': 'Aufträge & Umsatz — Diese Woche', 'fr': "Commandes & revenus — cette semaine"},
    'orders.recent':          {'en': 'Recent Orders', 'de': 'Letzte Aufträge', 'fr': "Commandes récentes"},
    'orders.shown':           {'en': '{n} orders shown', 'de': '{n} Aufträge angezeigt', 'fr': "{n} commandes affichées"},
    'orders.loading_all':     {'en': 'Loading full order list…', 'de': 'Vollständige Auftragsliste wird geladen…', 'fr': "Chargement de la liste complète des commandes…"},
    'orders.col.id':          {'en': 'Order ID', 'de': 'Auftrags-ID', 'fr': "ID de commande"},
    'orders.col.qty':         {'en': 'Qty', 'de': 'Menge', 'fr': "Qté"},
    'orders.legend.orders':   {'en': 'Orders', 'de': 'Aufträge', 'fr': "Commandes"},
    'orders.legend.revenue':  {'en': 'Revenue', 'de': 'Umsatz', 'fr': "Revenus"},
    'orders.new_order':       {'en': 'New Order', 'de': 'Neuer Auftrag', 'fr': "Nouvelle commande"},
    'orders.priority':        {'en': 'Priority', 'de': 'Priorität', 'fr': "Priorité"},
    'orders.quantity':        {'en': 'Quantity', 'de': 'Menge', 'fr': "Quantité"},
    'orders.create_order':    {'en': 'Create Order', 'de': 'Auftrag erstellen', 'fr': "Créer la commande"},
    'orders.created':         {'en': 'Order created successfully', 'de': 'Auftrag erfolgreich erstellt', 'fr': "Commande créée avec succès"},
    'orders.created_title':   {'en': 'Order Created', 'de': 'Auftrag erstellt', 'fr': "Commande créée"},
    'orders.priority.normal': {'en': 'Normal', 'de': 'Normal', 'fr': "Normale"},
    'orders.priority.high':   {'en': 'High', 'de': 'Hoch', 'fr': "Haute"},
    'orders.priority.urgent': {'en': 'Urgent', 'de': 'Dringend', 'fr': "Urgente"},

    # Pallets view details
    'pallets.kpi.total':       {'en': 'Total', 'de': 'Gesamt', 'fr': "Total"},
    'pallets.kpi.available':   {'en': 'Available', 'de': 'Verfügbar', 'fr': "Disponibles"},
    'pallets.kpi.in_use':      {'en': 'In Use', 'de': 'In Benutzung', 'fr': "En utilisation"},
    'pallets.kpi.in_transit':  {'en': 'In Transit', 'de': 'Unterwegs', 'fr': "En transit"},
    'pallets.kpi.damaged':     {'en': 'Damaged', 'de': 'Beschädigt', 'fr': "Endommagées"},
    'pallets.kpi.utilisation': {'en': 'Utilisation', 'de': 'Auslastung', 'fr': "Utilisation"},
    'pallets.sub.registered':  {'en': 'registered', 'de': 'registriert', 'fr': "enregistrées"},
    'pallets.sub.ready':       {'en': 'ready to use', 'de': 'einsatzbereit', 'fr': "prêtes à l’emploi"},
    'pallets.sub.loaded':      {'en': 'currently loaded', 'de': 'aktuell beladen', 'fr': "actuellement chargées"},
    'pallets.sub.moving':      {'en': 'on the move', 'de': 'unterwegs', 'fr': "en mouvement"},
    'pallets.sub.inspection':  {'en': 'needs inspection', 'de': 'muss geprüft werden', 'fr': "à inspecter"},
    'pallets.sub.fleet':       {'en': 'fleet avg load', 'de': 'ø Flottenauslastung', 'fr': "charge moyenne de la flotte"},
    'pallets.inventory':       {'en': 'Pallet Inventory', 'de': 'Palettenbestand', 'fr': "Inventaire des palettes"},
    'pallets.registered_count':{'en': '{n} pallets registered', 'de': '{n} Paletten registriert', 'fr': "{n} palettes enregistrées"},
    'pallets.load_capacity':   {'en': 'Load capacity', 'de': 'Ladekapazität', 'fr': "Capacité de charge"},
    'pallets.by_location':     {'en': 'By Location', 'de': 'Nach Standort', 'fr': "Par emplacement"},
    'pallets.locations_count': {'en': '{n} locations', 'de': '{n} Standorte', 'fr': "{n} emplacements"},
    'pallets.col.location':    {'en': 'Location', 'de': 'Standort', 'fr': "Emplacement"},
    'pallets.col.pallets':     {'en': 'Pallets', 'de': 'Paletten', 'fr': "Palettes"},
    'pallets.col.total_load':  {'en': 'Total Load', 'de': 'Gesamtlast', 'fr': "Charge totale"},
    'pallets.col.utilisation': {'en': 'Utilisation', 'de': 'Auslastung', 'fr': "Utilisation"},
    'pallets.move_scheduled':  {'en': '{id} move scheduled', 'de': '{id} Verschiebung geplant', 'fr': "{id} déplacement planifié"},
    'pallets.inspect_queued':  {'en': '{id} inspection queued', 'de': '{id} Prüfung eingereiht', 'fr': "{id} inspection en file"},
    'pallets.reg_soon':        {'en': 'Registration form coming soon', 'de': 'Registrierungsformular folgt bald', 'fr': "Formulaire d’enregistrement bientôt disponible"},

    # Packings view details
    'packing.total_jobs':    {'en': 'TOTAL JOBS', 'de': 'AUFTRÄGE GESAMT', 'fr': "TOTAL DES TÂCHES"},
    'packing.units_to_pack': {'en': '{n} units to pack', 'de': '{n} Einheiten zu verpacken', 'fr': "{n} unités à conditionner"},
    'packing.col.pending':     {'en': 'Pending', 'de': 'Ausstehend', 'fr': "En attente"},
    'packing.col.in_progress': {'en': 'In Progress', 'de': 'In Bearbeitung', 'fr': "En cours"},
    'packing.col.packed':      {'en': 'Packed', 'de': 'Verpackt', 'fr': "Conditionnées"},
    'packing.pct_of_jobs':   {'en': '{n} % of jobs', 'de': '{n} % der Aufträge', 'fr': "{n} % des tâches"},
    'packing.due':           {'en': 'Due {date}', 'de': 'Fällig {date}', 'fr': "Échéance {date}"},
    'packing.units':         {'en': '{n} units', 'de': '{n} Einheiten', 'fr': "{n} unités"},
    'packing.action.start':       {'en': 'Start', 'de': 'Starten', 'fr': "Démarrer"},
    'packing.action.mark_packed': {'en': 'Mark Packed', 'de': 'Als verpackt markieren', 'fr': "Marquer conditionnée"},
    'packing.action.dispatch':    {'en': 'Dispatch', 'de': 'Versenden', 'fr': "Expédier"},
    'packing.status.started':     {'en': 'Started', 'de': 'Gestartet', 'fr': "Démarrée"},
    'packing.status.packed':      {'en': 'Packed', 'de': 'Verpackt', 'fr': "Conditionnée"},
    'packing.status.dispatched':  {'en': 'Dispatched', 'de': 'Versendet', 'fr': "Expédiée"},
    'packing.notify.started':     {'en': '{id} — started', 'de': '{id} — gestartet', 'fr': "{id} — démarrée"},
    'packing.notify.packed':      {'en': '{id} — packed', 'de': '{id} — verpackt', 'fr': "{id} — conditionnée"},
    'packing.notify.dispatched':  {'en': '{id} — dispatched', 'de': '{id} — versendet', 'fr': "{id} — expédiée"},
    'packing.job_soon':      {'en': 'New job form coming soon', 'de': 'Neues Auftragsformular folgt bald', 'fr': "Formulaire de nouvelle tâche bientôt disponible"},

    # Users admin view
    'users.title':            {'en': 'User management', 'de': 'Benutzerverwaltung', 'fr': "Gestion des utilisateurs"},
    'users.subtitle':         {'en': 'Manage users and roles (admin only)', 'de': 'Benutzer und Rollen verwalten (nur Admin)', 'fr': "Gérez les utilisateurs et les rôles (admin uniquement)"},
    'users.access_denied':    {'en': 'Access denied', 'de': 'Zugriff verweigert', 'fr': "Accès refusé"},
    'users.admin_only':       {'en': 'This page is for administrators only.', 'de': 'Diese Seite ist nur für Administratoren.', 'fr': "Cette page est réservée aux administrateurs."},
    'users.col.user':         {'en': 'User', 'de': 'Benutzer', 'fr': "Utilisateur"},
    'users.col.role':         {'en': 'Role', 'de': 'Rolle', 'fr': "Rôle"},
    'users.col.source':       {'en': 'Source', 'de': 'Quelle', 'fr': "Source"},
    'users.source.local':     {'en': 'Local', 'de': 'Lokal', 'fr': "Local"},
    'users.source.idp':       {'en': 'External', 'de': 'Extern', 'fr': "Externe"},
    'users.col.status':       {'en': 'Status', 'de': 'Status', 'fr': "Statut"},
    'users.col.actions':      {'en': 'Actions', 'de': 'Aktionen', 'fr': "Actions"},
    'users.pw_pending':       {'en': 'Password change pending', 'de': 'Passwortänderung ausstehend', 'fr': "Changement de mot de passe requis"},
    'users.role.admin':       {'en': 'Admin', 'de': 'Admin', 'fr': "Admin"},
    'users.role.user':        {'en': 'User', 'de': 'Benutzer', 'fr': "Utilisateur"},
    'users.tip.reset':        {'en': 'Reset password', 'de': 'Passwort zurücksetzen', 'fr': "Réinitialiser le mot de passe"},
    'users.tip.reset_federated': {'en': 'Federated account — password managed by the identity provider',
                                  'de': 'Verbundenes Konto — Passwort wird vom Identitätsanbieter verwaltet',
                                  'fr': "Compte fédéré — mot de passe géré par le fournisseur d’identité"},
    'users.tip.switch_role':  {'en': 'Switch role', 'de': 'Rolle wechseln', 'fr': "Changer de rôle"},
    'users.tip.deactivate':   {'en': 'Deactivate', 'de': 'Deaktivieren', 'fr': "Désactiver"},
    'users.tip.activate':     {'en': 'Activate', 'de': 'Aktivieren', 'fr': "Activer"},
    'users.tip.delete':       {'en': 'Delete', 'de': 'Löschen', 'fr': "Supprimer"},
    'users.create':           {'en': 'Create user', 'de': 'Benutzer erstellen', 'fr': "Créer un utilisateur"},
    'users.create_new':       {'en': 'Create new user', 'de': 'Neuen Benutzer erstellen', 'fr': "Créer un nouvel utilisateur"},
    'users.initial_pw':       {'en': 'Initial password: "{pw}" — must be changed on first login.', 'de': 'Anfangspasswort: „{pw}" — muss bei der ersten Anmeldung geändert werden.', 'fr': "Mot de passe initial : « {pw} » — à changer à la première connexion."},
    'users.enter_username':   {'en': 'Please enter a username.', 'de': 'Bitte einen Benutzernamen eingeben.', 'fr': "Veuillez saisir un nom d’utilisateur."},
    'users.exists':           {'en': 'User "{name}" already exists.', 'de': 'Benutzer „{name}" existiert bereits.', 'fr': "L’utilisateur « {name} » existe déjà."},
    'users.created':          {'en': 'User "{name}" created.', 'de': 'Benutzer „{name}" erstellt.', 'fr': "Utilisateur « {name} » créé."},
    'users.deleted':          {'en': 'User "{name}" deleted.', 'de': 'Benutzer „{name}" gelöscht.', 'fr': "Utilisateur « {name} » supprimé."},
    'users.pw_reset':         {'en': 'Password reset to "{pw}".', 'de': 'Passwort auf „{pw}" zurückgesetzt.', 'fr': "Mot de passe réinitialisé à « {pw} »."},
    'users.not_possible':     {'en': 'Not possible', 'de': 'Nicht möglich', 'fr': "Impossible"},
    'users.delete_confirm':   {'en': 'Really delete user "{name}"? This cannot be undone.', 'de': 'Benutzer „{name}" wirklich löschen? Dies kann nicht rückgängig gemacht werden.', 'fr': "Voulez-vous vraiment supprimer l’utilisateur « {name} » ? Cette action est irréversible."},
    'users.delete_title':     {'en': 'Delete user', 'de': 'Benutzer löschen', 'fr': "Supprimer l’utilisateur"},
    'users.role.operator':    {'en': 'Operator', 'de': 'Operator', 'fr': "Opérateur"},
    'users.role_changed':     {'en': 'Role of "{name}" changed to "{role}".', 'de': 'Rolle von „{name}" auf „{role}" geändert.', 'fr': "Le rôle de « {name} » est désormais « {role} »."},
    'users.change_role_title': {'en': 'Change role of "{name}"', 'de': 'Rolle von „{name}" ändern', 'fr': "Changer le rôle de « {name} »"},
    'users.change_role_hint': {'en': 'Pick one of the three roles — takes effect on the next request.', 'de': 'Wählen Sie eine der drei Rollen — gilt ab der nächsten Anfrage.', 'fr': "Choisissez l’un des trois rôles — prend effet à la requête suivante."},
    'users.tip.username':     {'en': 'Login identifier — letters, digits, dots and dashes.', 'de': 'Anmeldekennung — Buchstaben, Ziffern, Punkte und Bindestriche.', 'fr': "Identifiant de connexion — lettres, chiffres, points et tirets."},
    'users.tip.role_field':   {'en': 'Role granted to the new user: admin (full access), operator (submit/manage jobs), user (read-only).', 'de': 'Rolle des neuen Benutzers: Admin (voller Zugriff), Operator (Jobs starten/verwalten), Benutzer (nur lesen).', 'fr': "Rôle attribué au nouvel utilisateur : admin (accès complet), operator (soumission/gestion des jobs), user (lecture seule)."},

    # Roles tab
    'roles.tab.users':        {'en': 'Users', 'de': 'Benutzer', 'fr': "Utilisateurs"},
    'roles.tab.roles':        {'en': 'Roles', 'de': 'Rollen', 'fr': "Rôles"},
    'roles.tab.hint':         {'en': 'Catalog of the three roles seeded by the backend. Role assignments are changed from the Users tab.', 'de': 'Katalog der drei vom Backend eingerichteten Rollen. Rollenzuweisungen werden im Benutzer-Tab geändert.', 'fr': "Catalogue des trois rôles initialisés par le backend. Les rôles sont attribués depuis l’onglet Utilisateurs."},
    'roles.desc.admin':       {'en': 'Full administration: users, roles, sessions, providers, audit.', 'de': 'Volle Verwaltung: Benutzer, Rollen, Sitzungen, Provider, Audit.', 'fr': "Administration complète : utilisateurs, rôles, sessions, fournisseurs, audit."},
    'roles.desc.operator':    {'en': 'Can submit and manage asynchronous jobs.', 'de': 'Kann asynchrone Jobs starten und verwalten.', 'fr': "Peut soumettre et gérer des jobs asynchrones."},
    'roles.desc.user':        {'en': 'Read-only dashboard access.', 'de': 'Nur-Lese-Zugriff auf das Dashboard.', 'fr': "Accès au tableau de bord en lecture seule."},
    'roles.users_with_role':  {'en': 'Active users with this role', 'de': 'Aktive Benutzer mit dieser Rolle', 'fr': "Utilisateurs actifs ayant ce rôle"},
    'roles.tip.protected':    {'en': 'At least one active admin is always required.', 'de': 'Mindestens ein aktiver Admin ist immer erforderlich.', 'fr': "Au moins un admin actif est toujours requis."},
    'common.save':            {'en': 'Save', 'de': 'Speichern', 'fr': "Enregistrer"},
    'common.close':           {'en': 'Close', 'de': 'Schließen', 'fr': "Fermer"},

    # Print Demo view details
    'print_demo.html_title':   {'en': 'HTML Print', 'de': 'HTML-Druck', 'fr': "Impression HTML"},
    'print_demo.html_desc':    {'en': 'Pass any HTML string — headings, paragraphs, lists, tables. Great for quick text reports.', 'de': 'Beliebige HTML-Zeichenkette übergeben — Überschriften, Absätze, Listen, Tabellen. Ideal für schnelle Textberichte.', 'fr': "Passez n’importe quelle chaîne HTML — titres, paragraphes, listes, tableaux. Idéal pour des rapports texte rapides."},
    'print_demo.image_title':  {'en': 'Image Print', 'de': 'Bilddruck', 'fr': "Impression d’image"},
    'print_demo.image_desc':   {'en': 'Pass a plain base64 string (PNG, JPEG, SVG). The print view centres it on the page with an optional caption.', 'de': 'Einfache base64-Zeichenkette übergeben (PNG, JPEG, SVG). Die Druckansicht zentriert es auf der Seite mit optionaler Beschriftung.', 'fr': "Passez une simple chaîne base64 (PNG, JPEG, SVG). La vue d’impression la centre sur la page avec une légende optionnelle."},
    'print_demo.page_title':   {'en': 'Structured Page', 'de': 'Strukturierte Seite', 'fr': "Page structurée"},
    'print_demo.page_desc':    {'en': 'Combine a title, subtitle, and any mix of HTML and image sections into one print-ready document.', 'de': 'Titel, Untertitel und beliebige HTML- und Bildabschnitte zu einem druckfertigen Dokument kombinieren.', 'fr': "Combine un titre, un sous-titre et n’importe quel mélange de sections HTML et images en un document prêt à imprimer."},
    'print_demo.preview':      {'en': 'Preview', 'de': 'Vorschau', 'fr': "Aperçu"},
    'print_demo.btn_html':     {'en': 'Print HTML report', 'de': 'HTML-Bericht drucken', 'fr': "Imprimer un rapport HTML"},
    'print_demo.btn_image':    {'en': 'Print chart image', 'de': 'Diagrammbild drucken', 'fr': "Imprimer une image de graphique"},
    'print_demo.btn_page':     {'en': 'Print full report', 'de': 'Vollständigen Bericht drucken', 'fr': "Imprimer le rapport complet"},

    # Icons view details
    'icons.how_to':        {'en': 'How to use in NiceGUI', 'de': 'Verwendung in NiceGUI', 'fr': "Comment l’utiliser dans NiceGUI"},
    'icons.click_copy':    {'en': 'Click any icon to copy its string.', 'de': 'Auf ein Symbol klicken, um seine Zeichenkette zu kopieren.', 'fr': "Cliquez sur une icône pour copier sa chaîne."},
    'icons.search':        {'en': 'Search icons…', 'de': 'Symbole suchen…', 'fr': "Rechercher des icônes…"},
    'icons.tab_tabler':    {'en': 'Tabler Icons', 'de': 'Tabler-Symbole', 'fr': "Icônes Tabler"},
    'icons.tab_material':  {'en': 'Material Icons', 'de': 'Material-Symbole', 'fr': "Icônes Material"},

    # Mobile notice
    'mobile.detected':   {'en': 'Mobile Device Detected', 'de': 'Mobilgerät erkannt', 'fr': "Appareil mobile détecté"},
    'mobile.not_optimized': {'en': 'You are visiting on a mobile device. This application is not optimized for mobile use.', 'de': 'Sie besuchen die Seite mit einem Mobilgerät. Diese Anwendung ist nicht für die mobile Nutzung optimiert.', 'fr': "Vous naviguez depuis un appareil mobile. Cette application n’est pas optimisée pour une utilisation mobile."},
    'mobile.visit_github': {'en': 'Visit us on GitHub', 'de': 'Besuchen Sie uns auf GitHub', 'fr': "Visitez-nous sur GitHub"},

    # Design System section titles
    'ds.typography':   {'en': '1 · Typography', 'de': '1 · Typografie', 'fr': "1 · Typographie"},
    'ds.buttons':      {'en': '2 · Buttons', 'de': '2 · Schaltflächen', 'fr': "2 · Boutons"},
    'ds.cards':        {'en': '3 · Cards & Panels', 'de': '3 · Karten & Panels', 'fr': "3 · Cartes & panneaux"},
    'ds.badges':       {'en': '4 · Badges', 'de': '4 · Badges', 'fr': "4 · Badges"},
    'ds.status_dots':  {'en': '5 · Status Dots', 'de': '5 · Statuspunkte', 'fr': "5 · Points de statut"},
    'ds.alerts':       {'en': '6 · Alerts', 'de': '6 · Hinweise', 'fr': "6 · Alertes"},
    'ds.notifications':{'en': '7 · Notifications', 'de': '7 · Benachrichtigungen', 'fr': "7 · Notifications"},
    'ds.inputs':       {'en': '8 · Inputs', 'de': '8 · Eingabefelder', 'fr': "8 · Champs de saisie"},
    'ds.input_groups': {'en': '9 · Input Groups', 'de': '9 · Eingabegruppen', 'fr': "9 · Groupes de champs"},
    'ds.select':       {'en': '10 · Select', 'de': '10 · Auswahl', 'fr': "10 · Sélection"},
    'ds.progress':     {'en': '11 · Progress', 'de': '11 · Fortschritt', 'fr': "11 · Progression"},
    'ds.dialog':       {'en': '12 · Dialog', 'de': '12 · Dialog', 'fr': "12 · Dialogue"},
    'ds.tooltip':      {'en': '13 · Tooltip & Popover', 'de': '13 · Tooltip & Popover', 'fr': "13 · Infobulle & popover"},
    'ds.toggles':      {'en': '14 · Toggles, Checkboxes & Radio', 'de': '14 · Schalter, Kontrollkästchen & Radio', 'fr': "14 · Interrupteurs, cases à cocher & radio"},
    'ds.tabs':         {'en': '15 · Tabs', 'de': '15 · Tabs', 'fr': "15 · Onglets"},
}


class LangState:
    """Per-client holder whose ``lang`` drives all bound translatable elements."""

    lang = binding.BindableProperty()

    def __init__(self, lang: str) -> None:
        self.lang = lang


def _state() -> LangState:
    state = app.storage.client.get('lang_state')
    if state is None:
        state = LangState(app.storage.user.get('language', DEFAULT_LANGUAGE))
        app.storage.client['lang_state'] = state
    return state


def register_view_refresh(refresh) -> None:
    """Register the active sub-page's ``@ui.refreshable`` refresh callback.

    Views built with plain ``t(...)`` strings (rather than :func:`bind`) wrap their
    body in an ``@ui.refreshable`` and register its ``.refresh`` here so the active
    view rebuilds live when the language changes — without a page reload.  Only the
    currently visible view is tracked; navigating to another view overwrites it.
    """
    app.storage.client['lang_view_refresh'] = refresh


def current_language() -> str:
    return _state().lang


def t(key: str, lang: str | None = None) -> str:
    """Translate ``key`` into ``lang`` (defaults to the current language)."""
    lang = lang or current_language()
    entry = _TRANSLATIONS.get(key, {})
    return entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key


def bind(element, key: str):
    """Bind an element's text to the current language so it updates live."""
    element.bind_text_from(_state(), 'lang', backward=lambda lang, k=key: t(k, lang))
    return element


def bind_format(element, key: str, **fmt):
    """Bind an element's text to a translated, ``str.format``-ed key so it updates live."""
    element.bind_text_from(_state(), 'lang', backward=lambda lang: t(key, lang).format(**fmt))
    return element


def bind_language_name(element):
    """Bind an element's text to the current language's display name (e.g. 'Deutsch')."""
    element.bind_text_from(_state(), 'lang', backward=lambda lang: LANGUAGES.get(lang, lang))
    return element


def set_language(code: str) -> None:
    """Switch language live and persist it to the session and the account."""
    if code not in LANGUAGES:
        return
    app.storage.user['language'] = code
    _state().lang = code  # triggers all bound elements to re-render

    # Re-render the active view (built with plain t(...) strings) live.
    refresh = app.storage.client.get('lang_view_refresh')
    if refresh is not None:
        try:
            refresh()
        except Exception:
            pass

    user_id = app.storage.user.get('user_id')
    if user_id is not None:
        # Lazy import avoids a circular dependency at module load time.
        from core.database import get_session
        from services.user_service import UserService
        with get_session() as session:
            UserService(session).set_language(user_id, code)
