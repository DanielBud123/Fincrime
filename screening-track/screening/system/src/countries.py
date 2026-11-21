"""Country normalisation: names, ISO codes and nationalities -> ISO alpha-2.

The files mix "United States", "US", "American", "Côte d'Ivoire" and
"Cote D'Ivoire"; hit fields such as nationality or place_of_birth may hold a
whole address ("Santa Prisca, Quito, Pichincha, Ecuador") where the country is
the last comma-separated part. Territories are their own country (Puerto Rico
is PR, not US). "International" and "Europe" are not countries.

No third-party packages (the system must run on the standard library).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

NOT_COUNTRIES = {"international", "europe", "european union", "eu", "worldwide", "global", "asia", "africa",
                 "middle east", "latin america", "north america", "south america", "oceania", "caribbean"}

# ISO2 -> display name used in reason text (the labels write "United States", "United Kingdom").
NAMES = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AS": "American Samoa", "AD": "Andorra", "AO": "Angola",
    "AI": "Anguilla", "AG": "Antigua and Barbuda", "AR": "Argentina", "AM": "Armenia", "AW": "Aruba", "AU": "Australia",
    "AT": "Austria", "AZ": "Azerbaijan", "BS": "Bahamas", "BH": "Bahrain", "BD": "Bangladesh", "BB": "Barbados",
    "BY": "Belarus", "BE": "Belgium", "BZ": "Belize", "BJ": "Benin", "BM": "Bermuda", "BT": "Bhutan", "BO": "Bolivia",
    "BA": "Bosnia and Herzegovina", "BW": "Botswana", "BR": "Brazil", "VG": "British Virgin Islands", "BN": "Brunei",
    "BG": "Bulgaria", "BF": "Burkina Faso", "BI": "Burundi", "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada",
    "CV": "Cape Verde", "KY": "Cayman Islands", "CF": "Central African Republic", "TD": "Chad", "CL": "Chile",
    "CN": "China", "CO": "Colombia", "KM": "Comoros", "CG": "Congo", "CD": "Democratic Republic of the Congo",
    "CK": "Cook Islands", "CR": "Costa Rica", "CI": "Cote D'Ivoire", "HR": "Croatia", "CU": "Cuba", "CW": "Curacao",
    "CY": "Cyprus", "CZ": "Czech Republic", "DK": "Denmark", "DJ": "Djibouti", "DM": "Dominica",
    "DO": "Dominican Republic", "EC": "Ecuador", "EG": "Egypt", "SV": "El Salvador", "GQ": "Equatorial Guinea",
    "ER": "Eritrea", "EE": "Estonia", "SZ": "Eswatini", "ET": "Ethiopia", "FK": "Falkland Islands", "FO": "Faroe Islands",
    "FJ": "Fiji", "FI": "Finland", "FR": "France", "GF": "French Guiana", "PF": "French Polynesia", "GA": "Gabon",
    "GM": "Gambia", "GE": "Georgia", "DE": "Germany", "GH": "Ghana", "GI": "Gibraltar", "GR": "Greece", "GL": "Greenland",
    "GD": "Grenada", "GP": "Guadeloupe", "GU": "Guam", "GT": "Guatemala", "GG": "Guernsey", "GN": "Guinea",
    "GW": "Guinea-Bissau", "GY": "Guyana", "HT": "Haiti", "HN": "Honduras", "HK": "Hong Kong", "HU": "Hungary",
    "IS": "Iceland", "IN": "India", "ID": "Indonesia", "IR": "Iran", "IQ": "Iraq", "IE": "Ireland", "IM": "Isle of Man",
    "IL": "Israel", "IT": "Italy", "JM": "Jamaica", "JP": "Japan", "JE": "Jersey", "JO": "Jordan", "KZ": "Kazakhstan",
    "KE": "Kenya", "KI": "Kiribati", "KP": "North Korea", "KR": "South Korea", "XK": "Kosovo", "KW": "Kuwait",
    "KG": "Kyrgyzstan", "LA": "Laos", "LV": "Latvia", "LB": "Lebanon", "LS": "Lesotho", "LR": "Liberia", "LY": "Libya",
    "LI": "Liechtenstein", "LT": "Lithuania", "LU": "Luxembourg", "MO": "Macao", "MG": "Madagascar", "MW": "Malawi",
    "MY": "Malaysia", "MV": "Maldives", "ML": "Mali", "MT": "Malta", "MH": "Marshall Islands", "MQ": "Martinique",
    "MR": "Mauritania", "MU": "Mauritius", "YT": "Mayotte", "MX": "Mexico", "FM": "Micronesia", "MD": "Moldova",
    "MC": "Monaco", "MN": "Mongolia", "ME": "Montenegro", "MS": "Montserrat", "MA": "Morocco", "MZ": "Mozambique",
    "MM": "Myanmar", "NA": "Namibia", "NR": "Nauru", "NP": "Nepal", "NL": "Netherlands", "NC": "New Caledonia",
    "NZ": "New Zealand", "NI": "Nicaragua", "NE": "Niger", "NG": "Nigeria", "NU": "Niue", "MK": "North Macedonia",
    "MP": "Northern Mariana Islands", "NO": "Norway", "OM": "Oman", "PK": "Pakistan", "PW": "Palau", "PS": "Palestine",
    "PA": "Panama", "PG": "Papua New Guinea", "PY": "Paraguay", "PE": "Peru", "PH": "Philippines", "PL": "Poland",
    "PT": "Portugal", "PR": "Puerto Rico", "QA": "Qatar", "RE": "Reunion", "RO": "Romania", "RU": "Russia", "RW": "Rwanda",
    "KN": "Saint Kitts and Nevis", "LC": "Saint Lucia", "VC": "Saint Vincent and the Grenadines", "WS": "Samoa",
    "SM": "San Marino", "ST": "Sao Tome and Principe", "SA": "Saudi Arabia", "SN": "Senegal", "RS": "Serbia",
    "SC": "Seychelles", "SL": "Sierra Leone", "SG": "Singapore", "SX": "Sint Maarten", "SK": "Slovakia", "SI": "Slovenia",
    "SB": "Solomon Islands", "SO": "Somalia", "ZA": "South Africa", "SS": "South Sudan", "ES": "Spain", "LK": "Sri Lanka",
    "SD": "Sudan", "SR": "Suriname", "SE": "Sweden", "CH": "Switzerland", "SY": "Syria", "TW": "Taiwan", "TJ": "Tajikistan",
    "TZ": "Tanzania", "TH": "Thailand", "TL": "Timor-Leste", "TG": "Togo", "TO": "Tonga", "TT": "Trinidad and Tobago",
    "TN": "Tunisia", "TR": "Turkey", "TM": "Turkmenistan", "TC": "Turks and Caicos Islands", "TV": "Tuvalu", "UG": "Uganda",
    "UA": "Ukraine", "AE": "United Arab Emirates", "GB": "United Kingdom", "US": "United States", "UY": "Uruguay",
    "UZ": "Uzbekistan", "VU": "Vanuatu", "VA": "Vatican City", "VE": "Venezuela", "VN": "Vietnam", "VI": "US Virgin Islands",
    "YE": "Yemen", "ZM": "Zambia", "ZW": "Zimbabwe",
}

# Alternative spellings and official names.
ALIASES = {
    "united states of america": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US", "america": "US", "the united states": "US",
    "united kingdom of great britain and northern ireland": "GB", "uk": "GB", "u.k.": "GB", "great britain": "GB",
    "britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB", "the united kingdom": "GB",
    "cote d'ivoire": "CI", "côte d'ivoire": "CI", "cote divoire": "CI", "ivory coast": "CI",
    "czechia": "CZ", "the netherlands": "NL", "holland": "NL", "russian federation": "RU",
    "korea, republic of": "KR", "republic of korea": "KR", "korea": "KR",
    "korea, democratic people's republic of": "KP", "democratic people's republic of korea": "KP", "dprk": "KP",
    "iran, islamic republic of": "IR", "islamic republic of iran": "IR", "syrian arab republic": "SY",
    "viet nam": "VN", "lao people's democratic republic": "LA", "burma": "MM", "swaziland": "SZ", "macau": "MO",
    "macao special administrative region of china": "MO", "macao sar": "MO", "hong kong sar": "HK",
    "palestina": "PS", "palestinian territory": "PS", "state of palestine": "PS", "west bank": "PS", "gaza": "PS",
    "uae": "AE", "emirates": "AE", "türkiye": "TR", "turkiye": "TR", "republic of moldova": "MD", "moldova, republic of": "MD",
    "bosnia": "BA", "bosnia & herzegovina": "BA", "macedonia": "MK", "republic of north macedonia": "MK",
    "dr congo": "CD", "drc": "CD", "congo, democratic republic of the": "CD", "congo-kinshasa": "CD", "congo-brazzaville": "CG",
    "republic of the congo": "CG", "tanzania, united republic of": "TZ", "cabo verde": "CV", "east timor": "TL",
    "the bahamas": "BS", "the gambia": "GM", "brunei darussalam": "BN", "st. lucia": "LC", "st lucia": "LC",
    "st. kitts and nevis": "KN", "st kitts and nevis": "KN", "st. vincent and the grenadines": "VC",
    "trinidad & tobago": "TT", "antigua & barbuda": "AG", "virgin islands, british": "VG", "virgin islands, u.s.": "VI",
    "united states virgin islands": "VI", "vatican": "VA", "holy see": "VA", "curaçao": "CW", "réunion": "RE",
    "south georgia": "GS", "new jersey": "US", "taiwan, province of china": "TW", "republic of china": "TW",
    "people's republic of china": "CN", "prc": "CN", "ussr": "RU", "soviet union": "RU",
}

# Nationalities / adjectives.
ADJECTIVES = {
    "afghan": "AF", "albanian": "AL", "algerian": "DZ", "american": "US", "andorran": "AD", "angolan": "AO",
    "argentine": "AR", "argentinian": "AR", "armenian": "AM", "australian": "AU", "austrian": "AT", "azerbaijani": "AZ",
    "bahamian": "BS", "bahraini": "BH", "bangladeshi": "BD", "barbadian": "BB", "belarusian": "BY", "belgian": "BE",
    "belizean": "BZ", "beninese": "BJ", "bhutanese": "BT", "bolivian": "BO", "bosnian": "BA", "botswanan": "BW",
    "brazilian": "BR", "british": "GB", "bruneian": "BN", "bulgarian": "BG", "burkinabe": "BF", "burmese": "MM",
    "burundian": "BI", "cambodian": "KH", "cameroonian": "CM", "canadian": "CA", "cape verdean": "CV", "chadian": "TD",
    "chilean": "CL", "chinese": "CN", "colombian": "CO", "comoran": "KM", "congolese": "CD", "costa rican": "CR",
    "croatian": "HR", "cuban": "CU", "cypriot": "CY", "czech": "CZ", "danish": "DK", "dane": "DK", "djiboutian": "DJ",
    "dominican": "DO", "dutch": "NL", "ecuadorian": "EC", "ecuadorean": "EC", "egyptian": "EG", "emirati": "AE",
    "english": "GB", "equatorial guinean": "GQ", "eritrean": "ER", "estonian": "EE", "ethiopian": "ET", "fijian": "FJ",
    "filipino": "PH", "filipina": "PH", "philippine": "PH", "finnish": "FI", "finn": "FI", "french": "FR", "gabonese": "GA",
    "gambian": "GM", "georgian": "GE", "german": "DE", "ghanaian": "GH", "greek": "GR", "grenadian": "GD", "guatemalan": "GT",
    "guinean": "GN", "guyanese": "GY", "haitian": "HT", "honduran": "HN", "hungarian": "HU", "icelandic": "IS",
    "indian": "IN", "indonesian": "ID", "iranian": "IR", "iraqi": "IQ", "irish": "IE", "israeli": "IL", "italian": "IT",
    "ivorian": "CI", "jamaican": "JM", "japanese": "JP", "jordanian": "JO", "kazakh": "KZ", "kazakhstani": "KZ",
    "kenyan": "KE", "kosovar": "XK", "kosovan": "XK", "kuwaiti": "KW", "kyrgyz": "KG", "lao": "LA", "laotian": "LA",
    "latvian": "LV", "lebanese": "LB", "liberian": "LR", "libyan": "LY", "liechtensteiner": "LI", "lithuanian": "LT",
    "luxembourgish": "LU", "luxembourger": "LU", "macedonian": "MK", "malagasy": "MG", "malawian": "MW", "malaysian": "MY",
    "maldivian": "MV", "malian": "ML", "maltese": "MT", "mauritanian": "MR", "mauritian": "MU", "mexican": "MX",
    "moldovan": "MD", "monegasque": "MC", "mongolian": "MN", "montenegrin": "ME", "moroccan": "MA", "mozambican": "MZ",
    "namibian": "NA", "nepalese": "NP", "nepali": "NP", "new zealander": "NZ", "nicaraguan": "NI", "nigerian": "NG",
    "nigerien": "NE", "north korean": "KP", "norwegian": "NO", "omani": "OM", "pakistani": "PK", "palestinian": "PS",
    "panamanian": "PA", "papua new guinean": "PG", "paraguayan": "PY", "peruvian": "PE", "polish": "PL", "pole": "PL",
    "portuguese": "PT", "puerto rican": "PR", "qatari": "QA", "romanian": "RO", "russian": "RU", "rwandan": "RW",
    "salvadoran": "SV", "saudi": "SA", "saudi arabian": "SA", "scottish": "GB", "senegalese": "SN", "serbian": "RS",
    "serb": "RS", "sierra leonean": "SL", "singaporean": "SG", "slovak": "SK", "slovakian": "SK", "slovenian": "SI",
    "slovene": "SI", "somali": "SO", "south african": "ZA", "south korean": "KR", "south sudanese": "SS", "spanish": "ES",
    "spaniard": "ES", "sri lankan": "LK", "sudanese": "SD", "surinamese": "SR", "swedish": "SE", "swede": "SE",
    "swiss": "CH", "syrian": "SY", "taiwanese": "TW", "tajik": "TJ", "tanzanian": "TZ", "thai": "TH", "togolese": "TG",
    "trinidadian": "TT", "tunisian": "TN", "turkish": "TR", "turk": "TR", "turkmen": "TM", "ugandan": "UG", "ukrainian": "UA",
    "uruguayan": "UY", "uzbek": "UZ", "venezuelan": "VE", "vietnamese": "VN", "welsh": "GB", "yemeni": "YE",
    "zambian": "ZM", "zimbabwean": "ZW", "korean": "KR",
}


def _fold(s: str) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.strip().lower())


_LOOKUP: dict[str, str] = {}
for code, name in NAMES.items():
    _LOOKUP[_fold(name)] = code
    _LOOKUP[code.lower()] = code
for alias, code in ALIASES.items():
    _LOOKUP[_fold(alias)] = code
for adj, code in ADJECTIVES.items():
    _LOOKUP[_fold(adj)] = code
# Two-letter codes that are also placeholders are not trusted as codes.
_LOOKUP.pop("na", None)
# Names, aliases and adjectives only (no codes): used when reading a token out of a longer phrase.
_LOOKUP_WORDS = {k: v for k, v in _LOOKUP.items() if len(k) > 2}

_BRACKET_SUFFIX_RE = re.compile(r"\s*\[[^\]]*\]\s*$")


def to_iso2(value: Optional[str]) -> Optional[str]:
    """One country-like field value -> ISO2, or None when it is not a country.

    Handles codes, names, nationalities, and "City, Region, Country" strings
    (the last comma-separated part is the country). A value that lists several
    places separated by ";" is handled by :func:`to_iso2_list`.
    """
    if not value:
        return None
    s = _BRACKET_SUFFIX_RE.sub("", str(value)).strip().strip(".;,")
    if not s:
        return None
    key = _fold(s)
    if key in NOT_COUNTRIES:
        return None
    if key in _LOOKUP:
        return _LOOKUP[key]
    if "," in s:
        last = s.rsplit(",", 1)[-1]
        return to_iso2(last)
    # "Nigerian national ID", "Republic of X" and similar: try a trailing or leading known token.
    words = key.replace("the ", "").split()
    for n in (3, 2, 1):
        if len(words) >= n:
            if " ".join(words[-n:]) in _LOOKUP_WORDS:
                return _LOOKUP_WORDS[" ".join(words[-n:])]
            if " ".join(words[:n]) in _LOOKUP_WORDS:
                return _LOOKUP_WORDS[" ".join(words[:n])]
    return None


def to_iso2_list(values: Iterable) -> list[str]:
    """Several field values (or one ';'-separated string) -> deduped ISO2 list."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        for part in re.split(r"\s*;\s*", str(v)):
            code = to_iso2(part)
            if code and code not in out:
                out.append(code)
    return out


def display(code: str) -> str:
    return NAMES.get(code, code)


# --- countries written inside free text (notes, snippets) --------------------
_TEXT_TERMS = sorted(
    {k for k in _LOOKUP if len(k) > 2 and k not in {"georgia", "jersey", "guinea", "niger", "dominica", "congo", "korea"}}
    | {"georgia", "jersey", "guinea", "niger", "dominica", "congo", "korea"},
    key=len, reverse=True)
_TEXT_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in _TEXT_TERMS) + r")(?![\w])", re.IGNORECASE)


def find_in_text(text: Optional[str]) -> list[tuple[str, str]]:
    """[(ISO2, matched text)] for every country, code-free, written in the text.
    Longest names win ("Papua New Guinea" before "Guinea"); 2-letter codes are
    never read out of prose. "New Jersey" is the US state, "Georgia" followed by
    ", United States" is the US state."""
    if not text:
        return []
    folded = _fold(text)
    out = []
    for m in _TEXT_RE.finditer(folded):
        term = m.group(1)
        code = _LOOKUP.get(term)
        if not code:
            continue
        if term == "georgia" and re.match(r"\s*,\s*(united states|usa|us)\b", folded[m.end():]):
            code = "US"
        if term == "jersey" and folded[max(0, m.start() - 4):m.start()].endswith("new "):
            code = "US"
        out.append((code, text[m.start():m.end()]))
    return out


def codes_in_text(text: Optional[str]) -> list[str]:
    out: list[str] = []
    for code, _ in find_in_text(text):
        if code not in out:
            out.append(code)
    return out
