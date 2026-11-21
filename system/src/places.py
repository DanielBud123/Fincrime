"""Cities, states and provinces -> country, for the customer's support notes.

A note may say where the customer lived with a city or a state instead of a
country ("moved to Texas", "based in Lagos"). Missing that country is the
dangerous direction: a customer who looks tied to fewer countries is easier to
clear on location. This table is general (capitals, large cities, US states);
it is not built from the development notes.

It is used on the customer side only. Extra customer countries can only block
a location clear, never create one. Hit countries come from the hit's
structured fields alone and are never read through this table.
"""
from __future__ import annotations

import re
import unicodedata

from countries import codes_in_text, to_iso2

# name -> countries. One country: the place settles it. Several: it only raises a possibility.
_PLACES: dict[str, tuple[str, ...]] = {
    # United Kingdom and Ireland
    "london": ("GB",), "manchester": ("GB",), "birmingham": ("GB", "US"), "glasgow": ("GB",), "edinburgh": ("GB",),
    "liverpool": ("GB",), "leeds": ("GB",), "bristol": ("GB",), "belfast": ("GB",), "cardiff": ("GB",),
    "sheffield": ("GB",), "newcastle": ("GB", "AU"), "nottingham": ("GB",), "leicester": ("GB",),
    "dublin": ("IE",), "galway": ("IE",), "limerick": ("IE",),
    # Western Europe
    "paris": ("FR",), "lyon": ("FR",), "marseille": ("FR",), "toulouse": ("FR",), "bordeaux": ("FR",),
    "berlin": ("DE",), "munich": ("DE",), "munchen": ("DE",), "hamburg": ("DE",), "frankfurt": ("DE",),
    "cologne": ("DE",), "koln": ("DE",), "stuttgart": ("DE",), "dusseldorf": ("DE",), "leipzig": ("DE",),
    "madrid": ("ES",), "barcelona": ("ES",), "valencia": ("ES", "VE"), "seville": ("ES",), "sevilla": ("ES",),
    "bilbao": ("ES",), "malaga": ("ES",), "zaragoza": ("ES",),
    "rome": ("IT",), "roma": ("IT",), "milan": ("IT",), "milano": ("IT",), "naples": ("IT",), "napoli": ("IT",),
    "turin": ("IT",), "torino": ("IT",), "florence": ("IT",), "venice": ("IT",), "bologna": ("IT",),
    "genoa": ("IT",), "palermo": ("IT",),
    "lisbon": ("PT",), "porto": ("PT",),
    "amsterdam": ("NL",), "rotterdam": ("NL",), "the hague": ("NL",), "utrecht": ("NL",), "eindhoven": ("NL",),
    "brussels": ("BE",), "antwerp": ("BE",),
    "vienna": ("AT",), "salzburg": ("AT",), "graz": ("AT",),
    "zurich": ("CH",), "geneva": ("CH",), "basel": ("CH",), "bern": ("CH",), "lausanne": ("CH",),
    "stockholm": ("SE",), "gothenburg": ("SE",), "malmo": ("SE",),
    "oslo": ("NO",), "bergen": ("NO",), "copenhagen": ("DK",), "aarhus": ("DK",), "helsinki": ("FI",),
    "reykjavik": ("IS",),
    # Central and Eastern Europe
    "warsaw": ("PL",), "krakow": ("PL",), "gdansk": ("PL",), "wroclaw": ("PL",), "poznan": ("PL",),
    "prague": ("CZ",), "brno": ("CZ",), "bratislava": ("SK",), "budapest": ("HU",), "bucharest": ("RO",),
    "sofia": ("BG",), "athens": ("GR", "US"), "thessaloniki": ("GR",), "belgrade": ("RS",), "novi sad": ("RS",),
    "zagreb": ("HR",), "ljubljana": ("SI",), "sarajevo": ("BA",), "podgorica": ("ME",), "skopje": ("MK",),
    "tirana": ("AL",), "pristina": ("XK",), "chisinau": ("MD",), "kyiv": ("UA",), "kiev": ("UA",),
    "kharkiv": ("UA",), "odessa": ("UA",), "odesa": ("UA",), "lviv": ("UA",), "minsk": ("BY",),
    "moscow": ("RU",), "saint petersburg": ("RU",), "st petersburg": ("RU",), "st. petersburg": ("RU",),
    "novosibirsk": ("RU",), "vilnius": ("LT",), "riga": ("LV",), "tallinn": ("EE",),
    "istanbul": ("TR",), "ankara": ("TR",), "izmir": ("TR",), "tbilisi": ("GE",), "yerevan": ("AM",),
    "baku": ("AZ",), "nicosia": ("CY",), "valletta": ("MT",),
    # Africa
    "lagos": ("NG",), "abuja": ("NG",), "kano": ("NG",), "ibadan": ("NG",), "port harcourt": ("NG",),
    "kaduna": ("NG",), "benin city": ("NG",), "enugu": ("NG",), "accra": ("GH",), "kumasi": ("GH",),
    "nairobi": ("KE",), "mombasa": ("KE",), "kampala": ("UG",), "dar es salaam": ("TZ",),
    "addis ababa": ("ET",), "khartoum": ("SD",), "cairo": ("EG",), "alexandria": ("EG", "US"),
    "casablanca": ("MA",), "rabat": ("MA",), "marrakech": ("MA",), "algiers": ("DZ",), "tunis": ("TN",),
    "tripoli": ("LY", "LB"), "dakar": ("SN",), "abidjan": ("CI",), "bamako": ("ML",), "douala": ("CM",),
    "yaounde": ("CM",), "kinshasa": ("CD",), "luanda": ("AO",), "lusaka": ("ZM",), "harare": ("ZW",),
    "maputo": ("MZ",), "johannesburg": ("ZA",), "cape town": ("ZA",), "durban": ("ZA",), "pretoria": ("ZA",),
    "windhoek": ("NA",), "gaborone": ("BW",), "kigali": ("RW",), "mogadishu": ("SO",), "freetown": ("SL",),
    "monrovia": ("LR",),
    # South Asia and Middle East
    "dhaka": ("BD",), "chittagong": ("BD",), "chattogram": ("BD",), "sylhet": ("BD",), "khulna": ("BD",),
    "karachi": ("PK",), "lahore": ("PK",), "islamabad": ("PK",), "rawalpindi": ("PK",), "faisalabad": ("PK",),
    "peshawar": ("PK",), "sialkot": ("PK",), "mumbai": ("IN",), "bombay": ("IN",), "delhi": ("IN",),
    "new delhi": ("IN",), "bangalore": ("IN",), "bengaluru": ("IN",), "chennai": ("IN",), "kolkata": ("IN",),
    "calcutta": ("IN",), "hyderabad": ("IN", "PK"), "pune": ("IN",), "ahmedabad": ("IN",), "colombo": ("LK",),
    "kathmandu": ("NP",), "kabul": ("AF",), "tehran": ("IR",), "baghdad": ("IQ",), "damascus": ("SY",),
    "beirut": ("LB",), "amman": ("JO",), "riyadh": ("SA",), "jeddah": ("SA",), "dubai": ("AE",),
    "abu dhabi": ("AE",), "sharjah": ("AE",), "doha": ("QA",), "kuwait city": ("KW",), "manama": ("BH",),
    "muscat": ("OM",), "tel aviv": ("IL",), "jerusalem": ("IL", "PS"),
    # East Asia and Pacific
    "beijing": ("CN",), "shanghai": ("CN",), "shenzhen": ("CN",), "guangzhou": ("CN",), "taipei": ("TW",),
    "tokyo": ("JP",), "osaka": ("JP",), "seoul": ("KR",), "busan": ("KR",), "pyongyang": ("KP",),
    "bangkok": ("TH",), "hanoi": ("VN",), "ho chi minh city": ("VN",), "saigon": ("VN",), "jakarta": ("ID",),
    "surabaya": ("ID",), "kuala lumpur": ("MY",), "manila": ("PH",), "cebu": ("PH",),
    "sydney": ("AU",), "melbourne": ("AU",), "brisbane": ("AU",), "perth": ("AU", "GB"), "adelaide": ("AU",),
    "canberra": ("AU",), "auckland": ("NZ",), "wellington": ("NZ",),
    # Americas
    "toronto": ("CA",), "montreal": ("CA",), "vancouver": ("CA",), "ottawa": ("CA",), "calgary": ("CA",),
    "edmonton": ("CA",), "ontario": ("CA",), "quebec": ("CA",), "british columbia": ("CA",), "alberta": ("CA",),
    "manitoba": ("CA",), "saskatchewan": ("CA",), "nova scotia": ("CA",),
    "new york": ("US",), "los angeles": ("US",), "chicago": ("US",), "houston": ("US",), "miami": ("US",),
    "san francisco": ("US",), "boston": ("US",), "seattle": ("US",), "dallas": ("US",), "atlanta": ("US",),
    "philadelphia": ("US",), "las vegas": ("US",), "denver": ("US",), "phoenix": ("US",), "detroit": ("US",),
    "newark": ("US",), "washington dc": ("US",), "washington d.c.": ("US",), "district of columbia": ("US",),
    "mexico city": ("MX",), "guadalajara": ("MX",), "monterrey": ("MX",), "bogota": ("CO",), "medellin": ("CO",),
    "lima": ("PE",), "quito": ("EC",), "guayaquil": ("EC",), "caracas": ("VE",), "santiago": ("CL", "DO", "ES"),
    "buenos aires": ("AR",), "montevideo": ("UY",), "asuncion": ("PY",), "la paz": ("BO",),
    "sao paulo": ("BR",), "rio de janeiro": ("BR",), "brasilia": ("BR",), "havana": ("CU",),
    "kingston": ("JM", "CA", "GB"), "port-au-prince": ("HT",), "santo domingo": ("DO",), "panama city": ("PA", "US"),
    "san jose": ("CR", "US"), "guatemala city": ("GT",), "tegucigalpa": ("HN",), "managua": ("NI",),
    "san salvador": ("SV",), "san juan": ("PR",), "port of spain": ("TT",), "nassau": ("BS",),
    # US states (Georgia is left to the country table, which reads "Georgia, United States" as US)
    "alabama": ("US",), "alaska": ("US",), "arizona": ("US",), "arkansas": ("US",), "california": ("US",),
    "colorado": ("US",), "connecticut": ("US",), "delaware": ("US",), "florida": ("US",), "hawaii": ("US",),
    "idaho": ("US",), "illinois": ("US",), "indiana": ("US",), "iowa": ("US",), "kansas": ("US",),
    "kentucky": ("US",), "louisiana": ("US",), "maine": ("US",), "maryland": ("US",), "massachusetts": ("US",),
    "michigan": ("US",), "minnesota": ("US",), "mississippi": ("US",), "missouri": ("US",), "montana": ("US",),
    "nebraska": ("US",), "nevada": ("US",), "new hampshire": ("US",), "new mexico": ("US",),
    "north carolina": ("US",), "south carolina": ("US",), "north dakota": ("US",), "south dakota": ("US",),
    "ohio": ("US",), "oklahoma": ("US",), "oregon": ("US",), "pennsylvania": ("US",), "rhode island": ("US",),
    "tennessee": ("US",), "texas": ("US",), "utah": ("US",), "vermont": ("US",), "virginia": ("US",),
    "west virginia": ("US",), "wisconsin": ("US",), "wyoming": ("US",),
}


def _fold_keep(s: str) -> str:
    """Lower-case and strip accents one character at a time, so offsets match the original."""
    out = []
    for ch in s:
        base = next((c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)), ch)
        out.append(base.lower()[:1] or ch)
    return "".join(out)


_PLACE_RE = re.compile(
    r"(?<![\w])(" + "|".join(re.escape(k) for k in sorted(_PLACES, key=len, reverse=True)) + r")(?![\w])")


def places_in_text(text: str) -> tuple[list[str], list[str]]:
    """(countries settled by a place name, countries a place name only makes possible).
    A place counts only when it is written with a capital letter."""
    settled: list[str] = []
    possible: list[str] = []
    if not text:
        return settled, possible
    folded = _fold_keep(text)
    for m in _PLACE_RE.finditer(folded):
        if not text[m.start()].isupper():
            continue
        codes = _PLACES[m.group(1)]
        target = settled if len(codes) == 1 else possible
        for c in codes:
            if c not in target:
                target.append(c)
    return settled, [c for c in possible if c not in settled]


_PLACE_TOKEN_RE = re.compile(
    r"\b(?:in|to|from|near|within|inside|across|throughout)\s+(?:the\s+)?"
    r"([A-Z][A-Za-z\u00c0-\u024f'\u2019.-]+(?:\s+[A-Z][A-Za-z\u00c0-\u024f'\u2019.-]+){0,3})")
_NOT_PLACES = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "customer", "client", "user", "kyc", "sumsub", "veriff", "persona", "onfido", "jumio", "q1", "q2", "q3", "q4",
    "mr", "mrs", "ms", "dr", "i",
}


def has_unresolved_place(text: str) -> bool:
    """True when the text names a place ("in Springfield") that neither the
    country table nor the place table can turn into a country."""
    if not text:
        return False
    for m in _PLACE_TOKEN_RE.finditer(text):
        run = m.group(1).strip(" .")
        words = [w.strip(".,").lower() for w in run.split()]
        if all(w in _NOT_PLACES for w in words):
            continue
        if to_iso2(run) or codes_in_text(run):
            continue
        settled, possible = places_in_text(run)
        if settled or possible:
            continue
        return True
    return False
