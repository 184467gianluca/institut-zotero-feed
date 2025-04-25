import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import re  # Importiere das Modul für reguläre Ausdrücke

# *** Konfiguration ***
GROUP_ID = "5560460"  # Die Zotero Gruppen ID vom IAU
API_BASE_URL = f"https://api.zotero.org/groups/{GROUP_ID}/items/top"
OUTPUT_FILENAME = "zotero_feed.xml"  # Name der Output-Datei
FEED_TITLE = "Publikationen des IAU"  # Titel für den Feed
FEED_ID = f"urn:zotero:group:{GROUP_ID}:items"  # Eindeutige ID für den Feed
FEED_AUTHOR = "IAU"  # Author des Feeds
MAX_LIMIT_PER_REQUEST = 100  # Zotero API Limit pro Seite
SORT_BY = "dateAdded"  # Sortierung der Items
DIRECTION = "desc"  # Sortierrichtung
GITHUB_USERNAME = "184467gianluca"  # Muss für den Link angepasst werden!
REPO_NAME = "institut-zotero-feed"  # Muss für den Link angepasst werden!
# *** Ende Konfiguration ***

# Namespace für Atom Feeds
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM_NS)  # Standard Namespace setzen


def fetch_zotero_items():
    """Holt alle Einträge von Zotero mittels Paginierung."""
    all_entries = []
    start = 0
    total_results = None

    print("Starte Abruf von Zotero. . .")

    while True:
        params = {
            'format': 'atom',
            'sort': SORT_BY,
            'direction': DIRECTION,
            'limit': MAX_LIMIT_PER_REQUEST,
            'start': start,
        }
        try:
            print(f"Rufe Einträge ab: Start={start}, Limit={MAX_LIMIT_PER_REQUEST}")
            response = requests.get(API_BASE_URL, params=params, timeout=30)  # Timeout
            response.raise_for_status()  # Fehler bei HTTP-Statuscodes 4xx/5xx

            # Gesamtzahl nur beim ersten Request holen (aus Header)
            if total_results is None and 'Total-Results' in response.headers:
                total_results = int(response.headers['Total-Results'])
                print(f"Gesamtzahl der Einträge laut API: {total_results}")

            # XML parsen
            atom_xml = response.text
            root = ET.fromstring(atom_xml)
            entries = root.findall(f'{{{ATOM_NS}}}entry')  # Einträge mit Namespace

            if not entries:
                print("Keine weiteren Einträge gefunden.")
                break  # Keine Einträge mehr, Schleife beenden

            print(f"{len(entries)} Einträge auf dieser Seite gefunden.")
            all_entries.extend(entries)
            start += len(entries)  # Erhöhe um die tatsächlich erhaltene Anzahl

            # Sicherheitsabbruch, falls total_results bekannt ist
            if total_results is not None and start >= total_results:
                print("Alle erwarteten Einträge abgerufen.")
                break

        except requests.exceptions.RequestException as e:
            print(f"Fehler bei API-Abruf: {e}")
            return None  # Fehler signalisieren
        except ET.ParseError as e:
            print(f"Fehler beim Parsen von XML: {e}")
            print("Fehlerhafte Antwort (erste 500 Zeichen):", atom_xml[:500])
            return None  # Fehler signalisieren

    print(f"Insgesamt {len(all_entries)} Einträge von Zotero geholt.")
    return all_entries


def create_combined_feed(entries):
    """Erstellt einen neuen Atom-Feed aus den gesammelten Einträgen."""
    if entries is None:
        print("Keine Einträge zum Erstellen des Feeds vorhanden.")
        return None

    # Haupt-Feed-Element erstellen
    feed = ET.Element(f'{{{ATOM_NS}}}feed')

    # Feed-Metadaten hinzufügen
    title = ET.SubElement(feed, f'{{{ATOM_NS}}}title')
    title.text = FEED_TITLE

    id_elem = ET.SubElement(feed, f'{{{ATOM_NS}}}id')
    id_elem.text = FEED_ID  # Eindeutige ID für den Feed

    # Ermittle die späteste 'updated'-Zeit der Einträge
    latest_update_time = datetime.now(timezone.utc)
    entry_update_times = []
    for entry in entries:
        updated_tag = entry.find(f'{{{ATOM_NS}}}updated')
        if updated_tag is not None and updated_tag.text:
            try:
                entry_update_times.append(
                    datetime.fromisoformat(updated_tag.text.replace("Z", "+00:00"))
                )
            except ValueError:
                pass  # Ungültige Zeitstempel ignorieren
    if entry_update_times:
        latest_update_time = max(entry_update_times)

    updated = ET.SubElement(feed, f'{{{ATOM_NS}}}updated')
    updated.text = latest_update_time.isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )

    author_elem = ET.SubElement(feed, f'{{{ATOM_NS}}}author')
    name_elem = ET.SubElement(author_elem, f'{{{ATOM_NS}}}name')
    name_elem.text = FEED_AUTHOR

    # Link zum Feed selbst
    link_self = ET.SubElement(
        feed,
        f'{{{ATOM_NS}}}link',
        attrib={
            "rel": "self",
            "href": f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{OUTPUT_FILENAME}",
        },
    )

    # Funktion, um den Titel-Text zu bereinigen und zu entscheiden, ob er HTML ist.
    def process_title_text(text):
        """
        Verarbeitet einen Titel-Text für den Atom-Feed.

        Args:
            text: Der Titel-Text.

        Returns:
            Ein Tupel: (bereinigter Text, ist_html)
        """
        # Entferne überflüssige Leerzeichen und Zeilenumbrüche
        text = " ".join(text.strip().split())

        # Regulärer Ausdruck, um HTML-Tags zu finden (vereinfacht)
        html_pattern = re.compile(r"<[^>]+>")
        if html_pattern.search(text):
            # Ersetze bestimmte HTML-Entities, die vorkommen könnten.
            text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            return text, True  # Betrachte es als HTML
        else:
            # Escapen von Sonderzeichen für Plain Text
            text = text.replace("<", "&lt;").replace(">", "&gt;")
            return text, False

    # Alle gesammelten Einträge hinzufügen
    for entry in entries:
        title_tag = entry.find(f'{{{ATOM_NS}}}title')
        if title_tag is not None and title_tag.text:
            cleaned_text, is_html = process_title_text(title_tag.text)
            title_tag.text = cleaned_text
            if is_html:
                title_tag.set("type", "html")

        feed.append(entry)

    # XML-Baum in String umwandeln und speichern
    try:
        tree = ET.ElementTree(feed)
        # Wichtig: encoding='unicode' für String
        xml_string = ET.tostring(feed, encoding="unicode", method="xml")
        # XML Deklaration manuell hinzufügen
        final_xml = '<?xml version="1.0" encoding="utf-8"?>\n' + xml_string

        with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
            f.write(final_xml)
        print(f"Feed erfolgreich in '{OUTPUT_FILENAME}' geschrieben.")
        return True
    except Exception as e:
        print(f"Fehler beim Schreiben der Feed-Datei: {e}")
        return False


# --- Hauptausführung ---
if __name__ == "__main__":
    zotero_entries = fetch_zotero_items()
    if zotero_entries is not None:
        create_combined_feed(zotero_entries)
    else:
        print("Feed-Generierung fehlgeschlagen aufgrund vorheriger Fehler.")

