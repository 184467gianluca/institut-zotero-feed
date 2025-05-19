import requests # Für HTTP-Anfragen an die Zotero API
import xml.etree.ElementTree as ET # Zum Erstellen und Bearbeiten von XML-Dokumenten (RSS-Feed)
from datetime import datetime, timezone # Für Datums- und Zeitoperationen, insbesondere für Zeitstempel im RSS-Feed
import re # Für reguläre Ausdrücke, z.B. zum Extrahieren von Jahreszahlen und zum Entfernen von HTML-Tags
from urllib.parse import quote, urlparse, urlunparse # Für URL-Encoding und -Parsing, um sichere und korrekte URLs zu erstellen
import html # Für das Dekodieren von HTML-Entitäten (z.B. &amp; zu &)
import logging # Für das Protokollieren von Informationen, Warnungen und Fehlern während der Skriptausführung

# --- Globale Konfiguration (Institutsebene) ---
GROUP_ID = "5560460" # Die Zotero Gruppen ID vom IAU
DEFAULT_AG_OUTPUT_SUFFIX = "_zotero_rss.xml" # Standard-Suffix für AG-Dateinamen
MAIN_FEED_FILENAME = "zotero_rss_minimal.xml" # Dateiname für den Haupt-Feed des Instituts

# RSS Channel Konfiguration (Basis, gilt für alle Feeds, wenn nicht spezifisch überschrieben)
RSS_CHANNEL_LINK = "https://www.iau.uni-frankfurt.de" # Hauptlink des Instituts
RSS_CHANNEL_LANGUAGE = "de-DE" # Sprache des Feeds

# Zotero API Abruf Konfiguration (allgemein gültig)
ZOTERO_ITEM_TYPE = "items/top" # Nur Top-Level Items (keine Anhänge oder Notizen, die direkt untergeordnet sind)
MAX_LIMIT_PER_REQUEST = 100 # Zotero API Limit pro Seite (üblicherweise max. 100)
SORT_BY = "dateAdded" # Sortierung der Items ('dateAdded', 'dateModified', 'title')
DIRECTION = "desc" # Sortierrichtung ('asc' für aufsteigend, 'desc' für absteigend)
# AG_TAG_PREFIX = "AG " # Präfix für Tags, die als Arbeitsgruppe interpretiert werden sollen (DEAKTIVIERT, da AGs jetzt über Collections laufen)

# GitHub Pages Konfiguration (Basis für die Feed-URL-Konstruktion)
GITHUB_USERNAME = "184467gianluca"
REPO_NAME = "institut-zotero-feed"
# --- Ende Globale Konfiguration ---

# XML-Namespace für Atom Link (für den selbstreferenziellen Link im Feed)
ATOM_NS = "http://www.w3.org/2005/Atom"

# Logging Konfiguration
# Legt das minimale Log-Level (INFO) und das Format der Log-Nachrichten fest.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# === Konfiguration der einzelnen Arbeitsgruppen ===
# Hier die Daten für jede AG eintragen, die einen eigenen Feed erhalten soll:
# "key": Der Collection Key aus der Zotero URL (z.B. CCHBIWUJ für AG Schmidli)
# "label": Der Anzeigename der AG (z.B. "AG Schmidli") - wird in Titeln und Log-Meldungen verwendet.
# "prefix": Ein Präfix für den Dateinamen des AG-spezifischen RSS-Feeds (z.B. "AG_Schmidli").
AG_CONFIGURATIONS = [
    {"key": "QBAUQQNT", "label": "AG Achatz", "prefix": "AG_Achatz"},
    {"key": "D4M39XHF", "label": "AG Ahrens", "prefix": "AG_Ahrens"},
    {"key": "LBA3HESK", "label": "AG Curtius", "prefix": "AG_Curtius"},
    {"key": "TMY9JK3J", "label": "AG Engel", "prefix": "AG_Engel"},
    {"key": "C59ZK2Z2", "label": "AG Possner", "prefix": "AG_Possner"},
    {"key": "CCHBIWUJ", "label": "AG Schmidli", "prefix": "AG_Schmidli"},
    {"key": "2664JL92", "label": "AG Vogel", "prefix": "AG_Vogel"},
    # Weitere AGs können hier nach dem gleichen Schema hinzugefügt werden.
]
# === Ende Arbeitsgruppen-Konfiguration ===


def clean_html(raw_html):
    """Entfernt HTML-Tags aus einem String und dekodiert HTML-Entitäten."""
    if not raw_html: # Wenn die Eingabe leer oder None ist, leeren String zurückgeben
        return ""
    raw_html_str = str(raw_html) # Sicherstellen, dass die Eingabe ein String ist
    cleanr = re.compile('<.*?>') # Regulärer Ausdruck, um alle HTML-Tags zu finden
    cleantext = re.sub(cleanr, '', raw_html_str) # HTML-Tags entfernen
    return html.unescape(cleantext).strip() # HTML-Entitäten dekodieren und Leerzeichen am Rand entfernen

def extract_year(date_str):
    """Versucht, die vierstellige Jahreszahl aus einem Datumsstring zu extrahieren.
    Behandelt verschiedene mögliche Datumsformate aus Zotero.
    """
    if not date_str: # Wenn die Eingabe leer oder None ist, None zurückgeben
        return None
    date_str_val = str(date_str) # Sicherstellen, dass die Eingabe ein String ist
    match = re.search(r'\b(\d{4})\b', date_str_val) # Sucht nach einer vierstelligen Zahl
    if match: # Wenn eine vierstellige Zahl gefunden wurde
        return match.group(1) # Gibt die gefundene Jahreszahl zurück
    # Fallback-Versuche, falls der Regex nicht erfolgreich war
    try:
        # Prüft, ob die Eingabe eine Zahl ist, die einem plausiblen Jahr entspricht
        if isinstance(date_str, (int, float)) and 1900 < int(date_str) < 2100:
            return str(int(date_str))
        # Versucht, den String mit verschiedenen Datumsformaten zu parsen
        if isinstance(date_str_val, str):
            for fmt in ('%Y-%m-%d', '%Y-%m', '%Y'): # Gängige Formate
                try:
                    dt = datetime.strptime(date_str_val, fmt) # String parsen
                    return dt.strftime('%Y') # Jahr extrahieren und zurückgeben
                except ValueError:
                    continue # Nächstes Format versuchen, wenn aktuelles fehlschlägt
    except (ValueError, TypeError): # Fehler bei Konvertierungsversuchen abfangen
        pass # Fehler ignorieren und fortfahren
    logging.warning(f"Konnte kein Jahr aus '{date_str_val}' extrahieren.") # Warnung loggen, wenn kein Jahr gefunden wurde
    return None # Kein Jahr gefunden

def format_authors(creators):
    """Formatiert die Autorenliste aus dem 'creators'-Array von Zotero.
    Autoren werden als "Nachname, Vorname" formatiert und mit Semikolon getrennt.
    """
    if not creators: # Wenn keine Autorenliste vorhanden ist, leeren String zurückgeben
        return ""
    author_list = [] # Liste für formatierte Autorennamen
    if not isinstance(creators, list): # Prüfen, ob 'creators' eine Liste ist
        logging.warning(f"Unerwartetes Format für 'creators': {creators}. Erwarte eine Liste.")
        return ""
    for creator in creators: # Jeden Eintrag in der Autorenliste durchgehen
        if not isinstance(creator, dict): # Prüfen, ob der Eintrag ein Dictionary ist
            logging.warning(f"Unerwartetes Format für Creator-Eintrag: {creator}. Erwarte ein Dictionary.")
            continue # Nächsten Eintrag bearbeiten
        if creator.get('creatorType') == 'author': # Nur Autoren berücksichtigen
            last_name = str(creator.get('lastName', '')).strip() # Nachname extrahieren
            first_name = str(creator.get('firstName', '')).strip() # Vorname extrahieren
            name_str = "" # String für den formatierten Namen
            # Namen zusammensetzen
            if last_name and first_name:
                name_str = f"{last_name}, {first_name}"
            elif last_name:
                name_str = last_name
            elif first_name:
                name_str = first_name
            elif creator.get('name'): # Fallback für institutionelle Autoren o.ä.
                name_str = str(creator['name']).strip()
            if name_str: # Wenn ein Name vorhanden ist
                author_list.append(name_str) # Zur Liste hinzufügen
    return "; ".join(author_list) # Alle formatierten Namen mit Semikolon verbinden

def find_best_link_json(item_data):
    """Sucht den besten Link (DOI, dann URL) aus den JSON-Daten eines Zotero-Items.
    Der Link wird URL-kodiert zurückgegeben.
    """
    if not isinstance(item_data, dict): # Prüfen, ob item_data ein Dictionary ist
        logging.warning(f"Unerwartetes Format für item_data in find_best_link_json: {item_data}")
        return None
    # 1. Priorität: DOI
    doi = item_data.get('DOI')
    if doi and str(doi).strip(): # Wenn DOI vorhanden und nicht leer
        doi_text = str(doi).strip()
        doi_text = re.sub(r'^(doi\s*:?\s*/*)+', '', doi_text, flags=re.IGNORECASE).strip() # DOI-Präfixe entfernen
        if doi_text: # Wenn nach Bereinigung noch ein DOI-Text übrig ist
            safe_doi_text = quote(doi_text, safe='/:()._-') # URL-Encoding des DOI-Texts
            if doi_text.startswith('http://doi.org/') or doi_text.startswith('https://doi.org/'): # Wenn DOI schon eine URL ist
                try:
                    parsed = urlparse(doi_text) # URL parsen
                    safe_path = quote(parsed.path, safe='/:()._-') # Pfad sicher kodieren
                    scheme = parsed.scheme or 'https' # Schema sicherstellen
                    netloc = parsed.netloc or 'doi.org' # Netlocation sicherstellen
                    return urlunparse((scheme, netloc, safe_path, parsed.params, parsed.query, parsed.fragment)) # URL wieder zusammensetzen
                except Exception as e:
                    logging.error(f"Fehler beim Parsen/Kodieren der DOI-URL '{doi_text}': {e}")
                    return f"https://doi.org/{safe_doi_text}" # Fallback
            else: # Wenn DOI nur der Identifier ist
                return f"https://doi.org/{safe_doi_text}" # Standard-DOI-URL erstellen
        else:
            logging.warning(f"DOI '{str(doi)}' war nach Bereinigung leer.")
    # 2. Priorität: URL
    url = item_data.get('url')
    if url and str(url).strip().startswith(('http://', 'https://')): # Wenn URL vorhanden und gültig
        try:
            parsed = urlparse(str(url).strip()) # URL parsen
            safe_path = quote(parsed.path, safe='/:@&=+$,-.%') # Pfad sicher kodieren
            return urlunparse((parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, parsed.fragment)) # URL wieder zusammensetzen
        except Exception as e:
            logging.warning(f"Konnte URL '{url}' nicht sicher parsen/kodieren, verwende sie unverändert: {e}")
            return str(url).strip() # Fallback: ursprüngliche URL (bereinigt)
    logging.info(f"Kein gültiger Link (DOI/URL) gefunden für Item mit Key {item_data.get('key')}.")
    return None # Kein Link gefunden

def get_categories_json(item_data, year):
    """Extrahiert Kategorien für einen RSS-Eintrag. Aktuell nur das Jahr."""
    categories = []
    if not isinstance(item_data, dict):
        logging.warning(f"Unerwartetes Format für item_data in get_categories_json: {item_data}")
        return categories
    if year and str(year).isdigit() and len(str(year)) == 4: # Wenn 'year' eine gültige vierstellige Zahl ist
        categories.append(str(year)) # Jahr als Kategorie hinzufügen
    # Die Logik für AG-Tags (AG_TAG_PREFIX) ist hier weiterhin deaktiviert,
    # da die AG-Zuordnung jetzt über Zotero-Collections erfolgt.
    return list(set(categories)) # Duplikate entfernen und Liste zurückgeben

def fetch_zotero_items(group_id_param, item_type_param, sort_by_param, direction_param, limit_param,
                       collection_key_override=None, ag_name_label_override="Gesamtinstitut"):
    """Holt alle Einträge (Items) von Zotero.
    Kann entweder alle Items der Gruppe oder Items einer spezifischen Collection abrufen.
    """
    all_items_data = [] # Liste für die gesammelten und verarbeiteten Item-Daten
    start = 0 # Startindex für die Paginierung
    total_results = None # Gesamtzahl der von der API gemeldeten Ergebnisse

    # URL-Konstruktion: Abhängig davon, ob eine spezifische Collection oder die gesamte Gruppe abgefragt wird
    if collection_key_override:
        # URL für eine spezifische Collection (Arbeitsgruppe)
        fetch_url = f"https://api.zotero.org/groups/{group_id_param}/collections/{collection_key_override}/{item_type_param}"
        logging.info(f"Starte Abruf von Zotero für {ag_name_label_override} (Collection Key: {collection_key_override})...")
    else:
        # URL für die gesamte Gruppe (Haupt-Feed)
        fetch_url = f"https://api.zotero.org/groups/{group_id_param}/{item_type_param}"
        logging.info(f"Starte Abruf von Zotero für {ag_name_label_override} (gesamte Gruppe)...")

    # Schleife für Paginierung, um alle Einträge zu holen
    while True:
        params = { # Parameter für die API-Anfrage
            'format': 'json',
            'sort': sort_by_param,
            'direction': direction_param,
            'limit': limit_param,
            'start': start
        }
        try:
            logging.info(f"Rufe Einträge ab ({ag_name_label_override}): Start={start}, Limit={limit_param}, URL={fetch_url}")
            headers = {'Zotero-API-Version': '3'} # Notwendiger Header für die Zotero API
            response = requests.get(fetch_url, params=params, headers=headers, timeout=120) # API-Anfrage

            # Fehlerbehandlung für HTTP-Statuscodes
            if response.status_code == 404:
                logging.error(f"Fehler ({ag_name_label_override}): Zotero Gruppe/Collection oder Endpunkt nicht gefunden (404). URL: {response.url}")
                return None # Abbruch, da keine Daten abgerufen werden können
            elif response.status_code == 403:
                logging.error(f"Fehler ({ag_name_label_override}): Zugriff auf Zotero Gruppe/Collection verweigert (403). URL: {response.url}")
                return None
            elif response.status_code == 429:
                logging.error(f"Fehler ({ag_name_label_override}): Zu viele Anfragen an die Zotero API (429). URL: {response.url}")
                return None
            response.raise_for_status() # Löst Fehler für andere 4xx/5xx Statuscodes aus

            # Gesamtzahl der Ergebnisse aus Header lesen (nur einmal)
            if total_results is None and 'Total-Results' in response.headers:
                try:
                    total_results = int(response.headers['Total-Results'])
                    logging.info(f"Gesamtzahl der Einträge laut API für {ag_name_label_override}: {total_results}")
                except ValueError:
                    logging.warning(f"Konnte 'Total-Results' Header nicht als Zahl interpretieren ({ag_name_label_override}): {response.headers['Total-Results']}")
                    total_results = -1 # Ungültiger Wert
            
            # JSON-Antwort parsen
            try:
                items_json = response.json()
            except requests.exceptions.JSONDecodeError as json_e:
                logging.error(f"Fehler beim Parsen der JSON-Antwort von Zotero ({ag_name_label_override}): {json_e}")
                logging.error(f"Empfangene Antwort (erste 500 Zeichen): {response.text[:500]}")
                break # Schleife abbrechen
            
            # Überprüfen, ob die Antwort eine Liste ist
            if not isinstance(items_json, list):
                logging.error(f"Unerwartete Antwort von Zotero API ({ag_name_label_override}): Erwartete Liste, bekam {type(items_json)}. Antwort: {items_json}")
                break # Schleife abbrechen
            
            # Wenn keine Items mehr zurückkommen, Ende der Paginierung
            if not items_json:
                logging.info(f"Keine weiteren Einträge für {ag_name_label_override} gefunden (leere JSON-Liste).")
                break # Schleife abbrechen
            
            logging.info(f"{len(items_json)} Einträge auf dieser Seite für {ag_name_label_override} gefunden.")

            # Jedes Item in der aktuellen Antwort verarbeiten
            for item_index, item in enumerate(items_json):
                item_key_for_log = "Unbekannt" # Für Log-Meldungen bei Fehlern
                try:
                    if not isinstance(item, dict): # Item-Struktur prüfen
                        logging.warning(f"Eintrag #{start + item_index} ({ag_name_label_override}): Unerwartetes Format, überspringe: {item}")
                        continue
                    item_key_for_log = item.get('key', 'Nicht vorhanden')
                    item_data = item.get('data', {}) # Die eigentlichen Metadaten sind im 'data'-Objekt
                    if not isinstance(item_data, dict): # 'data'-Objekt-Struktur prüfen
                        logging.warning(f"Eintrag {item_key_for_log} ({ag_name_label_override}): Unerwartetes 'data'-Format, überspringe.")
                        continue
                    
                    # Datenextraktion für das aktuelle Item
                    zotero_key = item.get('key') or item_data.get('key')
                    title = clean_html(item_data.get('title', '')) # Titel des Papers
                    creators = item_data.get('creators', []) # Autorenliste
                    date_str = item_data.get('date') # Datumsstring
                    journal_abbr = clean_html(item_data.get('journalAbbreviation')) # Journal-Abkürzung
                    pub_title = clean_html(item_data.get('publicationTitle')) # Voller Journal-/Buch-Titel
                    volume = str(item_data.get('volume', '')).strip() # Volume
                    
                    year = extract_year(date_str) # Jahr extrahieren
                    authors_formatted = format_authors(creators) # Autoren formatieren
                    journal_display = journal_abbr if journal_abbr else pub_title # Journalnamen auswählen
                    best_link = find_best_link_json(item_data) # Besten Link finden
                    categories = get_categories_json(item_data, year) # Kategorien extrahieren

                    if not title: # Item überspringen, wenn kein Titel vorhanden ist
                        logging.warning(f"Eintrag {item_key_for_log} ({ag_name_label_override}): Titel ist leer, wird übersprungen.")
                        continue
                    
                    # Aufbereitete Daten zur Gesamtliste hinzufügen
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
                except Exception as item_e: # Fehler bei der Verarbeitung eines einzelnen Items abfangen
                    logging.error(f"Fehler beim Verarbeiten von Item #{start + item_index} ({ag_name_label_override}, Key: {item_key_for_log}): {item_e}", exc_info=True)
                    continue # Mit dem nächsten Item fortfahren
            
            start += len(items_json) # Startindex für nächste Paginierungsseite erhöhen
            
            # Paginierung beenden, wenn alle erwarteten Ergebnisse abgerufen wurden
            if total_results is not None and total_results != -1 and start >= total_results:
                logging.info(f"Alle erwarteten Einträge für {ag_name_label_override} abgerufen.")
                break
            # Paginierung beenden, wenn weniger Items als das Limit zurückkamen (Indikator für letzte Seite)
            if len(items_json) < limit_param: 
                logging.info(f"Weniger Einträge als Limit für {ag_name_label_override} erhalten, nehme an, das waren die letzten.")
                break
        except requests.exceptions.RequestException as e: # Netzwerkfehler etc.
            logging.error(f"Netzwerk- oder HTTP-Fehler bei API-Abruf für {ag_name_label_override}: {e}")
            logging.info("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break # Schleife abbrechen, aber bisher gesammelte Daten behalten
        except Exception as e: # Andere unerwartete Fehler
            logging.error(f"Unerwarteter Fehler während des API-Abrufs für {ag_name_label_override}: {e}", exc_info=True)
            error_context = response.text[:500] if 'response' in locals() and hasattr(response, 'text') else "Keine Antwortdaten verfügbar"
            logging.error(f"Fehlerhafter Antwort/Kontext (erste 500 Zeichen): {error_context}")
            logging.info("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break # Schleife abbrechen
            
    logging.info(f"Insgesamt {len(all_items_data)} Einträge von Zotero für {ag_name_label_override} erfolgreich für den Feed vorbereitet.")
    return all_items_data

def create_rss_feed(items_data, output_filename_param, channel_title_param, channel_link_param,
                    channel_description_param, channel_language_param, feed_url_atom_param, generator_label_param):
    """Erstellt den RSS Feed im XML-Format aus den vorbereiteten Item-Daten.
    Die Parameter steuern die Metadaten des Feeds und den Dateinamen.
    """
    if not items_data: # Wenn keine Items zum Verarbeiten vorhanden sind
        logging.warning(f"Keine Einträge für {generator_label_param} zum Erstellen des Feeds '{output_filename_param}' vorhanden.")
        return None # Kein Feed wird erstellt
    
    ET.register_namespace('atom', ATOM_NS) # Atom-Namespace für <atom:link> registrieren
    rss = ET.Element('rss', version="2.0") # RSS-Wurzelelement
    channel = ET.SubElement(rss, 'channel') # Channel-Element

    # Channel-Metadaten setzen (werden als Parameter übergeben)
    ET.SubElement(channel, 'title').text = channel_title_param
    ET.SubElement(channel, 'link').text = channel_link_param
    ET.SubElement(channel, 'description').text = channel_description_param
    if channel_language_param:
        ET.SubElement(channel, 'language').text = channel_language_param
    
    now_rfc822 = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT') # Aktuelles Datum im RFC 822 Format
    ET.SubElement(channel, 'lastBuildDate').text = now_rfc822 # Wann der Feed zuletzt gebaut wurde
    ET.SubElement(channel, 'pubDate').text = now_rfc822 # Veröffentlichungsdatum des Feeds
    ET.SubElement(channel, 'generator').text = f"Zotero Feed Generator Script ({generator_label_param})" # Generator-Info

    # Selbstreferenzieller Atom-Link zum Feed
    atom_link_attrib = { 'href': feed_url_atom_param, 'rel': 'self', 'type': 'application/rss+xml' }
    ET.SubElement(channel, f'{{{ATOM_NS}}}link', attrib=atom_link_attrib)

    item_count = 0 # Zähler für die Items im Feed
    # Jedes aufbereitete Item durchgehen und als RSS-Item hinzufügen
    for item_data in items_data:
        item = ET.SubElement(channel, 'item') # Neues <item>-Element
        
        # Titel des RSS-Items zusammensetzen (Autoren (Jahr) Titel. Journal. Volume)
        title_parts = []
        authors = item_data.get('authors')
        year = item_data.get('year')
        paper_title = item_data.get('title', '[Titel nicht verfügbar]') # Eigentlicher Titel des Papers
        journal_name = item_data.get('journal') # Journal/Veröffentlichungsort
        volume_number = item_data.get('volume') # Volume
        
        # Teile in der gewünschten Reihenfolge hinzufügen
        if authors: title_parts.append(authors)
        if year: title_parts.append(f"({year})")
        title_parts.append(paper_title)
        if journal_name: title_parts.append(journal_name)
        if volume_number: title_parts.append(volume_number)
        
        # Teile zu einem String verbinden
        rss_item_title = ""
        for i, part in enumerate(title_parts):
            part_str = str(part).strip()
            if not part_str: continue
            if i == 0: # Erster Teil
                rss_item_title += part_str
            elif part_str.startswith('('): # Jahr in Klammern
                rss_item_title += f" {part_str}"
            else: # Andere Teile
                if rss_item_title and not rss_item_title.strip().endswith(')'):
                    rss_item_title += "." # Punkt als Trenner, wenn vorher nicht Klammer
                rss_item_title += f" {part_str}"
        ET.SubElement(item, 'title').text = rss_item_title.strip()

        # Link des Items
        rss_link = item_data.get('link')
        if rss_link:
            ET.SubElement(item, 'link').text = rss_link

        # Kategorien des Items (aktuell nur Jahr)
        rss_categories = item_data.get('categories', [])
        if rss_categories:
            for category_name in rss_categories:
                if category_name:
                    ET.SubElement(item, 'category').text = str(category_name)

        # GUID (Globally Unique Identifier) für das Item
        guid_text = item_data.get('zotero_key') # Primär Zotero-Key verwenden
        guid_is_permalink = "false"
        if not guid_text: # Fallback, wenn kein Zotero-Key vorhanden
            guid_text = rss_link # Link als GUID
            if guid_text:
                guid_is_permalink = "true" # Link ist ein Permalink
            else: # Letzter Fallback: Titel als GUID
                guid_text = rss_item_title
                guid_is_permalink = "false"
                logging.warning(f"Item '{rss_item_title[:50]}...' ({generator_label_param}) hat keine GUID, verwende Titel.")
        guid_elem = ET.SubElement(item, 'guid', isPermaLink=guid_is_permalink)
        guid_elem.text = str(guid_text)

        # Veröffentlichungsdatum des Items (hier: Generierungsdatum des Feeds)
        ET.SubElement(item, 'pubDate').text = now_rfc822
        item_count += 1
        
    # RSS-Feed in Datei schreiben
    try:
        ET.indent(rss, space="  ", level=0) # XML formatieren (Einrücken), benötigt Python 3.9+
        tree = ET.ElementTree(rss)
        # Dateiname wird als Parameter übergeben
        tree.write(output_filename_param, encoding="utf-8", xml_declaration=True, method='xml')
        logging.info(f"{item_count} Einträge für {generator_label_param} erfolgreich formatiert und in '{output_filename_param}' geschrieben.")
        return True # Erfolg signalisieren
    except AttributeError: # Fallback für Python < 3.9 (ET.indent nicht verfügbar)
        logging.warning(f"ET.indent() nicht verfügbar für {generator_label_param} (Python 3.9+ nötig). XML wird ohne Einrückung geschrieben.")
        tree = ET.ElementTree(rss)
        tree.write(output_filename_param, encoding="utf-8", xml_declaration=True, method='xml')
        logging.info(f"{item_count} Einträge für {generator_label_param} erfolgreich (unformatiert) in '{output_filename_param}' geschrieben.")
        return True # Erfolg signalisieren (Datei wurde geschrieben)
    except Exception as e: # Andere Fehler beim Schreiben der Datei
        logging.error(f"Fehler beim Schreiben der RSS-Datei '{output_filename_param}' für {generator_label_param}: {e}")
        return False # Fehler signalisieren

# --- Hauptausführung des Skripts ---
if __name__ == "__main__":
    logging.info("=== Starte Zotero RSS Feed Generator für Gesamtinstitut und Arbeitsgruppen ===")
    
    # 1. Generiere den Haupt-Feed für das gesamte Institut
    # ----------------------------------------------------
    logging.info("--- Generiere Haupt-Feed (Gesamtinstitut) ---")
    main_feed_label = "Gesamtinstitut (Minimal)" # Label für Log-Meldungen etc.
    main_feed_title = "IAU Publikationen (Minimal)" # Titel für den RSS-Channel
    main_feed_description = "Publikationen des Instituts für Atmosphäre und Umwelt (IAU) - Minimalformat" # Beschreibung
    # URL, unter der der Haupt-Feed später erreichbar sein wird (für atom:link)
    main_feed_atom_url = f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{MAIN_FEED_FILENAME}"

    # Daten für den Haupt-Feed abrufen
    fetched_main_data = fetch_zotero_items(
        group_id_param=GROUP_ID,
        item_type_param=ZOTERO_ITEM_TYPE,
        sort_by_param=SORT_BY,
        direction_param=DIRECTION,
        limit_param=MAX_LIMIT_PER_REQUEST,
        collection_key_override=None, # Wichtig: Kein Collection Key für den Haupt-Feed (alle Items der Gruppe)
        ag_name_label_override=main_feed_label # Label für Log-Meldungen
    )
    # Haupt-Feed erstellen, wenn Daten vorhanden sind
    if fetched_main_data is not None and len(fetched_main_data) > 0:
        create_rss_feed(
            items_data=fetched_main_data,
            output_filename_param=MAIN_FEED_FILENAME, # Dateiname des Haupt-Feeds
            channel_title_param=main_feed_title,
            channel_link_param=RSS_CHANNEL_LINK,
            channel_description_param=main_feed_description,
            channel_language_param=RSS_CHANNEL_LANGUAGE,
            feed_url_atom_param=main_feed_atom_url,
            generator_label_param=main_feed_label
        )
    elif fetched_main_data is None: # Schwerer Fehler beim Abrufen
         logging.error(f"Feed-Generierung für {main_feed_label} fehlgeschlagen, da keine Daten von Zotero abgerufen werden konnten.")
    else: # Keine Daten gefunden (len == 0)
        logging.warning(f"Keine verarbeitbaren Einträge für {main_feed_label} von Zotero gefunden. Feed-Datei '{MAIN_FEED_FILENAME}' wird nicht erstellt/aktualisiert.")

    # 2. Generiere Feeds für jede konfigurierte Arbeitsgruppe
    # -------------------------------------------------------
    logging.info("\n--- Generiere Feeds für einzelne Arbeitsgruppen ---")
    # Durchlaufe die oben definierte Liste AG_CONFIGURATIONS
    for ag_config in AG_CONFIGURATIONS:
        ag_key = ag_config["key"]       # Zotero Collection Key der AG
        ag_label = ag_config["label"]   # Anzeigename der AG
        ag_prefix = ag_config["prefix"] # Dateinamen-Präfix der AG

        logging.info(f"--- Verarbeite Arbeitsgruppe: {ag_label} (Key: {ag_key}) ---")

        # Dynamische Konfiguration für den aktuellen AG-Feed
        current_output_filename = f"{ag_prefix}{DEFAULT_AG_OUTPUT_SUFFIX}" # z.B. AG_Schmidli_zotero_rss.xml
        current_rss_channel_title = f"{ag_label} Publikationen (IAU)"
        current_rss_channel_description = f"Publikationen der {ag_label}, Institut für Atmosphäre und Umwelt (IAU)"
        current_feed_url = f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{current_output_filename}" # atom:link URL

        # Daten für die aktuelle AG abrufen
        fetched_ag_data = fetch_zotero_items(
            group_id_param=GROUP_ID,
            item_type_param=ZOTERO_ITEM_TYPE,
            sort_by_param=SORT_BY,
            direction_param=DIRECTION,
            limit_param=MAX_LIMIT_PER_REQUEST,
            collection_key_override=ag_key, # Spezifischer Collection Key für diese AG
            ag_name_label_override=ag_label # Label für Log-Meldungen
        )
        
        # AG-Feed erstellen, wenn Daten vorhanden sind
        if fetched_ag_data is not None and len(fetched_ag_data) > 0:
            create_rss_feed(
                items_data=fetched_ag_data,
                output_filename_param=current_output_filename,
                channel_title_param=current_rss_channel_title,
                channel_link_param=RSS_CHANNEL_LINK, # Hauptlink des Instituts bleibt gleich
                channel_description_param=current_rss_channel_description,
                channel_language_param=RSS_CHANNEL_LANGUAGE, # Sprache bleibt gleich
                feed_url_atom_param=current_feed_url,
                generator_label_param=ag_label # Label für Generator-Info und Logs
            )
        elif fetched_ag_data is None: # Schwerer Fehler beim Abrufen für diese AG
            logging.error(f"Feed-Generierung für {ag_label} fehlgeschlagen, da keine Daten von Zotero abgerufen werden konnten.")
        else: # Keine Daten für diese AG gefunden (len == 0)
             logging.warning(f"Keine verarbeitbaren Einträge für {ag_label} von Zotero gefunden. Feed-Datei '{current_output_filename}' wird nicht erstellt/aktualisiert.")
        logging.info(f"--- Verarbeitung für {ag_label} abgeschlossen ---\n")

    logging.info("=== Zotero RSS Feed Generator Skript beendet ===")
