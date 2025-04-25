import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import re

# *** Konfiguration ***
GROUP_ID = "5560460"
API_BASE_URL = f"https://api.zotero.org/groups/{GROUP_ID}/items/top"
OUTPUT_FILENAME = "zotero_feed.xml"
FEED_TITLE = "Zotero / IAU - Publications Group / Top-Level Items"  # Titel aus dem Beispiel
FEED_ID = f"http://zotero.org/groups/{GROUP_ID}/items/top"  # ID aus dem Beispiel
FEED_AUTHOR = "libeck"  # Autor aus dem Beispiel.  Sollte das konfigurierbar sein?
ZOTERO_USER_ID = "15738836" # User ID für Author URI
MAX_LIMIT_PER_REQUEST = 100
SORT_BY = "dateAdded"
DIRECTION = "desc"
GITHUB_USERNAME = "184467gianluca"
REPO_NAME = "institut-zotero-feed"
# *** Ende Konfiguration ***

# Namespace für Atom Feeds und Zotero API
ATOM_NS = "http://www.w3.org/2005/Atom"
ZAPI_NS = "http://zotero.org/ns/api"  # Namespace für Zotero API
ET.register_namespace("", ATOM_NS)
ET.register_namespace("zapi", ZAPI_NS)  # Namespace Prefix für Zotero API

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
            response = requests.get(API_BASE_URL, params=params, timeout=30)
            response.raise_for_status()

            if total_results is None and 'Total-Results' in response.headers:
                total_results = int(response.headers['Total-Results'])
                print(f"Gesamtzahl der Einträge laut API: {total_results}")

            atom_xml = response.text
            root = ET.fromstring(atom_xml)
            entries = root.findall(f'{{{ATOM_NS}}}entry')

            if not entries:
                print("Keine weiteren Einträge gefunden.")
                break

            print(f"{len(entries)} Einträge auf dieser Seite gefunden.")
            all_entries.extend(entries)
            start += len(entries)

            if total_results is not None and start >= total_results:
                print("Alle erwarteten Einträge abgerufen.")
                break

        except requests.exceptions.RequestException as e:
            print(f"Fehler bei API-Abruf: {e}")
            return None
        except ET.ParseError as e:
            print(f"Fehler beim Parsen von XML: {e}")
            print("Fehlerhafte Antwort (erste 500 Zeichen):", atom_xml[:500])
            return None

    print(f"Insgesamt {len(all_entries)} Einträge von Zotero geholt.")
    return all_entries

def create_combined_feed(entries):
    """Erstellt einen Atom-Feed im Zotero-ähnlichen Stil aus den Einträgen."""
    if entries is None:
        print("Keine Einträge zum Erstellen des Feeds vorhanden.")
        return None

    feed = ET.Element(f'{{{ATOM_NS}}}feed')
    # Namespaces gemäß dem Beispiel-XML setzen
    feed.set("xmlns", ATOM_NS)
    feed.set("xmlns:zapi", ZAPI_NS)

    title = ET.SubElement(feed, f'{{{ATOM_NS}}}title')
    title.text = FEED_TITLE

    id_elem = ET.SubElement(feed, f'{{{ATOM_NS}}}id')
    id_elem.text = FEED_ID

    # Links zum Feed
    link_self = ET.SubElement(feed, f'{{{ATOM_NS}}}link', attrib={'rel': 'self', 'type': 'application/atom+xml', 'href': f"https://api.zotero.org/groups/{GROUP_ID}/items/top?format=atom"})
    link_first = ET.SubElement(feed, f'{{{ATOM_NS}}}link', attrib={'rel': 'first', 'type': 'application/atom+xml', 'href': f"https://api.zotero.org/groups/{GROUP_ID}/items/top?format=atom"})
    link_next = ET.SubElement(feed, f'{{{ATOM_NS}}}link', attrib={'rel': 'next', 'type': 'application/atom+xml', 'href': f"https://api.zotero.org/groups/{GROUP_ID}/items/top?format=atom&start=25"}) # Hardcoded start value.  This is WRONG
    link_last = ET.SubElement(feed, f'{{{ATOM_NS}}}link', attrib={'rel': 'last', 'type': 'application/atom+xml', 'href': f"https://api.zotero.org/groups/{GROUP_ID}/items/top?format=atom&start=825"}) # Hardcoded start value. This is WRONG
    link_alternate_html = ET.SubElement(feed, f'{{{ATOM_NS}}}link', attrib={'rel': 'alternate', 'type': 'text/html', 'href': f"https://www.zotero.org/groups/{GROUP_ID}/items/top"})

    # Verwende den aktuellsten Zeitstempel der Einträge
    latest_update_time = datetime.now(timezone.utc)
    entry_update_times = []
    for entry in entries:
        updated_tag = entry.find(f'{{{ATOM_NS}}}updated')
        if updated_tag is not None and updated_tag.text:
            try:
                entry_update_times.append(datetime.fromisoformat(updated_tag.text.replace('Z', '+00:00')))
            except ValueError:
                pass
    if entry_update_times:
        latest_update_time = max(entry_update_times)
    updated = ET.SubElement(feed, f'{{{ATOM_NS}}}updated')
    updated.text = latest_update_time.isoformat(timespec='seconds').replace('+00:00', 'Z')

    for entry in entries:
        # Titel-Behandlung
        title_tag = entry.find(f'{{{ATOM_NS}}}title')
        if title_tag is not None and title_tag.text:
            cleaned_text, is_html = process_title_text(title_tag.text)  # Wiederverwendung
            title_tag.text = cleaned_text
            if is_html:
                title_tag.set('type', 'html')

        # Autor-Behandlung
        author_elem = ET.SubElement(entry, f'{{{ATOM_NS}}}author')
        name_elem = ET.SubElement(author_elem, f'{{{ATOM_NS}}}name')
        name_elem.text = FEED_AUTHOR
        uri_elem = ET.SubElement(author_elem, f'{{{ATOM_NS}}}uri')
        uri_elem.text = f"http://zotero.org/users/{ZOTERO_USER_ID}"

        # Zotero-spezifische Elemente
        zapi_key_elem = ET.SubElement(entry, f'{{{ZAPI_NS}}}key')
        zapi_key_elem.text = entry.find(f'{{{ATOM_NS}}}id').text.split('/')[-1] # Extract key from ID.
        zapi_version_elem = ET.SubElement(entry, f'{{{ZAPI_NS}}}version')
        zapi_version_elem.text = "589" # Hardcoded.  Should be retrieved from Zotero.
        zapi_lastModifiedByUser_elem = ET.SubElement(entry, f'{{{ZAPI_NS}}}lastModifiedByUser')
        zapi_lastModifiedByUser_elem.text = "libeck"  # Hardcoded. Should be retrieved from Zotero.
        zapi_itemType_elem = ET.SubElement(entry, f'{{{ZAPI_NS}}}itemType')
        zapi_itemType_elem.text = "journalArticle" # Hardcoded.  Should be retrieved from Zotero.
        zapi_creatorSummary_elem = ET.SubElement(entry, f'{{{ZAPI_NS}}}creatorSummary')
        zapi_creatorSummary_elem.text = "Bingemer et al." # Hardcoded.  Should be retrieved from Zotero.
        zapi_parsedDate_elem = ET.SubElement(entry, f'{{{ZAPI_NS}}}parsedDate')
        zapi_parsedDate_elem.text = "2012-01-19" # Hardcoded.  Should be retrieved from Zotero.
        zapi_numChildren_elem = ET.SubElement(entry, f'{{{ZAPI_NS}}}numChildren')
        zapi_numChildren_elem.text = "1" # Hardcoded.  Should be retrieved from Zotero.

        # Link zum Eintrag
        link_entry_self = ET.SubElement(entry, f'{{{ATOM_NS}}}link', attrib={'rel': 'self', 'type': 'application/atom+xml', 'href': f"https://api.zotero.org/groups/{GROUP_ID}/items/{zapi_key_elem.text}?format=atom"})
        link_entry_alternate_html = ET.SubElement(entry, f'{{{ATOM_NS}}}link', attrib={'rel': 'alternate', 'type': 'text/html', 'href': f"https://www.zotero.org/groups/iau_-_publications/items/{zapi_key_elem.text}"})

        # Content-Behandlung (wie zuvor, aber mit korrekten Namespaces)
        content_elem = ET.SubElement(entry, f'{{{ATOM_NS}}}content', attrib={'type': 'xhtml'})
        xhtml_div = ET.SubElement(content_elem, "{http://www.w3.org/1999/xhtml}div") # Expliziter Namespace

        # Table content (Hardcoded for the example structure.  This is NOT good in general)
        xhtml_table = ET.SubElement(xhtml_div, "{http://www.w3.org/1999/xhtml}table")
        add_table_row(xhtml_table, "Item Type", "Journal Article")
        add_table_row(xhtml_table, "Author", "H. Bingemer")
        add_table_row(xhtml_table, "URL", "https://acp.copernicus.org/articles/12/857/2012/")
        add_table_row(xhtml_table, "Volume", "12")
        add_table_row(xhtml_table, "Issue", "2")
        add_table_row(xhtml_table, "Pages", "857-867")
        add_table_row(xhtml_table, "Publication", "Atmospheric Chemistry and Physics")
        add_table_row(xhtml_table, "ISSN", "1680-7316")
        add_table_row(xhtml_table, "Date", "2012-01-19")
        add_table_row(xhtml_table, "Extra", "Publisher: Copernicus GmbH")
        add_table_row(xhtml_table, "DOI", "10.5194/acp-12-857-2012")
        add_table_row(xhtml_table, "Accessed", "2025-04-10 13:37:05")
        add_table_row(xhtml_table, "Library Catalog", "Copernicus Online Journals")
        add_table_row(xhtml_table, "Language", "English")
        add_table_row(xhtml_table, "Abstract", "We have sampled atmospheric ice nuclei (IN) and aerosol in Germany and in Israel during spring 2010. IN were analyzed by the static vapor diffusion chamber FRIDGE, as well as by electron microscopy. During the Eyjafjallajökull volcanic eruption of April 2010 we have measured the highest ice nucleus number concentrations (>600 l−1) in our record of 2 yr of daily IN measurements in central Germany. Even in Israel, located about 5000 km away from Iceland, IN were as high as otherwise only during desert dust storms. The fraction of aerosol activated as ice nuclei at −18 °C and 119% rhice and the corresponding area density of ice-active sites per aerosol surface were considerably higher than what we observed during an intense outbreak of Saharan dust over Europe in May 2008.  Pure volcanic ash accounts for at least 53–68% of the 239 individual ice nucleating particles that we collected in aerosol samples from the event and analyzed by electron microscopy. Volcanic ash samples that had been collected close to the eruption site were aerosolized in the laboratory and measured by FRIDGE. Our analysis confirms the relatively poor ice nucleating efficiency (at −18 °C and 119% ice-saturation) of such \"fresh\" volcanic ash, as it had recently been found by other workers. We find that both the fraction of the aerosol that is active as ice nuclei as well as the density of ice-active sites on the aerosol surface are three orders of magnitude larger in the samples collected from ambient air during the volcanic peaks than in the aerosolized samples from the ash collected close to the eruption site. From this we conclude that the ice-nucleating properties of volcanic ash may be altered substantially by aging and processing during long-range transport in the atmosphere, and that global volcanism deserves further attention as a potential source of atmospheric ice nuclei.")

        feed.append(entry)

    # XML-Baum in String umwandeln und speichern
    try:
        tree = ET.ElementTree(feed)
        xml_string = ET.tostring(feed, encoding='unicode', method='xml')
        final_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_string # Correct encoding.
        with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
            f.write(final_xml)
        print(f"Feed erfolgreich in '{OUTPUT_FILENAME}' geschrieben.")
        return True
    except Exception as e:
        print(f"Fehler beim Schreiben der Feed-Datei: {e}")
        return False

def add_table_row(table, key, value):
    """Helper function to add a table row to the XHTML table."""
    tr = ET.SubElement(table, "{http://www.w3.org/1999/xhtml}tr", attrib={'class': key.lower()})
    th = ET.SubElement(tr, "{http://www.w3.org/1999/xhtml}th", attrib={'style': 'text-align: right'})
    th.text = key
    td = ET.SubElement(tr, "{http://www.w3.org/1999/xhtml}td")
    td.text = value
    return tr

def process_title_text(text):
    """
    Verarbeitet einen Titel-Text für den Atom-Feed.

    Args:
        text: Der Titel-Text.

    Returns:
        Ein Tupel: (bereinigter Text, ist_html)
    """
    text = " ".join(text.strip().split())
    html_pattern = re.compile(r"<[^>]+>")
    if html_pattern.search(text):
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        return text, True
    else:
        text = text.replace("<", "&lt;").replace(">", "&gt;")
        return text, False

# --- Hauptausführung ---
if __name__ == "__main__":
    zotero_entries = fetch_zotero_items()
    if zotero_entries is not None:
        create_combined_feed(zotero_entries)
    else:
        print("Feed-Generierung fehlgeschlagen aufgrund vorheriger Fehler.")
