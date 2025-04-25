import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# *** Konfiguration ***
GROUP_ID = "5560460" # Die Zotero Gruppen ID vom IAU
API_BASE_URL = f"https://api.zotero.org/groups/{GROUP_ID}/items/top"
OUTPUT_FILENAME = "zotero_feed.xml" # Name der Output-Datei
FEED_TITLE = "Publikationen des IAU" # Titel für den Feed
FEED_ID = f"urn:zotero:group:{GROUP_ID}:items" # Eindeutige ID für den Feed
FEED_AUTHOR = "IAU" # Author des Feeds
MAX_LIMIT_PER_REQUEST = 100 # Zotero API Limit pro Seite in machen Quellen auch 150?
SORT_BY = "dateAdded" # Sortierung der Items
DIRECTION = "desc" # Sortierrichtung
GITHUB_USERNAME = "184467gianluca" # Muss für den Link angepasst werden!
REPO_NAME = "institut-zotero-feed" # Muss für den Link angepasst werden!
# *** Ende Konfiguration ***

# Namespace für Atom Feeds (war wichtig für XML Verarbeitung)
ATOM_NS = "http://www.w3.org/2005/Atom"
ZOTERO_NS = "http://zotero.org/ns/api" # Namespace für Zotero spezifische Daten
ET.register_namespace("", ATOM_NS) # Standard Namespace setzen
ET.register_namespace("z", ZOTERO_NS) # Prefix für Zotero Namespace


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
            'start': start
        }
        try:
            print(f"Rufe Einträge ab: Start={start}, Limit={MAX_LIMIT_PER_REQUEST}")
            response = requests.get(API_BASE_URL, params=params, timeout=30) # Timeout hinzugefügt
            response.raise_for_status()   # Löst einen Fehler aus bei HTTP-Statuscodes 4xx/5xx

            # Gesamtzahl nur beim ersten Request holen (aus Header)
            if total_results is None and 'Total-Results' in response.headers:
                total_results = int(response.headers['Total-Results'])
                print(f"Gesamtzahl der Einträge laut API: {total_results}")

            # XML parsen
            atom_xml = response.text
            root = ET.fromstring(atom_xml)
            entries = root.findall(f'{{{ATOM_NS}}}entry') # Einträge finden mit Namespace

            if not entries:
                print("Keine weiteren Einträge gefunden.")
                break # Keine Einträge mehr, Schleife beenden

            print(f"{len(entries)} Einträge auf dieser Seite gefunden.")
            all_entries.extend(entries)
            start += len(entries) # Wichtig: erhöhe um die *tatsächlich* erhaltene Anzahl

            # Sicherheitsabbruch, falls total_results bekannt ist
            if total_results is not None and start >= total_results:
                print("Alle erwarteten Einträge abgerufen.")
                break

        except requests.exceptions.RequestException as e:
            print(f"Fehler bei API-Abruf: {e}")
            # Entscheiden, ob abgebrochen oder wiederholt werden soll. Hier brechen wir ab.
            return None # Fehler signalisieren
        except ET.ParseError as e:
            print(f"Fehler beim Parsen von XML: {e}")
            print("Fehlerhafte Antwort (erste 500 Zeichen):", atom_xml[:500])
            return None # Fehler signalisieren


    print(f"Insgesamt {len(all_entries)} Einträge von Zotero geholt.")
    return all_entries

def create_combined_feed(entries):
    """Erstellt einen neuen Atom-Feed aus den gesammelten Einträgen."""
    if entries is None:
        print("Keine Einträge zum Erstellen des Feeds vorhanden.")
        return None

    # Haupt-Feed-Element erstellen
    feed = ET.Element(f'{{{ATOM_NS}}}feed')
    # Entferne die Deklaration des 'html' Namespace hier.

    # Feed-Metadaten hinzufügen
    title = ET.SubElement(feed, f'{{{ATOM_NS}}}title')
    title.text = FEED_TITLE

    id_elem = ET.SubElement(feed, f'{{{ATOM_NS}}}id')
    id_elem.text = FEED_ID # Eindeutige ID für den Feed

    # Verwende den 'updated' Zeitstempel des *neuesten* Eintrags im Feed
    # oder die aktuelle Zeit, falls Einträge keine gültigen 'updated' haben
    latest_update_time = datetime.now(timezone.utc)
    entry_update_times = {} # Dictionary, um die 'updated' Zeiten pro Eintrag zu speichern
    for entry in entries:
        updated_tag = entry.find(f'{{{ATOM_NS}}}updated')
        if updated_tag is not None and updated_tag.text:
            try:
                dt_object = datetime.fromisoformat(updated_tag.text.replace('Z', '+00:00'))
                entry_update_times[entry] = dt_object
                latest_update_time = max(latest_update_time, dt_object)
            except ValueError:
                pass # Ignoriere ungültige Zeitstempel

        # Titel-Element bearbeiten, um HTML zu escapen oder als HTML zu deklarieren
        title_tag = entry.find(f'{{{ATOM_NS}}}title')
        if title_tag is not None and title_tag.text:
            if "<sub" in title_tag.text:
                title_tag.set('type', 'html')
            else:
                # Sicherstellen, dass keine HTML-Fragmente unbehandelt bleiben
                title_tag.text = title_tag.text.replace("<", "&lt;").replace(">", "&gt;")

    updated = ET.SubElement(feed, f'{{{ATOM_NS}}}updated')
    # Format nach RFC3339 / ISO 8601
    updated.text = latest_update_time.isoformat(timespec='seconds').replace('+00:00', 'Z')


    author_elem = ET.SubElement(feed, f'{{{ATOM_NS}}}author')
    name_elem = ET.SubElement(author_elem, f'{{{ATOM_NS}}}name')
    name_elem.text = FEED_AUTHOR

    # Link zum Feed selbst
    link_self = ET.SubElement(feed, f'{{{ATOM_NS}}}link', attrib={'rel': 'self', 'href': f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{OUTPUT_FILENAME}"})

    # Alle gesammelten Einträge hinzufügen
    for entry in entries:
        # Entferne Zotero-spezifische Namespaces von den Einträgen, um Interoperabilität zu verbessern
        # Behalte aber die eigentlichen Elemente bei, falls sie wichtige Daten enthalten
        for child in list(entry):
            if child.tag.startswith('{' + ZOTERO_NS + '}'):
                # Optional: Du könntest hier entscheiden, ob du diese Elemente behalten und
                # unter einem anderen, generischen Namespace zusammenfassen möchtest.
                # Für maximale Interoperabilität empfiehlt es sich, sie zu entfernen,
                # es sei denn, andere Systeme erwarten diese spezifischen Daten.
                entry.remove(child)
        feed.append(entry)

    # XML-Baum in String umwandeln und speichern
    try:
        tree = ET.ElementTree(feed)
        # Wichtig: encoding='unicode' für String, 'utf-8' mit xml_declaration für Bytes
        xml_string = ET.tostring(feed, encoding='unicode', method='xml')
        # XML Deklaration manuell hinzufügen, da tostring(encoding='unicode') sie nicht erzeugt
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