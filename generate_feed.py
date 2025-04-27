import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import re # Für Jahreszahl-Extraktion und HTML-Strip
from urllib.parse import quote, urlparse, urlunparse # Für URL-Encoding und DOI-Parsing
import html # Für HTML Entity Decoding
import logging

# --- Konfiguration ---
GROUP_ID = "5560460" # Die Zotero Gruppen ID vom IAU
API_BASE_URL = f"https://api.zotero.org/groups/{GROUP_ID}/items" # Basis-URL für Items
# MODIFIZIERT: Dateiname zurück geändert
OUTPUT_FILENAME = "zotero_rss_minimal.xml"

# RSS Channel Konfiguration
# MODIFIZIERT: Titel zurück geändert
RSS_CHANNEL_TITLE = "IAU Publications (Minimal)"
RSS_CHANNEL_LINK = "https://www.iau.uni-frankfurt.de" # Hauptlink des Instituts
# MODIFIZIERT: Beschreibung zurück geändert
RSS_CHANNEL_DESCRIPTION = "Publikationen des Instituts für Atmosphäre und Umwelt (IAU) - Minimalformat"
RSS_CHANNEL_LANGUAGE = "de-DE" # Sprache des Feeds (z.B. de-DE oder en-US)

# Zotero API Abruf Konfiguration
ZOTERO_ITEM_TYPE = "items/top" # Nur Top-Level Items
MAX_LIMIT_PER_REQUEST = 100 # Zotero API Limit pro Seite
SORT_BY = "dateAdded" # Sortierung der Items ('dateAdded', 'dateModified', 'title')
DIRECTION = "desc" # Sortierrichtung ('asc' oder 'desc')
# MODIFIZIERT: Präfix für Tags, die als Arbeitsgruppe interpretiert werden sollen (WIEDER DEAKTIVIERT)
AG_TAG_PREFIX = "AG " # Z.B. "AG Biskitz" -> Kategorie "Biskitz"

# GitHub Pages Konfiguration (für atom:link und Fallback-GUID)
# Stelle sicher, dass diese Werte korrekt sind für den finalen Feed-URL
GITHUB_USERNAME = "184467gianluca"
REPO_NAME = "institut-zotero-feed"
# MODIFIZIERT: Verwende den ursprünglichen Dateinamen im Feed-URL
FEED_URL = f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{OUTPUT_FILENAME}"
# --- Ende Konfiguration ---

# Namespace für Atom Link (wird im RSS eingebettet)
ATOM_NS = "http://www.w3.org/2005/Atom"

# Logging Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def clean_html(raw_html):
    """Entfernt HTML-Tags aus einem String."""
    if not raw_html:
        return ""
    raw_html_str = str(raw_html)
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html_str)
    return html.unescape(cleantext).strip()

def extract_year(date_str):
    """Versucht, die vierstellige Jahreszahl aus einem Datumsstring zu extrahieren."""
    if not date_str:
        return None
    date_str_val = str(date_str)
    match = re.search(r'\b(\d{4})\b', date_str_val)
    if match:
        return match.group(1)
    try:
        if isinstance(date_str, (int, float)) and 1900 < int(date_str) < 2100:
             return str(int(date_str))
        if isinstance(date_str_val, str):
             for fmt in ('%Y-%m-%d', '%Y-%m', '%Y'):
                 try:
                     dt = datetime.strptime(date_str_val, fmt)
                     return dt.strftime('%Y')
                 except ValueError:
                     continue
    except (ValueError, TypeError):
        pass
    logging.warning(f"Konnte kein Jahr aus '{date_str_val}' extrahieren.")
    return None


def format_authors(creators):
    """Formatiert die Autorenliste aus dem creators-Array, Komma-getrennt."""
    if not creators:
        return ""
    author_list = []
    if not isinstance(creators, list):
        logging.warning(f"Unerwartetes Format für 'creators': {creators}. Erwarte eine Liste.")
        return ""

    for creator in creators:
        if not isinstance(creator, dict):
            logging.warning(f"Unerwartetes Format für Creator-Eintrag: {creator}. Erwarte ein Dictionary.")
            continue

        if creator.get('creatorType') == 'author':
            last_name = str(creator.get('lastName', '')).strip()
            first_name = str(creator.get('firstName', '')).strip()
            name_str = ""
            if last_name and first_name:
                name_str = f"{last_name}, {first_name}"
            elif last_name:
                name_str = last_name
            elif first_name:
                name_str = first_name
            elif creator.get('name'):
                 name_str = str(creator['name']).strip()

            if name_str:
                author_list.append(name_str)

    return ", ".join(author_list)

def find_best_link_json(item_data):
    """Sucht den besten Link (DOI, URL) aus den JSON-Daten und kodiert ihn korrekt."""
    if not isinstance(item_data, dict):
        logging.warning(f"Unerwartetes Format für item_data in find_best_link_json: {item_data}")
        return None

    # 1. Priorität: DOI
    doi = item_data.get('DOI')
    if doi and str(doi).strip():
        doi_text = str(doi).strip()
        doi_text = re.sub(r'^(doi\s*:?\s*/*)+', '', doi_text, flags=re.IGNORECASE).strip()

        if doi_text:
            safe_doi_text = quote(doi_text, safe='/:()._-')
            if doi_text.startswith('http://doi.org/') or doi_text.startswith('https://doi.org/'):
                 try:
                    parsed = urlparse(doi_text)
                    safe_path = quote(parsed.path, safe='/:()._-')
                    scheme = parsed.scheme or 'https'
                    netloc = parsed.netloc or 'doi.org'
                    return urlunparse((scheme, netloc, safe_path, parsed.params, parsed.query, parsed.fragment))
                 except Exception as e:
                    logging.error(f"Fehler beim Parsen/Kodieren der DOI-URL '{doi_text}': {e}")
                    return f"https://doi.org/{safe_doi_text}"
            else:
                 return f"https://doi.org/{safe_doi_text}"
        else:
             logging.warning(f"DOI '{str(doi)}' war nach Bereinigung leer.")

    # 2. Priorität: URL
    url = item_data.get('url')
    if url and str(url).strip().startswith(('http://', 'https://')):
        try:
            parsed = urlparse(str(url).strip())
            safe_path = quote(parsed.path, safe='/:@&=+$,-.%')
            return urlunparse((parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, parsed.fragment))
        except Exception as e:
            logging.warning(f"Konnte URL '{url}' nicht sicher parsen/kodieren, verwende sie unverändert: {e}")
            return str(url).strip()

    logging.info(f"Kein gültiger Link (DOI/URL) gefunden für Item mit Key {item_data.get('key')}.")
    return None

def get_categories_json(item_data, year):
    """Extrahiert Kategorien (Jahr) aus den JSON-Daten. AG-Tags sind deaktiviert."""
    categories = []
    if not isinstance(item_data, dict):
        logging.warning(f"Unerwartetes Format für item_data in get_categories_json: {item_data}")
        return categories

    # 1. Jahreszahl hinzufügen (nur wenn gültig)
    if year and str(year).isdigit() and len(str(year)) == 4:
        categories.append(str(year))

    # 2. Arbeitsgruppen-Tags hinzufügen (WIEDER DEAKTIVIERT)
    #    -> Um dies zu aktivieren, entfernen Sie die Kommentarzeichen (#)
    #       in den folgenden Zeilen, sobald die Tags in Zotero existieren.
    # ag_found = False
    # tags = item_data.get('tags', [])
    # if isinstance(tags, list):
    #     for tag_info in tags:
    #         if isinstance(tag_info, dict) and 'tag' in tag_info:
    #             tag = tag_info.get('tag')
    #             if tag and isinstance(tag, str) and tag.startswith(AG_TAG_PREFIX):
    #                 ag_name = tag[len(AG_TAG_PREFIX):].strip()
    #                 if ag_name: # Nur hinzufügen, wenn nach dem Präfix noch Text übrig ist
    #                     categories.append(ag_name)
    #                     ag_found = True
    #                     logging.debug(f"Arbeitsgruppen-Tag gefunden: '{tag}' -> Kategorie: '{ag_name}' für Item {item_data.get('key')}")
    #                 else:
    #                     logging.warning(f"AG-Tag '{tag}' für Item {item_data.get('key')} ist nach Präfix leer.")

    # 3. AG-Leiter: Kann hier nicht automatisch ermittelt werden.

    return list(set(categories)) # Duplikate entfernen

def fetch_zotero_items():
    """Holt alle Einträge von Zotero und extrahiert die benötigten Felder."""
    all_items_data = []
    start = 0
    total_results = None
    fetch_url = f"https://api.zotero.org/groups/{GROUP_ID}/{ZOTERO_ITEM_TYPE}"

    logging.info("Starte Abruf von Zotero (JSON Format)...")

    while True:
        params = {
            'format': 'json',
            'sort': SORT_BY,
            'direction': DIRECTION,
            'limit': MAX_LIMIT_PER_REQUEST,
            'start': start
        }
        try:
            logging.info(f"Rufe Einträge ab: Start={start}, Limit={MAX_LIMIT_PER_REQUEST}, URL={fetch_url}")
            headers = {'Zotero-API-Version': '3'}
            response = requests.get(fetch_url, params=params, headers=headers, timeout=120)

            if response.status_code == 404:
                 logging.error(f"Fehler: Zotero Gruppe oder Endpunkt nicht gefunden (404 Not Found). URL: {response.url}")
                 return None
            elif response.status_code == 403:
                 logging.error(f"Fehler: Zugriff auf Zotero Gruppe verweigert (403 Forbidden). Ist die Gruppe öffentlich oder benötigen Sie einen API Key? URL: {response.url}")
                 return None
            elif response.status_code == 429:
                 logging.error(f"Fehler: Zu viele Anfragen an die Zotero API (429 Too Many Requests). Bitte warten und erneut versuchen. URL: {response.url}")
                 return None
            response.raise_for_status()

            if total_results is None and 'Total-Results' in response.headers:
                try:
                    total_results = int(response.headers['Total-Results'])
                    logging.info(f"Gesamtzahl der Einträge laut API: {total_results}")
                except ValueError:
                    logging.warning(f"Konnte 'Total-Results' Header nicht als Zahl interpretieren: {response.headers['Total-Results']}")
                    total_results = -1

            try:
                items_json = response.json()
            except requests.exceptions.JSONDecodeError as json_e:
                logging.error(f"Fehler beim Parsen der JSON-Antwort von Zotero: {json_e}")
                logging.error(f"Empfangene Antwort (erste 500 Zeichen): {response.text[:500]}")
                break

            if not isinstance(items_json, list):
                logging.error(f"Unerwartete Antwort von Zotero API: Erwartete eine Liste, bekam aber Typ {type(items_json)}. Antwort: {items_json}")
                break

            if not items_json:
                logging.info("Keine weiteren Einträge gefunden (leere JSON-Liste).")
                break

            logging.info(f"{len(items_json)} Einträge auf dieser Seite gefunden.")

            for item_index, item in enumerate(items_json):
                item_key_for_log = "Unbekannt"
                try:
                    if not isinstance(item, dict):
                        logging.warning(f"Eintrag #{start + item_index}: Unerwartetes Format, überspringe: {item}")
                        continue

                    item_key_for_log = item.get('key', 'Nicht vorhanden')
                    item_data = item.get('data', {})
                    if not isinstance(item_data, dict):
                         logging.warning(f"Eintrag {item_key_for_log}: Unerwartetes 'data'-Format, überspringe.")
                         continue

                    # --- Datenextraktion ---
                    zotero_key = item.get('key') or item_data.get('key')
                    title = clean_html(item_data.get('title', ''))
                    creators = item_data.get('creators', [])
                    date_str = item_data.get('date')
                    journal_abbr = clean_html(item_data.get('journalAbbreviation'))
                    pub_title = clean_html(item_data.get('publicationTitle'))
                    volume = str(item_data.get('volume', '')).strip()

                    year = extract_year(date_str)
                    authors_formatted = format_authors(creators)
                    journal_display = journal_abbr if journal_abbr else pub_title
                    best_link = find_best_link_json(item_data)
                    # MODIFIZIERT: Ruft jetzt nur noch Jahr als Kategorie ab
                    categories = get_categories_json(item_data, year)

                    if not title:
                        logging.warning(f"Eintrag {item_key_for_log}: Titel ist leer, wird übersprungen.")
                        continue

                    all_items_data.append({
                        'zotero_key': zotero_key,
                        'authors': authors_formatted,
                        'year': year,
                        'title': title,
                        'journal': journal_display,
                        'volume': volume,
                        'link': best_link,
                        'categories': categories,
                    })

                except Exception as item_e:
                    logging.error(f"Fehler beim Verarbeiten von Item #{start + item_index} (Key: {item_key_for_log}): {item_e}", exc_info=True)
                    continue


            start += len(items_json)

            if total_results is not None and total_results != -1 and start >= total_results:
                logging.info("Alle erwarteten Einträge abgerufen.")
                break
            if len(items_json) < MAX_LIMIT_PER_REQUEST:
                logging.info("Weniger Einträge als Limit erhalten, nehme an, das waren die letzten.")
                break

        except requests.exceptions.RequestException as e:
            logging.error(f"Netzwerk- oder HTTP-Fehler bei API-Abruf: {e}")
            logging.info("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break
        except Exception as e:
            logging.error(f"Unerwarteter Fehler während des API-Abrufs oder der Paginierungslogik: {e}", exc_info=True)
            error_context = response.text[:500] if 'response' in locals() and hasattr(response, 'text') else "Keine Antwortdaten verfügbar"
            logging.error(f"Fehlerhafter Antwort/Kontext (erste 500 Zeichen): {error_context}")
            logging.info("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break

    logging.info(f"Insgesamt {len(all_items_data)} Einträge von Zotero erfolgreich für den Feed vorbereitet.")
    return all_items_data

def create_rss_feed(items_data):
    """Erstellt den RSS Feed im minimalen Format mit Boss-Titelstruktur."""
    if not items_data:
        logging.warning("Keine Einträge zum Erstellen des Feeds vorhanden.")
        return None

    ET.register_namespace('atom', ATOM_NS)
    rss = ET.Element('rss', version="2.0")
    rss.set(f'xmlns:atom', ATOM_NS)
    channel = ET.SubElement(rss, 'channel')

    # Channel-Metadaten (zurück auf Minimal)
    ET.SubElement(channel, 'title').text = RSS_CHANNEL_TITLE
    ET.SubElement(channel, 'link').text = RSS_CHANNEL_LINK
    ET.SubElement(channel, 'description').text = RSS_CHANNEL_DESCRIPTION
    if RSS_CHANNEL_LANGUAGE:
        ET.SubElement(channel, 'language').text = RSS_CHANNEL_LANGUAGE

    now_rfc822 = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    ET.SubElement(channel, 'lastBuildDate').text = now_rfc822
    ET.SubElement(channel, 'pubDate').text = now_rfc822
    # MODIFIZIERT: Generator-Text zurück geändert
    ET.SubElement(channel, 'generator').text = "Zotero Feed Generator Script (Minimal)"

    # Atom Link (self)
    atom_link_attrib = { 'href': FEED_URL, 'rel': 'self', 'type': 'application/rss+xml' }
    ET.SubElement(channel, f'{{{ATOM_NS}}}link', attrib=atom_link_attrib)

    # Einträge hinzufügen
    item_count = 0
    for item_data in items_data:
        item = ET.SubElement(channel, 'item')

        # --- <title> zusammenbauen (Boss-Format beibehalten) ---
        title_parts = []
        authors = item_data.get('authors')
        year = item_data.get('year')
        title = item_data.get('title', '[Titel nicht verfügbar]')
        journal = item_data.get('journal')
        volume = item_data.get('volume')

        if authors:
            title_parts.append(authors)
        if year:
            title_parts.append(f"({year})")
        title_parts.append(title)
        if journal:
            title_parts.append(journal)
        if volume:
            title_parts.append(volume)

        rss_item_title = ""
        for i, part in enumerate(title_parts):
            part_str = str(part).strip()
            if not part_str: continue

            if i == 0:
                rss_item_title += part_str
            elif part_str.startswith('('):
                rss_item_title += f" {part_str}"
            else:
                if rss_item_title and not rss_item_title.endswith(')'):
                     rss_item_title += "."
                rss_item_title += f" {part_str}"

        ET.SubElement(item, 'title').text = rss_item_title.strip()

        # --- <link> hinzufügen ---
        rss_link = item_data.get('link')
        if rss_link:
            ET.SubElement(item, 'link').text = rss_link

        # --- <category> hinzufügen (nur Jahr) ---
        rss_categories = item_data.get('categories', [])
        if rss_categories:
             for category_name in rss_categories:
                 if category_name:
                     ET.SubElement(item, 'category').text = str(category_name)

        # --- <guid> hinzufügen ---
        guid_text = item_data.get('zotero_key')
        guid_is_permalink = "false"

        if not guid_text:
            guid_text = rss_link
            if guid_text:
                guid_is_permalink = "true"
            else:
                guid_text = rss_item_title
                guid_is_permalink = "false"
                logging.warning(f"Item '{rss_item_title[:50]}...' hat keine GUID (weder Key noch Link), verwende Titel.")

        guid_elem = ET.SubElement(item, 'guid', isPermaLink=guid_is_permalink)
        guid_elem.text = str(guid_text)

        # --- <pubDate> hinzufügen ---
        ET.SubElement(item, 'pubDate').text = now_rfc822

        item_count += 1

    # XML-Baum speichern
    try:
        # ET.indent(rss, space="  ", level=0)
        tree = ET.ElementTree(rss)
        tree.write(OUTPUT_FILENAME, encoding="utf-8", xml_declaration=True, method='xml')
        logging.info(f"{item_count} Einträge erfolgreich in '{OUTPUT_FILENAME}' geschrieben.")
        return True
    except Exception as e:
        logging.error(f"Fehler beim Schreiben der RSS-Datei: {e}")
        return False

# --- Hauptausführung ---
if __name__ == "__main__":
    logging.info("Starte Zotero RSS Feed Generator Skript (Minimal - Boss Title)...")
    zotero_items_data = fetch_zotero_items()
    if zotero_items_data is not None and len(zotero_items_data) > 0:
        if create_rss_feed(zotero_items_data):
             logging.info("Skript erfolgreich beendet.")
        else:
             logging.error("Feed-Generierung fehlgeschlagen beim Schreiben der Datei.")
    elif zotero_items_data is None:
         logging.error("Feed-Generierung fehlgeschlagen, da keine Daten abgerufen werden konnten (API-Fehler oder Berechtigungsproblem).")
    else:
         logging.warning("Keine verarbeitbaren Einträge von Zotero gefunden oder alle übersprungen. Feed-Datei wird nicht erstellt/aktualisiert.")

