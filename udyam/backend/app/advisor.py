"""Conversational needs discovery.

A deterministic state machine decides WHAT to ask and parses the answers. Gemini is used only to
(a) rescue an answer the parser could not read, (b) phrase the explanation and (c) translate fixed text.
If Gemini is down the whole journey still works in English and Hindi.
"""
from __future__ import annotations

import re

from . import llm
from .data import catalogue, city_tiers
from .registry import gstin_is_valid, lookup_gstin, mask
from .rules import SEGMENTS, Profile, eligibility, quote, recommend

DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUM_WORDS = {"ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4,
             "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8,
             "eight": 8, "nau": 9, "nine": 9, "das": 10, "ten": 10, "एक": 1, "दो": 2, "तीन": 3, "चार": 4,
             "पाँच": 5, "पांच": 5, "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10}

# ---------------------------------------------------------------- fixed text (en + hi; others are translated)
T = {
    "business_type": {
        "en": "Namaste! I'm Accel's business advisor. In a few questions I'll find the right internet, phone and "
              "security setup for you. What kind of business do you run?",
        "hi": "नमस्ते! मैं Accel का बिज़नेस सलाहकार हूँ। कुछ सवालों में मैं आपके लिए सही इंटरनेट, फ़ोन और सिक्योरिटी "
              "सेटअप चुन दूँगा। आप किस तरह का बिज़नेस चलाते हैं?",
    },
    "business_type_retry": {
        "en": "I didn't catch the type of business. For example: kirana store, salon, clinic, CA office, "
              "restaurant chain or factory.",
        "hi": "बिज़नेस का प्रकार समझ नहीं आया। जैसे: किराना दुकान, सैलून, क्लिनिक, CA ऑफ़िस, रेस्तरां चेन या फैक्ट्री।",
    },
    "employees": {
        "en": "Got it. How many people work in your business, including you?",
        "hi": "ठीक है। आपको मिलाकर आपके बिज़नेस में कितने लोग काम करते हैं?",
    },
    "employees_retry": {"en": "Please tell me a number, like 1, 5 or 12.", "hi": "कृपया संख्या बताइए, जैसे 1, 5 या 12।"},
    "sites": {
        "en": "How many locations (shops, branches or units) do you run?",
        "hi": "आप कितनी जगहों (दुकान, ब्रांच या यूनिट) से काम करते हैं?",
    },
    "sites_retry": {"en": "Please tell me a number of locations, like 1 or 4.", "hi": "कृपया जगहों की संख्या बताइए, जैसे 1 या 4।"},
    "city": {"en": "Which city is the business in?", "hi": "आपका बिज़नेस किस शहर में है?"},
    "internet": {
        "en": "What do you use for internet today?",
        "hi": "अभी आप इंटरनेट के लिए क्या इस्तेमाल करते हैं?",
    },
    "internet_retry": {"en": "Please pick one of the options below.", "hi": "कृपया नीचे दिए विकल्पों में से चुनिए।"},
    "gstin": {
        "en": "Last one: do you have a GSTIN? If yes, type it and I'll check it instantly. This unlocks extra "
              "products such as WhatsApp Business API, cloud telephony and firewall. If not, just say no.",
        "hi": "आख़िरी सवाल: क्या आपके पास GSTIN है? है तो लिख दीजिए, मैं तुरंत जाँच लूँगा। इससे WhatsApp Business API, "
              "क्लाउड टेलीफ़ोनी और फ़ायरवॉल जैसे प्रोडक्ट मिलते हैं। नहीं है तो बस 'नहीं' लिख दीजिए।",
    },
    "gstin_retry": {
        "en": "That GSTIN did not check out (format or checksum). Please re-type it, or say 'no' to continue without it.",
        "hi": "यह GSTIN जाँच में सही नहीं निकला। कृपया दोबारा लिखिए, या बिना GSTIN आगे बढ़ने के लिए 'नहीं' लिखिए।",
    },
    "gstin_notfound": {
        "en": "This GSTIN is valid in format but I cannot find it in the registry. Re-type it, or say 'no' to continue without it.",
        "hi": "GSTIN का फ़ॉर्मेट सही है पर रजिस्ट्री में नहीं मिला। दोबारा लिखिए, या बिना GSTIN आगे बढ़ने के लिए 'नहीं' लिखिए।",
    },
    "handoff": {
        "en": "Of course. I've flagged this for a human advisor, who will call you within a working day. "
              "You can keep going here meanwhile.",
        "hi": "ज़रूर। मैंने इसे एक ह्यूमन सलाहकार को भेज दिया है, वे एक कार्यदिवस में आपको कॉल करेंगे। "
              "तब तक आप यहाँ आगे बढ़ सकते हैं।",
    },
}
CHIPS = {
    "business_type": {"en": ["Kirana store", "Clinic", "Chain of stores", "Factory"],
                      "hi": ["किराना दुकान", "क्लिनिक", "स्टोर चेन", "फैक्ट्री"]},
    "employees": {"en": ["Just me", "2-5", "6-10", "11-25"], "hi": ["सिर्फ़ मैं", "2-5", "6-10", "11-25"]},
    "sites": {"en": ["1", "2", "3-5", "6+"], "hi": ["1", "2", "3-5", "6+"]},
    "city": {"en": ["Mumbai", "Delhi", "Nagpur", "Jaipur"], "hi": ["मुंबई", "दिल्ली", "नागपुर", "जयपुर"]},
    "internet": {"en": ["Mobile hotspot", "Home broadband", "Business broadband", "Leased line", "Mixed per site"],
                 "hi": ["Mobile hotspot", "Home broadband", "Business broadband", "Leased line", "Mixed per site"]},
    "gstin": {"en": ["No GSTIN"], "hi": ["नहीं"]},
    "after": {"en": ["Looks good, continue", "Make it cheaper", "Add CCTV", "Talk to a human"],
              "hi": ["ठीक है, आगे बढ़ें", "सस्ता करें", "CCTV जोड़ें", "ह्यूमन से बात करें"]},
}


def t(key: str, lang: str) -> str:
    row = T[key]
    return row.get(lang) or llm.translate(row["en"], lang)


def chips(key: str, lang: str) -> list[str]:
    row = CHIPS[key]
    return row.get(lang) or row["en"]


# ---------------------------------------------------------------- parsers
def _norm(text: str) -> str:
    return (text or "").translate(DEV_DIGITS).lower().strip()


def parse_segment(text: str) -> tuple[str | None, str]:
    s = _norm(text)
    if re.search(r"chain|outlet|branch|franchise|multiple (shops|stores|locations)|स्टोर चेन|चेन|ब्रांच|आउटलेट", s):
        return "multi", "multi-site business"
    if re.search(r"factory|manufactur|workshop|plant|\bmill\b|fabricat|production|textile|auto part|फैक्ट्री|कारखाना|मैन्युफ", s):
        return "mfg", "manufacturing unit"
    if re.search(r"clinic|doctor|dental|dentist|physio|diagnostic|\blab\b|\bca\b|chartered|accountant|consult|"
                 r"lawyer|legal|advocate|coaching|tuition|institute|academy|architect|insurance|travel|studio|"
                 r"agency|office|क्लिनिक|डॉक्टर|कोचिंग|वकील|ऑफ़िस|ऑफिस", s):
        return "prof", "professional office"
    if re.search(r"kirana|grocery|store|shop|salon|parlou?r|pharmacy|medical|chemist|bakery|cafe|restaurant|"
                 r"tea|vendor|boutique|tailor|repair|retail|दुकान|किराना|सैलून|मेडिकल|रेस्तरां|होटल", s):
        return "micro", "small shop or service"
    return None, ""


def parse_int(text: str, allow_range_low: bool = True) -> int | None:
    s = _norm(text)
    if re.search(r"just me|only me|alone|akela|akele|myself|सिर्फ़ मैं|सिर्फ मैं|अकेला", s):
        return 1
    m = re.search(r"(\d+)\s*[-–to]+\s*(\d+)", s)
    if m and allow_range_low:
        return int(m.group(1))
    m = re.search(r"\d+", s)
    if m:
        return int(m.group())
    for w, n in NUM_WORDS.items():
        if re.search(rf"\b{re.escape(w)}\b", s) or (not w.isascii() and w in s):
            return n
    return None


CITY_ALIASES = {"bangalore": "bengaluru", "bombay": "mumbai", "calcutta": "kolkata", "vizag": "visakhapatnam",
                "मुंबई": "mumbai", "दिल्ली": "delhi", "नागपुर": "nagpur", "जयपुर": "jaipur", "पुणे": "pune",
                "लखनऊ": "lucknow", "चेन्नई": "chennai", "कोलकाता": "kolkata", "हैदराबाद": "hyderabad",
                "अहमदाबाद": "ahmedabad", "सूरत": "surat", "भोपाल": "bhopal", "इंदौर": "indore", "पटना": "patna",
                "बेंगलुरु": "bengaluru", "कोच्चि": "kochi", "वडोदरा": "vadodara", "लुधियाना": "ludhiana"}


def parse_city(text: str) -> tuple[str | None, int | None]:
    s = _norm(text)
    for alias, city in CITY_ALIASES.items():
        if alias in s:
            return city, city_tiers()[city]
    for city, tier in city_tiers().items():
        if re.search(rf"\b{re.escape(city)}\b", s):
            return city, tier
    return None, None


def parse_internet(text: str) -> str | None:
    s = _norm(text)
    if re.search(r"leased", s):
        return "Leased line"
    if re.search(r"mixed|each site|different|per site", s):
        return "Mixed per site"
    if re.search(r"hotspot|mobile|phone|data|nothing|no internet|none|नहीं|कुछ नहीं", s):
        return "Mobile hotspot"
    if re.search(r"home", s):
        return "Home broadband"
    if re.search(r"business|office|fibre|fiber|broadband|wifi|wi-fi|jio|airtel|act\b", s):
        return "Business broadband"
    return None


GSTIN_IN_TEXT = re.compile(r"\b\d{2}[A-Z0-9]{10}[A-Z0-9]Z[A-Z0-9]\b|\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
SAY_NO = re.compile(r"\b(no|nope|none|don'?t|do not|dont|nahi|nahin|skip|later|not yet|na)\b|नहीं|नही|नो", re.I)

# keyword -> product id. Longer phrases first.
PRODUCT_WORDS = [
    (r"1\s?g\b|gigabit|1 gbps|1gbps", "P03"), (r"leased line|dedicated line|\bill\b", "P05"),
    (r"air ?fiber|5g fwa|wireless broadband", "P04"), (r"sd-?wan", "P10"), (r"fail ?over|backup link|backup internet", "P09"),
    (r"static ip|fixed ip", "P11"), (r"cloud telephony|\bsip\b|\bivr\b|business phone", "P12"),
    (r"toll[- ]?free|1800", "P13"), (r"\bsms\b", "P14"), (r"whatsapp", "P15"),
    (r"e-?mail|office suite|gmail|google workspace", "P16"), (r"cloud backup|data backup", "P17"),
    (r"website|domain", "P18"), (r"\bpos\b|billing|point of sale", "P19"), (r"antivirus|endpoint|ransomware", "P20"),
    (r"firewall", "P21"), (r"wi-?fi|guest network", "P22"), (r"cctv|camera", "P23"),
    (r"machine monitor|\biot\b", "P24"), (r"fleet|gps|vehicle tracker", "P25"),
    (r"postpaid|\bsim\b|mobile plan|business line", "P07"),
]
WANT_BY_PRODUCT = {"P23": "cctv", "P19": "pos", "P15": "whatsapp", "P18": "website", "P22": "wifi", "P12": "phone",
                   "P13": "tollfree", "P24": "iot", "P25": "fleet", "P17": "backup", "P16": "email", "P21": "security",
                   "P14": "sms"}


def find_products(text: str) -> list[str]:
    s = _norm(text)
    out: list[str] = []
    for pat, pid in PRODUCT_WORDS:
        if re.search(pat, s) and pid not in out:
            out.append(pid)
    return out


# ---------------------------------------------------------------- profile <-> session
def to_profile(d: dict) -> Profile:
    return Profile(segment=d.get("segment", "micro"), employees=int(d.get("employees", 1)),
                   sites=int(d.get("sites", 1)), city_tier=int(d.get("city_tier", 1)),
                   has_valid_gstin=bool(d.get("has_valid_gstin", False)),
                   current_internet=d.get("current_internet", ""), language=d.get("language", "en"),
                   wants=set(d.get("wants", [])))


def build_recommendation(profile: dict, term: int = 12) -> dict:
    p = to_profile(profile)
    rec = recommend(p)
    cat = catalogue()
    q = quote(rec["items"], p, term)
    q24 = quote(rec["items"], p, 24)
    for it in rec["items"]:
        it["name"] = cat[it["product_id"]].name
        it["unit"] = cat[it["product_id"]].unit
    return {"items": rec["items"], "excluded": rec["excluded"], "quote": q,
            "saving_with_24_months": max(0, q["monthly_subtotal"] - q24["monthly_subtotal"]),
            "segment_label": SEGMENTS[p.segment], "term": term}


def _facts(profile: dict, rec: dict) -> dict:
    return {
        "business": f"{rec['segment_label']}, {profile.get('employees')} people, {profile.get('sites', 1)} site(s), "
                    f"Tier {profile.get('city_tier')} city, currently on {profile.get('current_internet') or 'unknown'}",
        "has_valid_gstin": profile.get("has_valid_gstin", False),
        "recommended": [{"product": i["name"], "qty": i["qty"], "unit": i["unit"], "why": i["why"]}
                        for i in rec["items"] if i["included"]],
        "optional_not_included": [{"product": i["name"], "why": i["why"]} for i in rec["items"] if not i["included"]],
        "not_available": [e["reason"] for e in rec["excluded"]],
        "monthly_total_incl_gst_inr": rec["quote"]["monthly_total"],
        "one_time_setup_incl_gst_inr": rec["quote"]["setup_total"],
        "commitment_months": rec["term"],
        "monthly_saving_if_24_months_inr": rec["saving_with_24_months"],
        "install_days": rec["quote"]["install_days"],
    }


def _fallback_explanation(profile: dict, rec: dict, lang: str) -> str:
    names = ", ".join(f"{i['name']}" + (f" x{i['qty']}" if i["qty"] > 1 else "") for i in rec["items"] if i["included"])
    q = rec["quote"]
    if lang == "hi":
        return (f"आपके {rec['segment_label']} के लिए मेरा सुझाव: {names}। कुल ₹{q['monthly_total']:,} प्रति माह (GST सहित), "
                f"एक बार का सेटअप ₹{q['setup_total']:,}। लगभग {q['install_days']} दिन में चालू। "
                f"24 महीने के कॉन्ट्रैक्ट पर लगभग ₹{rec['saving_with_24_months']:,} प्रति माह बचेंगे।")
    return (f"For your {rec['segment_label'].lower()} I suggest: {names}. That is ₹{q['monthly_total']:,} a month "
            f"including GST, with a one-time setup of ₹{q['setup_total']:,}, live in about {q['install_days']} days. "
            f"A 24-month commitment would save about ₹{rec['saving_with_24_months']:,} a month.")


def explain(profile: dict, rec: dict, lang: str) -> str:
    return llm.explain(_facts(profile, rec), lang) or _fallback_explanation(profile, rec, lang)


# ---------------------------------------------------------------- the state machine
FLOW = ["business_type", "employees", "sites", "city", "internet", "gstin", "done"]


def _next_step(step: str, profile: dict) -> str:
    i = FLOW.index(step) + 1
    nxt = FLOW[i]
    if nxt == "sites" and profile.get("segment") != "multi":
        profile["sites"] = 1
        nxt = FLOW[i + 1]
    return nxt


def opening(lang: str) -> dict:
    return {"reply": t("business_type", lang), "chips": chips("business_type", lang), "step": "business_type",
            "done": False, "profile": {}, "recommendation": None, "action": None}


def _ask(step: str, lang: str, prefix: str = "") -> dict:
    return {"reply": (prefix + " " if prefix else "") + t(step, lang), "chips": chips(step, lang), "step": step,
            "done": False, "action": None}


def handle(session, text: str) -> dict:
    """Mutates session.profile / step / extra and returns the response payload."""
    lang = session.language
    profile = dict(session.profile or {})
    extra = dict(session.extra or {})
    step = session.step
    text = (text or "").strip()[:500]

    def finish(resp: dict) -> dict:
        session.profile, session.extra, session.step = profile, extra, resp["step"]
        resp["profile"] = profile
        resp.setdefault("recommendation", None)
        return resp

    if step == "business_type":
        seg, label = parse_segment(text)
        if not seg and llm.available():
            data = llm.extract_json(
                'Classify the Indian small business into one of: "micro" (shop, salon, pharmacy, restaurant), '
                '"prof" (clinic, CA, lawyer, coaching), "multi" (chain or several branches), "mfg" (factory). '
                'Reply JSON {"segment": "<one of those or null>"}.', text)
            if data and data.get("segment") in SEGMENTS:
                seg, label = data["segment"], SEGMENTS[data["segment"]].lower()
        if not seg:
            return finish({**_ask("business_type", lang), "reply": t("business_type_retry", lang)})
        profile.update(segment=seg, language=lang, biz_label=label)
        n = parse_int(text)
        if n and re.search(r"\d+\s*(people|staff|employees|workers|log)", _norm(text)):
            profile["employees"] = n
        # an owner who already said "clinic with 5 staff" does not need to be asked again
        return finish(_advance(profile, "employees" if "employees" in profile else "business_type", lang))

    if step == "employees":
        n = parse_int(text)
        if n is None or n < 1:
            return finish({**_ask("employees", lang), "reply": t("employees_retry", lang)})
        profile["employees"] = min(n, 500)
        return finish(_advance(profile, "employees", lang))

    if step == "sites":
        n = parse_int(text)
        if "6+" in text:
            n = 6
        if n is None or n < 1:
            return finish({**_ask("sites", lang), "reply": t("sites_retry", lang)})
        profile["sites"] = min(n, 100)
        return finish(_advance(profile, "sites", lang))

    if step == "city":
        city, tier = parse_city(text)
        if not city:
            # unknown city: assume Tier 2 (the stricter product set) and say so
            profile.update(city=text[:40].title(), city_tier=2, city_assumed=True)
        else:
            profile.update(city=city.title(), city_tier=tier, city_assumed=False)
        return finish(_advance(profile, "city", lang))

    if step == "internet":
        net = parse_internet(text)
        if not net:
            return finish({**_ask("internet", lang), "reply": t("internet_retry", lang)})
        profile["current_internet"] = net
        return finish(_advance(profile, "internet", lang))

    if step == "gstin":
        m = GSTIN_IN_TEXT.search(text.upper().replace(" ", ""))
        if m:
            g = m.group()
            if not gstin_is_valid(g):
                return finish({**_ask("gstin", lang), "reply": t("gstin_retry", lang)})
            row = lookup_gstin(g)
            if not row:
                return finish({**_ask("gstin", lang), "reply": t("gstin_notfound", lang)})
            extra["gstin_masked"] = mask(g)
            extra["gstin_status"] = row["status"]
            extra["trade_name"] = row["trade_name"]
            profile["has_valid_gstin"] = row["status"] == "Active"
            if row["status"] == "Active":
                note = (f"Verified: {row['trade_name']} ({mask(g)}), Active." if lang != "hi"
                        else f"सत्यापित: {row['trade_name']} ({mask(g)}), सक्रिय।")
            else:
                note = (f"I found {row['trade_name']} ({mask(g)}) but the registry shows it as {row['status']}, so "
                        "I'll leave out products that need GST. You can fix this later and add them." if lang != "hi"
                        else f"{row['trade_name']} ({mask(g)}) मिला, पर रजिस्ट्री में यह {row['status']} है, इसलिए GST वाले "
                             "प्रोडक्ट छोड़ रहा हूँ। ठीक करवाकर बाद में जोड़ सकते हैं।")
            return finish(_recommend_response(profile, extra, lang, prefix=note))
        if SAY_NO.search(text) or "no gstin" in _norm(text):
            profile["has_valid_gstin"] = False
            return finish(_recommend_response(profile, extra, lang))
        if re.search(r"\byes\b|\bhaan\b|\bha\b|हाँ|हां", _norm(text)):
            return finish({**_ask("gstin", lang), "reply": "Please type the 15-character GSTIN." if lang != "hi"
                           else "कृपया 15 अक्षरों का GSTIN लिखिए।"})
        return finish({**_ask("gstin", lang), "reply": t("gstin_retry", lang)})

    return finish(_after_recommendation(profile, extra, text, lang))


def _advance(profile: dict, step: str, lang: str) -> dict:
    nxt = _next_step(step, profile)
    return _ask(nxt, lang)


def _recommend_response(profile: dict, extra: dict, lang: str, prefix: str = "") -> dict:
    rec = build_recommendation(profile, extra.get("term", 12))
    text = explain(profile, rec, lang)
    return {"reply": (prefix + "\n\n" if prefix else "") + text, "chips": chips("after", lang), "step": "done",
            "done": True, "recommendation": rec, "action": None}


def _after_recommendation(profile: dict, extra: dict, text: str, lang: str) -> dict:
    s = _norm(text)
    cat = catalogue()
    if re.search(r"human|agent|advisor|call me|talk to|सलाहकार|ह्यूमन|कॉल", s) and not find_products(text):
        extra["handoff"] = True
        r = _recommend_response(profile, extra, lang)
        r["reply"] = t("handoff", lang)
        r["chips"] = chips("after", lang)
        r["action"] = "handoff"
        return r
    if re.search(r"continue|proceed|checkout|go ahead|looks good|\bok\b|okay|yes|haan|theek|ठीक|आगे|हाँ", s) \
            and not find_products(text):
        r = _recommend_response(profile, extra, lang)
        r["reply"] = "Great, let's get you set up." if lang != "hi" else "बहुत बढ़िया, चलिए शुरू करते हैं।"
        r["action"] = "checkout"
        return r
    if re.search(r"cheap|cheaper|budget|afford|expensive|costly|too much|sasta|sasti|सस्त|महंग", s) \
            and not find_products(text):
        extra["term"] = 24
        profile["wants"] = []
        r = _recommend_response(profile, extra, lang)
        r["reply"] = ("I switched to a 24-month commitment, which gives the lowest price for each product, and "
                      "kept only the essentials ticked. " if lang != "hi" else
                      "मैंने 24 महीने का कॉन्ट्रैक्ट चुना है जिसमें हर प्रोडक्ट सबसे सस्ता है, और सिर्फ़ ज़रूरी चीज़ें रखी हैं। ") + \
                     _fallback_explanation(profile, r["recommendation"], lang)
        return r

    pids = find_products(text)
    if pids:
        p = to_profile(profile)
        rec = recommend(p)
        in_bundle = {i["product_id"] for i in rec["items"]}
        msgs = []
        for pid in pids:
            prod = cat[pid]
            ok, reasons = eligibility(prod, p, in_bundle | {pid})
            if ok and pid in WANT_BY_PRODUCT:
                profile.setdefault("wants", [])
                if WANT_BY_PRODUCT[pid] not in profile["wants"]:
                    profile["wants"] = [*profile["wants"], WANT_BY_PRODUCT[pid]]
                msgs.append(f"{prod.name} is available for you and I've added it." if lang != "hi"
                            else f"{prod.name} आपके लिए उपलब्ध है और मैंने इसे जोड़ दिया है।")
            elif ok:
                msgs.append(f"{prod.name} is available for you. Tick it in the next step if you want it." if lang != "hi"
                            else f"{prod.name} आपके लिए उपलब्ध है। चाहें तो अगले चरण में चुन लीजिए।")
            else:
                alt = _alternative(prod, p, in_bundle)
                why = reasons[0]
                msgs.append((f"Sorry, {why}." + (f" The closest option for you is {alt.name}." if alt else ""))
                            if lang != "hi" else (f"क्षमा करें, {why}।" + (f" आपके लिए सबसे नज़दीकी विकल्प {alt.name} है।" if alt else "")))
        r = _recommend_response(profile, extra, lang)
        r["reply"] = " ".join(msgs)
        return r

    facts = _facts(profile, build_recommendation(profile, extra.get("term", 12)))
    ans = llm.answer(text, facts, lang)
    r = _recommend_response(profile, extra, lang)
    r["reply"] = ans or ("I can change the bundle, make it cheaper, add a product, or hand you to a human "
                         "advisor. What would you like?" if lang != "hi" else
                         "मैं बंडल बदल सकता हूँ, सस्ता कर सकता हूँ, कोई प्रोडक्ट जोड़ सकता हूँ या ह्यूमन सलाहकार से जोड़ सकता हूँ।")
    return r


def _alternative(prod, p: Profile, bundle_ids: set[str]):
    """Closest eligible product in the same category (cheapest first)."""
    cat = catalogue()
    cands = [c for c in cat.values() if c.category == prod.category and c.id != prod.id
             and eligibility(c, p, bundle_ids)[0]]
    if prod.category == "Connectivity":
        cands = [c for c in cands if c.unit == prod.unit and c.requires_one_of == ()]
        cands.sort(key=lambda c: -c.price_min)  # nearest step down in capability
    else:
        cands.sort(key=lambda c: c.price_min)
    return cands[0] if cands else None
