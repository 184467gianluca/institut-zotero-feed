import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import re # Für Jahreszahl-Extraktion und HTML-Strip
from urllib.parse import quote # Für URL-Encoding

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

# GitHub Pages Konfiguration (für atom:link und Fallback-GUID)
GITHUB_USERNAME = "184467gianluca"
REPO_NAME = "institut-zotero-feed"
FEED_URL = f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}/{OUTPUT_FILENAME}"
# --- Ende Konfiguration ---

# Namespace für Atom Link (wird im RSS eingebettet)
ATOM_NS = "http://www.w3.org/2005/Atom"


def clean_html(raw_html):
  """Entfernt HTML-Tags aus einem String."""
  if not raw_html:
      return ""
  cleanr = re.compile('<.*?>')
  cleantext = re.sub(cleanr, '', str(raw_html))
  # Zusätzlich HTML-Entities dekodieren (z.B. &amp; -> &)
  import html
  return html.unescape(cleantext)

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
        # Check if it's an integer representation of a year
        if isinstance(date_str, (int, float)) and 1900 < int(date_str) < 2100:
             return str(int(date_str))
        # Check if it's a string that can be parsed as a year
        if isinstance(date_str, str):
             dt = datetime.strptime(date_str, '%Y') # Try parsing just year
             return dt.strftime('%Y')
    except ValueError: # Handle cases where parsing fails
        pass
    except TypeError: # Handle cases where type conversion fails
        pass
    return None


def format_authors(creators):
    """Formatiert die Autorenliste aus dem creators-Array."""
    if not creators:
        return ""
    author_list = []
    for creator in creators:
        # Ensure creator is a dictionary
        if not isinstance(creator, dict):
            continue
        # Nur Autoren berücksichtigen
        if creator.get('creatorType') == 'author':
            last_name = creator.get('lastName', '')
            first_name = creator.get('firstName', '')
            # Ensure names are strings
            last_name = str(last_name) if last_name is not None else ''
            first_name = str(first_name) if first_name is not None else ''

            if last_name and first_name:
                # Standard-Reihenfolge (Nachname, Vorname) - Anpassen falls gewünscht
                author_list.append(f"{last_name}, {first_name}")
            elif last_name:
                author_list.append(last_name)
            elif first_name:
                # Sollte nicht vorkommen, aber sicherheitshalber
                author_list.append(first_name)
            elif creator.get('name'): # Für institutionelle Autoren etc.
                 author_list.append(str(creator['name']))

    return ", ".join(filter(None, author_list)) # Filter out empty strings

def find_best_link_json(item_data):
    """Sucht den besten Link (DOI, URL) aus den JSON-Daten und kodiert ihn korrekt."""
    doi = item_data.get('DOI')
    if doi and str(doi).strip():
        doi_text = str(doi).strip()
        # Entferne häufige fehlerhafte Präfixe wie "DOI ", "doi:", "/" etc.
        doi_text = re.sub(r'^(doi\s*:?\s*/*)+', '', doi_text, flags=re.IGNORECASE)

        # URL-Encode nur den DOI-Teil, nicht die ganze URL
        # Ersetze unsichere Zeichen wie < > durch ihre Kodierung
        # quote() kodiert standardmäßig keine Slashes '/', was für DOIs okay ist
        # quote() kodiert auch keine Semikolons ';', was problematisch sein *könnte*,
        # aber oft in DOIs vorkommt. Wir lassen es erstmal so.
        # Wichtig: Leerzeichen werden zu %20 kodiert.
        safe_doi_text = quote(doi_text, safe='/:()') # Erlaube Slashes, Doppelpunkte, Klammern

        # Konstruiere die finale URL
        # Prüfe, ob der ursprüngliche Text bereits eine volle URL war
        if doi_text.startswith('http://doi.org/') or doi_text.startswith('https://doi.org/'):
             # Wenn ja, parse und re-encode nur den Pfad-Teil
             from urllib.parse import urlparse, urlunparse
             parsed = urlparse(doi_text)
             safe_path = quote(parsed.path, safe='/:()')
             return urlunparse((parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, parsed.fragment))
        else:
             # Andernfalls, baue die URL neu auf
             return f"https://doi.org/{safe_doi_text}"


    url = item_data.get('url')
    if url and str(url).strip().startswith(('http://', 'https://')):
        # Hier gehen wir davon aus, dass die URL bereits korrekt ist.
        # Eine zusätzliche Validierung/Kodierung könnte hier erfolgen, ist aber komplex.
        return str(url).strip()

    # Fallback: Link zur Zotero-Seite (aus 'links'->'alternate')
    links_data = item_data.get('links')
    if isinstance(links_data, dict) and 'alternate' in links_data:
        alt_link_data = links_data['alternate']
        if isinstance(alt_link_data, dict):
             alt_link = alt_link_data.get('href')
             if alt_link:
                 return alt_link

    return None # Kein Link gefunden

def get_categories_json(item_data, year):
    """Extrahiert Kategorien (Jahr, AG-Tags - AG aktuell deaktiviert) aus den JSON-Daten."""
    categories = []
    # 1. Jahreszahl hinzufügen (nur wenn gültig)
    if year and str(year).isdigit() and len(str(year)) == 4:
        categories.append(str(year))

    # 2. Arbeitsgruppen-Tags hinzufügen (AKTUELL AUSKOMMENTIERT)
    #    -> Um dies zu aktivieren, entfernen Sie die Kommentarzeichen (#)
    #       in den folgenden Zeilen, sobald die Tags in Zotero existieren.
    # tags = item_data.get('tags', [])
    # if isinstance(tags, list): # Ensure tags is a list
    #     for tag_info in tags:
    #         # Ensure tag_info is a dictionary and has 'tag' key
    #         if isinstance(tag_info, dict) and 'tag' in tag_info:
    #             tag = tag_info.get('tag')
    #             if tag and isinstance(tag, str) and tag.startswith(AG_TAG_PREFIX):
    #                 # Füge den Tag ohne Präfix hinzu (oder mit, je nach Wunsch)
    #                 # categories.append(tag) # Mit Präfix
    #                 categories.append(tag[len(AG_TAG_PREFIX):].strip()) # Ohne Präfix

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
            'sort': SORT_BY,
            'direction': DIRECTION,
            'limit': MAX_LIMIT_PER_REQUEST,
            'start': start
        }
        try:
            print(f"Rufe Einträge ab: Start={start}, Limit={MAX_LIMIT_PER_REQUEST}")
            headers = {'Zotero-API-Version': '3'}
            response = requests.get(fetch_url, params=params, headers=headers, timeout=60)
            response.raise_for_status()

            if total_results is None and 'Total-Results' in response.headers:
                total_results = int(response.headers['Total-Results'])
                print(f"Gesamtzahl der Einträge laut API: {total_results}")

            items_json = response.json()

            if not items_json:
                print("Keine weiteren Einträge gefunden (leere JSON-Antwort).")
                break

            print(f"{len(items_json)} Einträge auf dieser Seite gefunden.")

            for item in items_json:
                if not isinstance(item, dict):
                    print(f"Warnung: Unerwartetes Format für Eintrag gefunden, überspringe: {item}")
                    continue

                item_data = item.get('data', {})
                if not isinstance(item_data, dict):
                     print(f"Warnung: Unerwartetes 'data'-Format für Eintrag {item.get('key')}, überspringe.")
                     continue

                # --- Datenextraktion ---
                # Titel extrahieren und HTML entfernen
                title_raw = item_data.get('title', '')
                title = clean_html(title_raw) # HTML entfernen
                if not title: # Fallback, falls Titel leer ist
                    title = "[Titel nicht verfügbar]"

                creators = item_data.get('creators', [])
                date_str = item_data.get('date')
                journal_abbr = clean_html(item_data.get('journalAbbreviation')) # Auch hier HTML entfernen
                pub_title = clean_html(item_data.get('publicationTitle')) # Auch hier HTML entfernen
                volume = item_data.get('volume')

                year = extract_year(date_str)
                authors_formatted = format_authors(creators)
                journal_display = journal_abbr if journal_abbr else pub_title

                # --- RSS Felder zusammenbauen ---
                # Titel-Tag
                rss_title_parts = []
                if authors_formatted:
                    rss_title_parts.append(authors_formatted)
                if year:
                    rss_title_parts.append(f"({year})")
                rss_title_parts.append(str(title)) # Sicherstellen, dass Titel ein String ist
                if journal_display:
                     rss_title_parts.append(str(journal_display))
                if volume:
                     rss_title_parts.append(str(volume))

                rss_title = ""
                for i, part in enumerate(rss_title_parts):
                    if part:
                        part_str = str(part)
                        # Füge Punkt hinzu, außer beim ersten Element oder wenn es die Jahreszahl ist
                        if i > 0 and not part_str.startswith('('):
                            rss_title += ". "
                        # Füge Leerzeichen nach der Jahreszahl-Klammer hinzu, wenn mehr folgt
                        elif part_str.endswith(')') and i < len(rss_title_parts) - 1 and rss_title_parts[i+1]:
                             rss_title += part_str + " "
                             continue # Gehe zum nächsten Teil über
                        rss_title += part_str

                # Fallback für komplett leeren Titel
                if not rss_title.strip():
                    rss_title = "[Kein Titel verfügbar]"


                # Link-Tag
                rss_link = find_best_link_json(item_data)

                # Kategorien
                rss_categories = get_categories_json(item_data, year)

                # GUID
                guid = item.get('key') or item_data.get('key')
                if not guid and rss_link:
                    guid = rss_link
                elif not guid:
                     guid = rss_title # Fallback auf den (hoffentlich nicht leeren) Titel

                all_items_data.append({
                    'rss_title': rss_title,
                    'rss_link': rss_link,
                    'rss_categories': rss_categories,
                    'guid': guid,
                })


            start += len(items_json)

            if total_results is not None and start >= total_results:
                print("Alle erwarteten Einträge abgerufen.")
                break
            if len(items_json) < MAX_LIMIT_PER_REQUEST:
                print("Weniger Einträge als Limit erhalten, nehme an, das waren die letzten.")
                break

        except requests.exceptions.RequestException as e:
            print(f"Fehler bei API-Abruf: {e}")
            print("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break
        except Exception as e:
            print(f"Unerwarteter Fehler beim Verarbeiten der Daten: {e}")
            error_context = response.text[:500] if 'response' in locals() and hasattr(response, 'text') else "Keine Antwortdaten verfügbar"
            print(f"Fehlerhafte Antwort/Kontext (erste 500 Zeichen): {error_context}")
            print("Versuche, mit bisher gesammelten Daten fortzufahren...")
            break

    print(f"Insgesamt {len(all_items_data)} Einträge von Zotero verarbeitet.")
    return all_items_data

def create_rss_feed(items_data):
    """Erstellt einen neuen, minimalen RSS 2.0 Feed mit Validierungs-Fixes."""
    if not items_data:
        print("Keine Einträge zum Erstellen des Feeds vorhanden.")
        return None

    # Registriere den Atom-Namespace für den self-Link
    ET.register_namespace('atom', ATOM_NS)

    # RSS Root-Element erstellen
    # Füge das Atom-Namespace-Attribut hinzu
    rss = ET.Element('rss', version="2.0", attrib={f"{{{ATOM_NS}}}link": ""}) # Dummy-Attribut, wird unten gesetzt

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
    ET.SubElement(channel, 'generator').text = "Zotero Feed Generator Script (Minimal, Validated)"

    # Atom Link (self) hinzufügen - Empfehlung vom Validator
    # Das Attribut wird hier korrekt gesetzt
    atom_link_attrib = {
        '{' + ATOM_NS + '}href': FEED_URL, # Verwende die konfigurierte Feed URL
        '{' + ATOM_NS + '}rel': 'self',
        '{' + ATOM_NS + '}type': 'application/rss+xml'
    }
    # Korrektur: Füge atom:link als Element hinzu, nicht als Attribut von <rss>
    ET.SubElement(channel, f'{{{ATOM_NS}}}link', attrib=atom_link_attrib)


    # Alle gesammelten Einträge als <item> hinzufügen
    for item_data in items_data:
        item = ET.SubElement(channel, 'item')

        # Titel (sicherstellen, dass nicht leer)
        item_title = str(item_data.get('rss_title', '[Titel nicht verfügbar]')).strip()
        if not item_title:
             item_title = '[Titel nicht verfügbar]'
        ET.SubElement(item, 'title').text = item_title

        # Link (nur wenn vorhanden und gültig)
        rss_link = item_data.get('rss_link')
        if rss_link and isinstance(rss_link, str) and rss_link.startswith(('http://', 'https://')):
            ET.SubElement(item, 'link').text = rss_link
        # else: Optional: Fallback-Link zum Channel oder zur Zotero-Seite?

        # Kategorien hinzufügen
        rss_categories = item_data.get('rss_categories', [])
        if isinstance(rss_categories, list):
             for category_name in rss_categories:
                 if category_name: # Nur nicht-leere Kategorien hinzufügen
                    ET.SubElement(item, 'category').text = str(category_name)

        # GUID hinzufügen
        guid_is_permalink = "false"
        guid_text = item_data.get('guid')
        if guid_text and str(guid_text).startswith(('http://', 'https://')):
             guid_is_permalink = "true"

        if not guid_text: # Fallback, falls GUID fehlt
             guid_text = item_title # Verwende Titel als Fallback GUID

        guid_elem = ET.SubElement(item, 'guid', isPermaLink=guid_is_permalink)
        guid_elem.text = str(guid_text)

    # XML-Baum in String umwandeln und speichern
    try:
        # ET.indent(rss, space="  ", level=0) # Einrückung kann manchmal Probleme mit Namespaces machen, optional
        tree = ET.ElementTree(rss)
        # Wichtig: encoding='utf-8' und xml_declaration=True für korrekte Datei
        # method='xml' stellt sicher, dass Namespace-Präfixe verwendet werden (wie atom:)
        tree.write(OUTPUT_FILENAME, encoding="utf-8", xml_declaration=True, method='xml')
        print(f"Minimaler RSS Feed erfolgreich in '{OUTPUT_FILENAME}' geschrieben (mit Validierungs-Fixes).")
        return True
    except Exception as e:
        print(f"Fehler beim Schreiben der RSS-Datei: {e}")
        return False

# --- Hauptausführung ---
if __name__ == "__main__":
    zotero_items_data = fetch_zotero_items()
    if zotero_items_data is not None:
        create_rss_feed(zotero_items_data)
    else:
        print("Feed-Generierung fehlgeschlagen, da keine Daten abgerufen werden konnten.")

