"""Katalog „Fertige Anwendungen“: Anwendung × Technik. Claude baut die Anwendung auf dem Grundgerüst der gewählten Vorlage auf."""
from dataclasses import dataclass

WEB = ("laravel", "java-spring", "react-vite", "vue-vite", "next", "nuxt", "angular")

TECH_LABEL = {
    "laravel": "Laravel (PHP)", "java-spring": "Spring Boot (Java)", "react-vite": "React (TypeScript, Vite)", "vue-vite": "Vue 3 (TypeScript, Vite)",
    "next": "Next.js", "nuxt": "Nuxt 3", "angular": "Angular", "py-qt": "Qt (Python, PySide6)", "java-swing": "Java Swing",
}

# Was Claude über das jeweilige Grundgerüst wissen muss. Wichtig: Claude hat im Assistenten keine Shell – nichts kann installiert oder ausgeführt werden.
TECH_NOTES = {
    "laravel": "Technik: Laravel (PHP 8, bereits per composer angelegt, SQLite als Standard-Datenbank). Lege Migrationen, Eloquent-Modelle, Controller, Routen (routes/web.php), "
               "Blade-Views und Seeder (Beispieldaten und ein Admin-Benutzer) von Hand an. Du kannst keine Befehle ausführen (kein artisan, composer oder npm): "
               "füge keine neuen Pakete hinzu und nutze kein Vite – das Styling kommt aus einer eigenen Datei public/css/app.css, eingebunden per <link>. "
               "Schreibe in die README, dass man 'php artisan migrate --seed' ausführt (dafür braucht PHP die Erweiterung pdo_sqlite) und wie die Anmeldedaten lauten.",
    "java-spring": "Technik: Spring Boot 4 mit Maven (mvnw liegt bei). Oberfläche als statische Seiten unter src/main/resources/static (HTML, CSS, JavaScript) und eine REST-API "
                   "in Controllern; Daten in einer JSON-Datei oder im Speicher. Weitere Abhängigkeiten dürfen in die pom.xml (Maven lädt sie beim Start). Der Server läuft auf Port 8080.",
    "react-vite": "Technik: React + TypeScript mit Vite. Reines Frontend: Daten und Anmeldung im Browser (localStorage), Seitenwechsel mit einem selbst geschriebenen einfachen Router. "
                  "Du kannst nichts installieren: nutze nur die Pakete aus package.json. Das Designer-Formular Form1 darfst du löschen oder ersetzen.",
    "vue-vite": "Technik: Vue 3 + TypeScript mit Vite. Reines Frontend: Daten und Anmeldung im Browser (localStorage), Seitenwechsel mit einem selbst geschriebenen einfachen Router. "
                "Du kannst nichts installieren: nutze nur die Pakete aus package.json. Das Designer-Formular Form1 darfst du löschen oder ersetzen.",
    "next": "Technik: Next.js (App Router, TypeScript). Daten über Route-Handler unter app/api, gespeichert in einer JSON-Datei (data/db.json). "
            "Du kannst nichts installieren: nutze nur die Pakete aus package.json. Das Designer-Formular Form1 darfst du löschen oder ersetzen.",
    "nuxt": "Technik: Nuxt 3 (TypeScript). Daten über Server-Routen unter server/api, gespeichert in einer JSON-Datei (data/db.json). "
            "Du kannst nichts installieren: nutze nur die Pakete aus package.json. Das Designer-Formular Form1 darfst du löschen oder ersetzen.",
    "angular": "Technik: Angular (eigenständige Komponenten, TypeScript). Reines Frontend: Daten und Anmeldung in Services mit localStorage; Seitenwechsel mit dem Angular-Router, "
               "falls @angular/router in package.json steht, sonst mit einer einfachen eigenen Lösung. Du kannst nichts installieren: nutze nur die Pakete aus package.json.",
    "py-qt": "Technik: Python mit PySide6 (QtWidgets, bei Bedarf QtSql mit SQLite oder QtWebEngine). Nur Bibliotheken, die in requirements.txt stehen oder zur Standardbibliothek "
             "gehören. Gliedere den Code in ein Paket (nicht alles in main.py); Start mit 'python main.py'. Gestalte die Oberfläche selbst im Code. "
             "Achtung PySide6: QFileSystemModel und QFileIconProvider liegen in PySide6.QtWidgets (nicht QtGui); QAction und QShortcut in PySide6.QtGui; "
             "importiere nur Namen, die es dort wirklich gibt.",
    "java-swing": "Technik: Java Swing, nur JDK-Standardbibliothek ohne Fremdpakete. Weitere Klassen dürfen als eigene .java-Dateien im Projektordner liegen; "
                  "gestartet wird Form1.java mit 'java Form1.java'.",
}

GENERAL = ("Allgemein: Benutzeroberfläche auf Deutsch, aufgeräumt und modern, mit sinnvollen Beispieldaten, damit man sofort etwas sieht. Prüfe Eingaben und zeige verständliche Fehlermeldungen. "
           "Schreibe eine kurze README.md (Start, Anmeldedaten, Aufbau). Arbeite vollständig: keine leeren Platzhalter-Seiten.")


@dataclass(frozen=True)
class App:
    id: str
    name: str
    blurb: str
    techs: tuple
    spec: str


APPS = [
    App("cms", "CMS (WordPress-Ersatz)", "Seiten und Beiträge verwalten, mit Admin-Bereich", WEB,
        "Baue ein Content-Management-System als Ersatz für WordPress. Öffentlich: Startseite mit den neuesten Beiträgen, Beitragsseite, freie Seiten (z. B. Über uns, Impressum), "
        "Kategorien, Suche und eine Navigation, die aus den Seiten entsteht. Admin-Bereich unter /admin mit Anmeldung (ein Admin-Benutzer mit Beispielpasswort, das in der README steht): "
        "Beiträge und Seiten anlegen, bearbeiten, löschen (Titel, Adresse/Slug, Inhalt mit einfacher Formatierung, Status Entwurf/Veröffentlicht, Kategorie, Datum), Kategorien verwalten, "
        "Website-Titel einstellen. Lege einige Beispielbeiträge an."),
    App("shop", "Online-Shop (Shopify/WooCommerce-Ersatz)", "Produkte, Warenkorb, Bestellung, Admin-Bereich", WEB,
        "Baue einen Online-Shop. Kundenbereich: Produktliste mit Kategorien, Suche und Sortierung, Produktseite (Bild, Beschreibung, Preis, Lagerbestand), Warenkorb (Menge ändern, entfernen, "
        "Summe mit Mehrwertsteuer), Kasse mit Adressformular, Bestellbestätigung mit Bestellnummer. Zahlung nur als Platzhalter „Rechnung“ (keine echte Zahlungsanbindung). "
        "Admin-Bereich mit Anmeldung (Beispielpasswort in der README): Produkte und Kategorien verwalten, Bestellungen ansehen und den Status ändern (offen, bezahlt, versandt). "
        "Lege etwa zwölf Beispielprodukte in drei Kategorien an (Bilder als einfache farbige Platzhalter)."),
    App("website", "Unternehmens-Website mit Backend", "Startseite, Leistungen, Team, Kontaktformular und Verwaltungsbereich", WEB,
        "Baue eine moderne Unternehmens-Website für eine fiktive Firma (nimm den Projektnamen als Firmennamen). Seiten: Startseite mit großem Kopfbereich und Aufruf zum Handeln, Leistungen, "
        "Über uns mit Team, Referenzen/Kundenstimmen, Kontakt mit Formular (Eingaben prüfen und speichern bzw. bestätigen), Impressum und Datenschutz als Platzhaltertexte. "
        "Responsive für Handy und Desktop, durchgehende Navigation und Fußzeile. "
        "Backend: Verwaltungsbereich unter /admin mit Anmeldung (ein Admin-Benutzer, Beispielpasswort in der README). Dort pflegt man Leistungen, Team, Referenzen und die Texte der Startseite "
        "(anlegen, bearbeiten, löschen, Reihenfolge) und sieht die eingegangenen Kontaktanfragen (Liste, Details, als gelesen markieren, löschen). Die öffentliche Seite liest alle Inhalte aus dem Backend. "
        "Lege Beispielinhalte an, damit die Seite sofort gefüllt ist."),
    App("access", "Datenbank-Anwendung (MS-Access-Stil)", "Tabellen, Formulare, Abfragen und Berichte", ("py-qt",),
        "Baue eine Desktop-Datenbankanwendung im Stil von Microsoft Access mit SQLite. Funktionen: Tabellen anlegen und Spalten festlegen (Name, Typ, Pflichtfeld), Daten in einer "
        "bearbeitbaren Tabellenansicht pflegen, Formularansicht für einen Datensatz mit Blättern (erster/vorheriger/nächster/letzter), Abfragen mit SQL-Editor und Ergebnistabelle, "
        "Berichte als druckbare Ansicht mit Export als PDF, Import und Export von CSV. Liefere eine Beispieldatenbank „Kundenverwaltung“ (Kunden, Aufträge) mit Daten mit."),
    App("filemanager", "Dateimanager", "Ordnerbaum, Dateiliste, Kopieren, Verschieben, Suche", ("py-qt", "java-swing"),
        "Baue einen Dateimanager für den Desktop. Ordnerbaum links, Dateiliste rechts mit Name, Größe, Typ und Änderungsdatum (sortierbar), Adressleiste, Zurück/Vor/Hoch, Ordner neu laden. "
        "Aktionen: Öffnen (mit dem Standardprogramm), Kopieren, Ausschneiden, Einfügen, Umbenennen, neuer Ordner, Löschen (in den Papierkorb, wo möglich, vor dem Löschen nachfragen), "
        "Kontextmenü, Tastenkürzel (F2, Entf, Strg+C/X/V), Suchfeld zum Filtern der Liste und eine Statusleiste mit Anzahl und Größe der Auswahl."),
    App("browser", "Webbrowser", "Tabs, Adressleiste, Lesezeichen, Verlauf", ("py-qt",),
        "Baue einen Webbrowser mit QtWebEngine. Tabs (öffnen, schließen, Titel und Symbol der Seite), Adressleiste (Adresse oder Suchbegriff – dann Suche über eine Suchmaschine), "
        "Zurück/Vor/Neu laden/Startseite, Fortschrittsanzeige, Lesezeichen (speichern und verwalten in einer JSON-Datei im Konfigurationsordner), Verlauf, Zoom (Strg+Plus/Minus/0), "
        "Vollbild (F11), Suche auf der Seite (Strg+F). Wichtig: PySide6.QtWebEngineWidgets muss vor dem Erzeugen der QApplication importiert werden."),
]
BY_ID = {a.id: a for a in APPS}


def prompt(app_id: str, tech_id: str) -> str:
    """Vorbelegter Auftrag für Claude (im Assistenten bearbeitbar)."""
    a = BY_ID[app_id]
    return "\n\n".join((a.spec, TECH_NOTES[tech_id], GENERAL))
