"""langcodes.py - the plugin's single source of language codes (stdlib only).

A leaf module (no imports): a curated map of common language NAMES to their
ISO-639-1 codes, plus the derived set of valid codes (incl. "und"). The same
data drives the triage schema's `enum` (so the model can only return codes we
know) and the learning-language code lookup (debrief.py), replacing the old
per-run LLM resolution. This is a generic standard reference, not "the target
language" — adding a language is a one-line edit. such input tags as "und"."""

# Lowercased language NAME -> ISO-639-1 code. English names plus a few common
# autonyms. Extend with one line per language as learners need them.
NAME_TO_CODE = {
    "english": "en",
    "ukrainian": "uk",
    "українська": "uk",
    "spanish": "es",
    "español": "es",
    "german": "de",
    "deutsch": "de",
    "french": "fr",
    "français": "fr",
    "italian": "it",
    "portuguese": "pt",
    "português": "pt",
    "dutch": "nl",
    "polish": "pl",
    "czech": "cs",
    "slovak": "sk",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "greek": "el",
    "turkish": "tr",
    "romanian": "ro",
    "hungarian": "hu",
    "bulgarian": "bg",
    "croatian": "hr",
    "serbian": "sr",
    "slovenian": "sl",
    "lithuanian": "lt",
    "latvian": "lv",
    "estonian": "et",
    "arabic": "ar",
    "hebrew": "he",
    "hindi": "hi",
    "bengali": "bn",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "vietnamese": "vi",
    "thai": "th",
    "indonesian": "id",
    "malay": "ms",
    "persian": "fa",
    "farsi": "fa",
    "urdu": "ur",
    "tamil": "ta",
    "georgian": "ka",
    "armenian": "hy",
    "kazakh": "kk",
    "azerbaijani": "az",
    "catalan": "ca",
    "irish": "ga",
    "welsh": "cy",
}

# Valid codes for triage: every code we can name, plus "und" (no judgeable prose).
CODES = frozenset(NAME_TO_CODE.values()) | {"und"}
