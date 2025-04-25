import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import re # Für Jahreszahl-Extraktion

# --- Konfiguration ---
GROUP_ID = "5560460" # Die Zotero Gruppen ID vom IAU
API_BASE_URL = f"https://api.zotero.org/groups/{GROUP_ID}/items" # Basis-URL für Items
OUTPUT_FILENAME = "zotero_rss_minimal.xml" # Name der Output-Datei

# RSS Channel Konfiguration
RSS_CHANNEL_TITLE = "IAU Publications (Minimal)"
RSS_CHANNEL_LINK = "https://www.iau.uni-frankfurt.de" # Hauptlink des Instituts
RSS_CHANNEL_DESCRIPTION = "Publikationen des Instituts für Atmosphäre und Umwelt (IAU) - Minimalformat"
RSS_CHANNEL_LANGUAGE = "de-DE" # Sprache des Feeds (z.B. de-DE oder en-US)

# Zotero API Abruf Konfiguration
ZOTERO_ITEM_TYPE = "items/top" # Oder "items" für alle, "publications" etc.
MAX_LIMIT_PER_REQUEST = 100 # Zotero API Limit pro Seite
SORT_BY = "dateAdded" # Sortierung der Items ('dateAdded', 'dateModified', 'title')
DIRECTION = "desc" # Sortierrichtung ('asc' oder 'desc')
# Präfix für Tags, die als Arbeitsgruppe interpretiert werden sollen (AKTUELL DEAKTIVIERT)
AG_TAG_PREFIX = "AG "

# GitHub Pages Konfiguration (nur für Fallback-GUID relevant)
GITHUB_USERNAME = "184467gianluca"
REPO_NAME = "institut-zotero-feed"
# --- Ende Konfiguration ---


def extract_year(date_str):
    """Versucht, die vierstellige Jahreszahl aus einem Datumsstring zu extrahieren."""
    if not date_str:
        return None
    # Suche nach einer vierstelligen Zahl (potenziell das Jahr)
    match = re.search(r'\b(\d{4})\b', str(date_str))
    if match:
        return match.group(1)
    # Fallback für einfache Jahreszahlen
    try:
        if isinstance(date_str, int) and 1900 < date_str < 2100:
             return str(date_str)
    except:
        pass
    return None

def format_authors(creators):
    """Formatiert die Autorenliste aus dem creators-Array."""
    if not creators:
        return ""
    author_list = []
    for creator in creators:
        # Nur Autoren berücksichtigen
        if creator.get('creatorType') == 'author':
            last_name = creator.get('lastName', '')
            first_name = creator.get('firstName', '')
            if last_name and first_name:
                # Standard-Reihenfolge (Nachname, Vorname) - Anpassen falls gewünscht
                author_list.append(f"{last_name}, {first_name}")
            elif last_name:
                author_list.append(last_name)
            elif first_name:
                # Sollte nicht vorkommen, aber sicherheitshalber
                author_list.append(first_name)
            elif creator.get('name'): # Für institutionelle Autoren etc.
                 author_list.append(creator['name'])

    return ", ".join(author_list)

def find_best_link_json(item_data):
    """Sucht den besten Link (DOI, URL) aus den JSON-Daten."""
    doi = item_data.get('DOI')
    if doi and str(doi).strip():
        # Ensure DOI doesn't already start with http(s)://doi.org/
        doi_text = str(doi).strip()
        if doi_text.startswith('http://doi.org/') or doi_text.startswith('https://doi.org/'):
            return doi_text
        else:
            # Remove potential leading slashes or other prefixes before adding https://doi.org/
            doi_text = re.sub(r'^(doi:|/)+', '', doi_text)
            return f"https://doi.org/{doi_text}"


    url = item_data.get('url')
    if url and str(url).strip().startswith(('http://', 'https://')):
        return str(url).strip()

    # Fallback: Link zur Zotero-Seite (aus 'links'->'alternate')
    # Check if 'links' exists and is a dictionary
    links_data = item_data.get('links')
    if isinstance(links_data, dict) and 'alternate' in links_data:
        alt_link_data = links_data['alternate']
        # Check if 'alternate' link data is a dictionary and has 'href'
        if isinstance(alt_link_data, dict):
             alt_link = alt_link_data.get('href')
             if alt_link:
                 return alt_link

    return None # Kein Link gefunden

def get_categories_json(item_data, year):
    """Extrahiert Kategorien (Jahr, AG-Tags - AG aktuell deaktiviert) aus den JSON-Daten."""
    categories = []
    # 1. Jahreszahl hinzufügen
    if year:
        categories.append(year)

    # 2. Arbeitsgruppen-Tags hinzufügen (AKTUELL AUSKOMMENTIERT)
    #    -> Um dies zu aktivieren, entfernen Sie die Kommentarzeichen (#)
    #       in den folgenden Zeilen, sobald die Tags in Zotero existieren.
    # tags = item_data.get('tags', [])
    # for tag_info in tags:
    #     tag = tag_info.get('tag')
    #     if tag and tag.startswith(AG_TAG_PREFIX):
    #         # Füge den Tag ohne Präfix hinzu (oder mit, je nach Wunsch)
    #         # categories.append(tag) # Mit Präfix
    #         categories.append(tag[len(AG_TAG_PREFIX):].strip()) # Ohne Präfix

    # 3. AG-Leiter kann hier nicht automatisch ermittelt werden

    return categories

def fetch_zotero_items():
    """Holt alle Einträge von Zotero mittels Paginierung im JSON-Format."""
    all_items_data = []
    start = 0
    total_results = None
    fetch_url = f"https://api.zotero.org/groups/{GROUP_ID}/{ZOTERO_ITEM_TYPE}"

    print("Starte Abruf von Zotero (JSON Format)...")

    while True:
        params = {
            'format': 'json', # JSON-Format anfordern
            # 'include': 'data,bib', # 'data' ist in JSON meist Standard, 'bib' könnte nützlich sein für Titelformatierung
            'sort': SORT_BY,
            'direction': DIRECTION,
            'limit': MAX_LIMIT_PER_REQUEST,
            'start': start
        }
        try:
            print(f"Rufe Einträge ab: Start={start}, Limit={MAX_LIMIT_PER_REQUEST}")
            # Wichtig: Zotero API Version Header hinzufügen
            headers = {'Zotero-API-Version': '3'}
            response = requests.get(fetch_url, params=params, headers=headers, timeout=60)
            response.raise_for_status()

            # Gesamtzahl nur beim ersten Request holen (aus Header)
            if total_results is None and 'Total-Results' in response.headers:
                total_results = int(response.headers['Total-Results'])
                print(f"Gesamtzahl der Einträge laut API: {total_results}")

            # JSON parsen
            items_json = response.json()

            if not items_json:
                print("Keine weiteren Einträge gefunden (leere JSON-Antwort).")
                break

            print(f"{len(items_json)} Einträge auf dieser Seite gefunden.")

            # Extrahiere die benötigten Daten aus jedem JSON-Item
            for item in items_json:
                # Ensure item is a dictionary before proceeding
                if not isinstance(item, dict):
                    print(f"Warnung: Unerwartetes Format für Eintrag gefunden, überspringe: {item}")
                    continue

                item_data = item.get('data', {}) # Die relevanten Felder sind im 'data'-Objekt
                # Ensure item_data is a dictionary
                if not isinstance(item_data, dict):
                     print(f"Warnung: Unerwartetes 'data'-Format für Eintrag {item.get('key')}, überspringe.")
                     continue


                # --- Datenextraktion ---
                title = item_data.get('title', "Unbekannter Titel")
                creators = item_data.get('creators', [])
                date_str = item_data.get('date') # Kann Jahr, Datum, etc. sein
                journal_abbr = item_data.get('journalAbbreviation')
                pub_title = item_data.get('publicationTitle') # Fallback für Journal
                volume = item_data.get('volume')
                # issue = item_data.get('issue') # Falls doch benötigt
                # pages = item_data.get('pages') # Falls doch benötigt

                year = extract_year(date_str)
                authors_formatted = format_authors(creators)
                journal_display = journal_abbr if journal_abbr else pub_title # Bevorzuge Abkürzung

                # --- RSS Felder zusammenbauen ---
                # Titel-Tag
                rss_title_parts = []
                if authors_formatted:
                    rss_title_parts.append(authors_formatted)
                if year:
                    rss_title_parts.append(f"({year})")
                # Ensure title is a string
                rss_title_parts.append(str(title))
                if journal_display:
                     rss_title_parts.append(str(journal_display))
                if volume:
                     rss_title_parts.append(str(volume))
                # Trennzeichen: Punkt, außer vor der Jahreszahl-Klammer
                rss_title = ""
                for i, part in enumerate(rss_title_parts):
                    if part: # Nur hinzufügen, wenn Teil vorhanden ist
                        part_str = str(part) # Sicherstellen, dass es ein String ist
                        if i > 0 and not part_str.startswith('('):
                            rss_title += ". "
                        rss_title += part_str

                # Link-Tag
                rss_link = find_best_link_json(item_data)

                # Kategorien
                rss_categories = get_categories_json(item_data, year)

                # GUID (Eindeutige ID für Feed Reader)
                # Zotero Key oder Item ID ist gut geeignet
                guid = item.get('key') or item_data.get('key')
                if not guid and rss_link: # Fallback auf Link
                    guid = rss_link
                elif not guid: # Letzter Fallback auf Titel
                     guid = rss_title

                # Veröffentlichungsdatum (optional für RSS, aber gut zu haben)
                # Hier verwenden wir nur das Jahr für Kategorien, aber man könnte auch pubDate hinzufügen
                # pub_date_rss = ... (Code von vorher anpassen, falls benötigt)


                all_items_data.append({
                    'rss_title': rss_title,
                    'rss_link': rss_link,
                    'rss_categories': rss_categories,
                    'guid': guid,
                    # 'pubDate': pub_date_rss # Auskommentiert, da nicht explizit gefordert
                })


            start += len(items_json) # Erhöhe um die Anzahl der erhaltenen Items

            # Sicherheitsabbrüche
            if total_results is not None and start >= total_results:
                print("Alle erwarteten Einträge abgerufen.")
                break
            if len(items_json) < MAX_LIMIT_PER_REQUEST:
                print("Weniger Einträge als Limit erhalten, nehme an, das waren die letzten.")
                break

        except requests.exceptions.RequestException as e:
            print(f"Fehler bei API-Abruf: {e}")
            # Bei Fehlern die teilweise gesammelten Daten zurückgeben? Oder None?
            # return None # Sicherer: Bei Fehler abbrechen
            print("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break # Breche die Schleife ab, verarbeite, was wir haben
        except Exception as e: # Breitere Ausnahmebehandlung für JSON-Parsing etc.
            print(f"Unerwarteter Fehler beim Verarbeiten der Daten: {e}")
            # Check if response exists before trying to access its text attribute
            error_context = response.text[:500] if 'response' in locals() and hasattr(response, 'text') else "Keine Antwortdaten verfügbar"
            print(f"Fehlerhafte Antwort/Kontext (erste 500 Zeichen): {error_context}")
            # return None
            print("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break

    print(f"Insgesamt {len(all_items_data)} Einträge von Zotero verarbeitet.")
    return all_items_data

def create_rss_feed(items_data):
    """Erstellt einen neuen, minimalen RSS 2.0 Feed."""
    if not items_data: # Prüfe auf leere Liste oder None
        print("Keine Einträge zum Erstellen des Feeds vorhanden.")
        return None

    # RSS Root-Element erstellen
    rss = ET.Element('rss', version="2.0")
    # Channel-Element erstellen
    channel = ET.SubElement(rss, 'channel')

    # Channel-Metadaten hinzufügen
    ET.SubElement(channel, 'title').text = RSS_CHANNEL_TITLE
    ET.SubElement(channel, 'link').text = RSS_CHANNEL_LINK
    ET.SubElement(channel, 'description').text = RSS_CHANNEL_DESCRIPTION
    if RSS_CHANNEL_LANGUAGE:
        ET.SubElement(channel, 'language').text = RSS_CHANNEL_LANGUAGE

    # Zeitstempel der Generierung
    now_rfc822 = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    ET.SubElement(channel, 'lastBuildDate').text = now_rfc822
    ET.SubElement(channel, 'generator').text = "Zotero Feed Generator Script (Minimal)"

    # Alle gesammelten Einträge als <item> hinzufügen
    for item_data in items_data:
        item = ET.SubElement(channel, 'item')
        # Ensure title is a string before setting
        ET.SubElement(item, 'title').text = str(item_data.get('rss_title', ''))

        rss_link = item_data.get('rss_link')
        if rss_link:
            # Ensure link is a string
            ET.SubElement(item, 'link').text = str(rss_link)
        # else: Kein Fallback-Link mehr nötig? Oder Link zum Channel?

        # Keine <description> mehr

        # Kategorien hinzufügen
        rss_categories = item_data.get('rss_categories', [])
        if isinstance(rss_categories, list): # Ensure it's a list
             for category_name in rss_categories:
                 # Ensure category name is a string
                 ET.SubElement(item, 'category').text = str(category_name)

        # GUID hinzufügen
        guid_is_permalink = "false"
        guid_text = item_data.get('guid')
        if guid_text and str(guid_text).startswith(('http://', 'https://')):
             guid_is_permalink = "true"
        # Stelle sicher, dass GUID Text hat
        if not guid_text:
             guid_text = item_data.get('rss_title', '') # Letzter Fallback

        guid_elem = ET.SubElement(item, 'guid', isPermaLink=guid_is_permalink)
        # Ensure GUID text is a string
        guid_elem.text = str(guid_text)

        # <pubDate> ist optional und aktuell nicht hinzugefügt

    # XML-Baum in String umwandeln und speichern
    try:
        ET.indent(rss, space="  ", level=0)
        tree = ET.ElementTree(rss)
        tree.write(OUTPUT_FILENAME, encoding="utf-8", xml_declaration=True)
        print(f"Minimaler RSS Feed erfolgreich in '{OUTPUT_FILENAME}' geschrieben.")
        return True
    except Exception as e:
        print(f"Fehler beim Schreiben der RSS-Datei: {e}")
        return False

# --- Hauptausführung ---
if __name__ == "__main__":
    zotero_items_data = fetch_zotero_items()
    if zotero_items_data is not None: # Auch leere Liste ist okay
        create_rss_feed(zotero_items_data)
    else:
        print("Feed-Generierung fehlgeschlagen, da keine Daten abgerufen werden konnten.")
