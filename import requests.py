import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# *** Konfifuration ***
GROUP_ID = "5560460" # Die Zotero Gruppen ID vom IAU
API_BASE_URL = f"https://api.zotero.org/groups/{GROUP_ID}/items/top"
OUTPUT_FILNAME = "zotero_feed.xml" # Name der Output-Datei
FEED_TITLE = "Publikationen des IAU" # Titel für den Feed
FEED_ID = f"urn:zotero:group:{GROUP_ID}:items" # Eindeutige ID für den Feed
FEED_AUTHOR = "IAU" # Author des Feeds
MAX_LIMIT_PER_REQUEST = 100 # Zotero API Limit pro Seite in machen Quellen auch 150?
SORT_BY = "dateAdded" # Sortierung der Items
DIRECTION = "desc" # Sortierrichtung
# *** Ende Konfiguration ***

# Namespace für Atom Feeds (war wichtig für XML Verarbeitung)
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM_NS) # Standard Namespace setzen