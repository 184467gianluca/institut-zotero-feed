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
SINGLE_AUTHOR_SUFFIX = "_single_author" # Zusatz für Dateinamen der "Single Author"-Version
MAIN_FEED_FILENAME = "zotero_rss_minimal.xml" # Dateiname für den Haupt-Feed des Instituts

# RSS Channel Konfiguration (Basis, gilt für alle Feeds, wenn nicht spezifisch überschrieben)
RSS_CHANNEL_LINK = "https://www.iau.uni-frankfurt.de" # Hauptlink des Instituts
RSS_CHANNEL_LANGUAGE = "de-DE" # Sprache des Feeds

# Zotero API Abruf Konfiguration (allgemein gültig)
ZOTERO_ITEM_TYPE = "items/top" # Nur Top-Level Items
MAX_LIMIT_PER_REQUEST = 100 # Zotero API Limit pro Seite
SORT_BY = "dateAdded" # Sortierung beim API-Abruf (wird später in Python überschrieben durch Datumssortierung)
DIRECTION = "desc" # Sortierrichtung beim API-Abruf

# GitHub Pages Konfiguration (Basis für die Feed-URL-Konstruktion)
GITHUB_USERNAME = "184467gianluca"
REPO_NAME = "institut-zotero-feed"
# --- Ende Globale Konfiguration ---

# XML-Namespace für Atom Link
ATOM_NS = "http://www.w3.org/2005/Atom"

# Logging Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# === Konfiguration der einzelnen Arbeitsgruppen ===
AG_CONFIGURATIONS = [
    {"key": "QBAUQQNT", "label": "AG Achatz", "prefix": "AG_Achatz"},
    {"key": "D4M39XHF", "label": "AG Ahrens", "prefix": "AG_Ahrens"},
    {"key": "LBA3HESK", "label": "AG Curtius", "prefix": "AG_Curtius"},
    {"key": "TMY9JK3J", "label": "AG Engel", "prefix": "AG_Engel"},
    {"key": "C59ZK2Z2", "label": "AG Possner", "prefix": "AG_Possner"},
    {"key": "CCHBIWUJ", "label": "AG Schmidli", "prefix": "AG_Schmidli"},
    {"key": "2664JL92", "label": "AG Vogel", "prefix": "AG_Vogel"},
]
# === Ende Arbeitsgruppen-Konfiguration ===


def clean_html(raw_html):
    """Entfernt HTML-Tags aus einem String und dekodiert HTML-Entitäten."""
    if not raw_html:
        return ""
    raw_html_str = str(raw_html)
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html_str)
    return html.unescape(cleantext).strip()

def parse_date(date_str):
    """Versucht, einen Datumsstring in ein datetime-Objekt umzuwandeln.
    Wird für die Sortierung der Einträge nach Publikationsdatum benötigt.
    """
    if not date_str:
        return datetime.min # Gib ein sehr altes Datum zurück, um Einträge ohne Datum nach hinten zu sortieren
    
    date_str_val = str(date_str).strip()
    # Verschiedene Formate durchprobieren, von spezifisch bis allgemein
    for fmt in ('%Y-%m-%d', '%Y-%m', '%Y'):
        try:
            return datetime.strptime(date_str_val, fmt)
        except ValueError:
            continue # Nächstes Format versuchen
            
    # Fallback für reine vierstellige Jahreszahlen im Text
    match = re.search(r'\b(\d{4})\b', date_str_val)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y')
        except ValueError:
            pass

    logging.warning(f"Konnte kein valides Datum aus '{date_str_val}' für die Sortierung parsen.")
    return datetime.min # Fallback, wenn kein Format passt

def extract_year(date_str):
    """Extrahiert nur die vierstellige Jahreszahl aus einem Datumsstring für die Anzeige."""
    if not date_str:
        return None
    date_str_val = str(date_str)
    match = re.search(r'\b(\d{4})\b', date_str_val)
    if match:
        return match.group(1)
    logging.warning(f"Konnte kein Jahr aus '{date_str_val}' für die Anzeige extrahieren.")
    return None

def format_authors(creators, single_author_mode=False):
    """Formatiert die Autorenliste. Im single_author_mode wird nur der erste Autor mit 'et al.' angezeigt."""
    if not creators:
        return ""
        
    author_list = []
    if not isinstance(creators, list):
        logging.warning(f"Unerwartetes Format für 'creators': {creators}. Erwarte eine Liste.")
        return ""
        
    for creator in creators:
        if isinstance(creator, dict) and creator.get('creatorType') == 'author':
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
    
    if not author_list:
        return ""

    # NEU: Logik für den Single-Author-Modus
    if single_author_mode:
        if len(author_list) > 1:
            return f"{author_list[0]} et al."
        else:
            return author_list[0]
    else:
        # Bisherige Logik: alle Autoren mit Semikolon trennen
        return "; ".join(author_list)

def find_best_link_json(item_data, fallback_url=None):
    """Sucht den besten Link (DOI, dann URL) und verwendet ggf. eine Fallback-URL."""
    if not isinstance(item_data, dict):
        logging.warning(f"Unerwartetes Format für item_data in find_best_link_json: {item_data}")
        return fallback_url
        
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

    url = item_data.get('url')
    if url and str(url).strip().startswith(('http://', 'https://')):
        try:
            parsed = urlparse(str(url).strip())
            safe_path = quote(parsed.path, safe='/:@&=+$,-.%')
            return urlunparse((parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, parsed.fragment))
        except Exception as e:
            logging.warning(f"Konnte URL '{url}' nicht sicher parsen/kodieren, verwende sie unverändert: {e}")
            return str(url).strip()

    item_key = item_data.get('key', ' unbekanntem Key')
    if fallback_url:
        logging.info(f"Kein spezifischer Link (DOI/URL) für Item mit Key {item_key} gefunden. Verwende Fallback-URL: {fallback_url}")
        return fallback_url
    else:
        logging.warning(f"Kein spezifischer Link (DOI/URL) und kein Fallback-URL für Item mit Key {item_key} gefunden.")
        return None

# KORRIGIERT: Fehlende Funktion wieder eingefügt.
def get_categories_json(item_data, year):
    """Extrahiert Kategorien für einen RSS-Eintrag. Aktuell nur das Jahr."""
    categories = []
    if not isinstance(item_data, dict):
        logging.warning(f"Unerwartetes Format für item_data in get_categories_json: {item_data}")
        return categories
    if year and str(year).isdigit() and len(str(year)) == 4:
        categories.append(str(year))
    return list(set(categories))


def fetch_zotero_items(group_id_param, item_type_param, sort_by_param, direction_param, limit_param, single_author_mode,
                       collection_key_override=None, ag_name_label_override="Gesamtinstitut"):
    """Holt alle Einträge von Zotero und sortiert sie nach Publikationsdatum."""
    all_items_data = []
    start = 0
    total_results = None
    
    current_fallback_url = None

    if collection_key_override:
        fetch_url = f"https://api.zotero.org/groups/{group_id_param}/collections/{collection_key_override}/{item_type_param}"
        current_fallback_url = f"https://www.zotero.org/groups/{group_id_param}/collections/{collection_key_override}/items"
        logging.info(f"Starte Abruf von Zotero für {ag_name_label_override} (Collection Key: {collection_key_override}).")
    else:
        fetch_url = f"https://api.zotero.org/groups/{group_id_param}/{item_type_param}"
        current_fallback_url = f"https://www.zotero.org/groups/{group_id_param}/library"
        logging.info(f"Starte Abruf von Zotero für {ag_name_label_override} (gesamte Gruppe).")

    while True:
        params = {'format': 'json', 'sort': sort_by_param, 'direction': direction_param, 'limit': limit_param, 'start': start}
        try:
            logging.info(f"Rufe Einträge ab ({ag_name_label_override}): Start={start}, Limit={limit_param}")
            headers = {'Zotero-API-Version': '3'}
            response = requests.get(fetch_url, params=params, headers=headers, timeout=120)

            if response.status_code != 200:
                logging.error(f"Fehler bei API-Abruf für {ag_name_label_override}. Status: {response.status_code}, URL: {response.url}")
                if response.status_code == 404: logging.error("-> Gruppe/Collection nicht gefunden.")
                if response.status_code == 403: logging.error("-> Zugriff verweigert.")
                if response.status_code == 429: logging.error("-> Zu viele Anfragen (Rate Limit).")
                return None
            response.raise_for_status()

            if total_results is None and 'Total-Results' in response.headers:
                try:
                    total_results = int(response.headers['Total-Results'])
                    logging.info(f"Gesamtzahl der Einträge laut API für {ag_name_label_override}: {total_results}")
                except ValueError:
                    logging.warning(f"Konnte 'Total-Results' Header nicht als Zahl interpretieren ({ag_name_label_override}).")
                    total_results = -1
            
            items_json = response.json()
            if not isinstance(items_json, list):
                logging.error(f"Unerwartete Antwort von Zotero API ({ag_name_label_override}): Erwartete Liste, bekam {type(items_json)}.")
                break
            if not items_json:
                logging.info(f"Keine weiteren Einträge für {ag_name_label_override} gefunden.")
                break
            
            logging.info(f"{len(items_json)} Einträge auf dieser Seite für {ag_name_label_override} gefunden.")

            for item in items_json:
                try:
                    item_data = item.get('data', {})
                    if not isinstance(item_data, dict):
                        logging.warning(f"Unerwartetes 'data'-Format für Item {item.get('key', '')}, überspringe.")
                        continue
                    
                    date_str = item_data.get('date')
                    # Daten für jedes Item extrahieren und verarbeiten
                    all_items_data.append({
                        'zotero_key': item.get('key') or item_data.get('key'),
                        'authors': format_authors(item_data.get('creators', []), single_author_mode),
                        'year': extract_year(date_str),
                        'parsed_date': parse_date(date_str), # NEU: Datum für Sortierung parsen
                        'title': clean_html(item_data.get('title', '')),
                        'journal': clean_html(item_data.get('journalAbbreviation')) or clean_html(item_data.get('publicationTitle')),
                        'volume': str(item_data.get('volume', '')).strip(),
                        'link': find_best_link_json(item_data, fallback_url=current_fallback_url),
                        'categories': get_categories_json(item_data, extract_year(date_str)),
                    })
                except Exception as e:
                    logging.error(f"Fehler beim Verarbeiten von Item (Key: {item.get('key', 'N/A')}): {e}", exc_info=True)
            
            start += len(items_json)
            if total_results is not None and total_results != -1 and start >= total_results:
                break
            if len(items_json) < limit_param:
                break
        except requests.exceptions.RequestException as e:
            logging.error(f"Netzwerk- oder HTTP-Fehler bei API-Abruf für {ag_name_label_override}: {e}")
            break
        except Exception as e:
            logging.error(f"Unerwarteter Fehler während des API-Abrufs für {ag_name_label_override}: {e}", exc_info=True)
            break
            
    # NEU: Sortiere die gesammelten Daten nach dem geparsten Datum (absteigend)
    all_items_data.sort(key=lambda item: item['parsed_date'], reverse=True)
    
    logging.info(f"Insgesamt {len(all_items_data)} Einträge von Zotero für {ag_name_label_override} erfolgreich für den Feed vorbereitet und sortiert.")
    return all_items_data

def create_rss_feed(items_data, output_filename_param, channel_title_param, channel_link_param,
                    channel_description_param, channel_language_param, feed_url_atom_param, generator_label_param):
    """Erstellt den RSS Feed im XML-Format aus den vorbereiteten und sortierten Item-Daten."""
    if not items_data:
        logging.warning(f"Keine Einträge für {generator_label_param} zum Erstellen des Feeds '{output_filename_param}' vorhanden.")
        return None
    
    ET.register_namespace('atom', ATOM_NS)
    rss = ET.Element('rss', version="2.0")
    channel = ET.SubElement(rss, 'channel')

    ET.SubElement(channel, 'title').text = channel_title_param
    ET.SubElement(channel, 'link').text = channel_link_param
    ET.SubElement(channel, 'description').text = channel_description_param
    if channel_language_param:
        ET.SubElement(channel, 'language').text = channel_language_param
    now_rfc822 = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    ET.SubElement(channel, 'lastBuildDate').text = now_rfc822
    ET.SubElement(channel, 'pubDate').text = now_rfc822
    ET.SubElement(channel, 'generator').text = f"Zotero Feed Generator Script ({generator_label_param})"

    atom_link_attrib = { 'href': feed_url_atom_param, 'rel': 'self', 'type': 'application/rss+xml' }
    ET.SubElement(channel, f'{{{ATOM_NS}}}link', attrib=atom_link_attrib)

    item_count = 0
    for item_data in items_data:
        item = ET.SubElement(channel, 'item')
        title_parts = []
        # Daten aus dem aufbereiteten Dictionary holen
        authors = item_data.get('authors')
        year = item_data.get('year')
        paper_title = item_data.get('title', '[Titel nicht verfügbar]')
        journal_name = item_data.get('journal')
        volume_number = item_data.get('volume')
        
        if authors: title_parts.append(authors)
        if year: title_parts.append(f"({year})")
        title_parts.append(paper_title)
        if journal_name: title_parts.append(journal_name)
        if volume_number: title_parts.append(volume_number)
        
        rss_item_title = ""
        for i, part in enumerate(title_parts):
            part_str = str(part).strip()
            if not part_str: continue
            if i == 0:
                rss_item_title += part_str
            elif part_str.startswith('('):
                rss_item_title += f" {part_str}"
            else:
                if rss_item_title and not rss_item_title.strip().endswith(')'):
                    rss_item_title += "."
                rss_item_title += f" {part_str}"
        ET.SubElement(item, 'title').text = rss_item_title.strip()
        
        rss_link = item_data.get('link')
        if rss_link:
            ET.SubElement(item, 'link').text = rss_link
        else:
            logging.warning(f"Item '{rss_item_title[:50]}...' ({generator_label_param}) hat keinen Link. <link>-Tag wird ausgelassen.")

        rss_categories = item_data.get('categories', [])
        if rss_categories:
            for category_name in rss_categories:
                if category_name: ET.SubElement(item, 'category').text = str(category_name)
        
        guid_text = item_data.get('zotero_key')
        guid_is_permalink = "false"
        if not guid_text and rss_link:
            guid_text = rss_link
            guid_is_permalink = "true"
        elif not guid_text:
            guid_text = rss_item_title
            guid_is_permalink = "false"
            logging.warning(f"Item '{rss_item_title[:50]}...' ({generator_label_param}) hat keine GUID, verwende Titel.")
        
        guid_elem = ET.SubElement(item, 'guid', isPermaLink=guid_is_permalink)
        guid_elem.text = str(guid_text)

        ET.SubElement(item, 'pubDate').text = now_rfc822
        item_count += 1
    
    try:
        ET.indent(rss, space="  ", level=0)
        tree = ET.ElementTree(rss)
        tree.write(output_filename_param, encoding="utf-8", xml_declaration=True, method='xml')
        logging.info(f"{item_count} Einträge für {generator_label_param} erfolgreich formatiert und in '{output_filename_param}' geschrieben.")
        return True
    except Exception as e:
        logging.error(f"Fehler beim Schreiben der RSS-Datei '{output_filename_param}' für {generator_label_param}: {e}")
        return False

def generate_feeds_for_mode(single_author_mode):
    """Führt die Feed-Generierung für einen bestimmten Modus durch (alle Autoren oder einzelner Autor)."""
    mode_suffix = SINGLE_AUTHOR_SUFFIX if single_author_mode else ""
    mode_label = "Single Author" if single_author_mode else "Alle Autoren"
    logging.info(f"\n=== Starte Generierung für Modus: {mode_label} ===")

    # 1. Haupt-Feed generieren
    logging.info(f"--- Generiere Haupt-Feed ({mode_label}) ---")
    main_feed_name_base = MAIN_FEED_FILENAME.replace('.xml', '')
    main_output_filename = f"{main_feed_name_base}{mode_suffix}.xml"
    if not single_author_mode:
        main_output_filename = MAIN_FEED_FILENAME # Für den Standardmodus den Originalnamen behalten

    main_feed_atom_url = f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{main_output_filename}"
    main_feed_title = f"IAU Publikationen (Minimal, {mode_label})"

    fetched_main_data = fetch_zotero_items(
        group_id_param=GROUP_ID, item_type_param=ZOTERO_ITEM_TYPE, sort_by_param=SORT_BY,
        direction_param=DIRECTION, limit_param=MAX_LIMIT_PER_REQUEST, single_author_mode=single_author_mode
    )
    if fetched_main_data:
        create_rss_feed(
            items_data=fetched_main_data, output_filename_param=main_output_filename,
            channel_title_param=main_feed_title, channel_link_param=RSS_CHANNEL_LINK,
            channel_description_param=f"Publikationen des Instituts für Atmosphäre und Umwelt (IAU) - {mode_label}",
            channel_language_param=RSS_CHANNEL_LANGUAGE, feed_url_atom_param=main_feed_atom_url,
            generator_label_param=f"Gesamtinstitut ({mode_label})"
        )

    # 2. Feeds für Arbeitsgruppen generieren
    logging.info(f"\n--- Generiere Feeds für einzelne Arbeitsgruppen ({mode_label}) ---")
    for ag_config in AG_CONFIGURATIONS:
        ag_key, ag_label, ag_prefix = ag_config["key"], ag_config["label"], ag_config["prefix"]
        logging.info(f"--- Verarbeite Arbeitsgruppe: {ag_label} ({mode_label}) ---")

        current_output_filename = f"{ag_prefix}{mode_suffix}{DEFAULT_AG_OUTPUT_SUFFIX}"
        current_rss_channel_title = f"{ag_label} Publikationen (IAU, {mode_label})"
        current_feed_url = f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{current_output_filename}"

        fetched_ag_data = fetch_zotero_items(
            group_id_param=GROUP_ID, item_type_param=ZOTERO_ITEM_TYPE, sort_by_param=SORT_BY,
            direction_param=DIRECTION, limit_param=MAX_LIMIT_PER_REQUEST, single_author_mode=single_author_mode,
            collection_key_override=ag_key, ag_name_label_override=ag_label
        )
        if fetched_ag_data:
            create_rss_feed(
                items_data=fetched_ag_data, output_filename_param=current_output_filename,
                channel_title_param=current_rss_channel_title, channel_link_param=RSS_CHANNEL_LINK,
                channel_description_param=f"Publikationen der {ag_label}, Institut für Atmosphäre und Umwelt (IAU) - {mode_label}",
                channel_language_param=RSS_CHANNEL_LANGUAGE, feed_url_atom_param=current_feed_url,
                generator_label_param=f"{ag_label} ({mode_label})"
            )
        logging.info(f"--- Verarbeitung für {ag_label} ({mode_label}) abgeschlossen ---\n")

# --- Hauptausführung des Skripts ---
if __name__ == "__main__":
    logging.info("=== Starte Zotero RSS Feed Generator Skript ===")
    
    # Generiere Feeds im Standardmodus (alle Autoren)
    generate_feeds_for_mode(single_author_mode=False)
    
    # Generiere Feeds im Single-Author-Modus
    generate_feeds_for_mode(single_author_mode=True)
    
    logging.info("=== Zotero RSS Feed Generator Skript beendet ===")
