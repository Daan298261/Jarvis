"""Direct owner commands only; quoted or document-contained text never activates policy."""
import re


def away_intent(text):
    normalized = (text or "").strip()
    if re.fullmatch(r"(?:hey(?: anzu)?[, ]+)?(?:i['’]m afk[, ]+go develop yourself|enable away mode(?:[,]? develop anzu)?|turn on away mode)[.!]?", normalized, re.I):
        return True
    if re.fullmatch(r"(?:i['’]m back|stop developing|turn off away mode)[.!]?", normalized, re.I):
        return False
    return None
