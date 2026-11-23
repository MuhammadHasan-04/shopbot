"""ShopBot guard rules: run BEFORE the model, cost 0 tokens.
Catches prompt injection and clearly off-topic requests. Borderline cases reach Claude,
whose system prompt also tells it to stay on shopping."""
import re

INJECTION = [
    r"ignore (all |any |the |your )?(previous|prior|above|earlier|system)? ?(instructions|prompts?|rules|directions)",
    r"disregard (all |any |the |your )?(previous|prior|above|system)? ?(instructions|prompts?|rules)",
    r"forget (all |your |the )?(previous |prior )?(instructions|rules|prompt)",
    r"\bforget everything\b", r"disregard (everything|the above|all of the above)",
    r"\b(override|bypass) (your |the )?(rules|instructions|safety|guardrails|filters?)\b",
    r"\b(new|updated) (rules?|instructions?|system prompt)\s*:",
    r"(repeat|print|show|reveal) (everything|all|the text) (above|before)",
    r"\bwhat were you told\b|\byour (initial|hidden|secret) (instructions|prompt|rules)\b",
    r"\b(no|without) (restrictions|filters|rules|limits)\b",
    r"(reveal|show|print|repeat|tell me|output|leak|display)( me)? (your|the) (system |hidden |initial |original )?(prompt|instructions|rules)",
    r"what (is|are) your (system )?(prompt|instructions)",
    r"\byou are now\b", r"\bpretend (to be|you are)\b", r"\bdeveloper mode\b", r"\bjailbreak\b", r"\bDAN\b",
    r"\bdo anything now\b", r"\bnew instructions\b", r"\bact as (a |an |my )?(dan|developer|admin|system|unrestricted|evil)\b",
    r"<\s*/?\s*(system|assistant|instructions?)\s*>", r"^\s*(system|admin)\s*:",
    r"\b(admin|developer|root) (mode|access|override)\b", r"\bi am (the|your) (admin|developer|owner|seller)\b",
    r"(api[_ ]?key|secret key|database (url|password)|env(ironment)? variables?)",
    r"(other|another|all|every) (users?|customers?|people)('s|’s|'|’)? (orders?|data|addresses|details|memory|carts?|info)",
    r"\b(set|change|make) (the |all )?(price|prices)\b.*\b(0|zero|free|1)\b",
    r"\bdrop table\b|\bdelete from\b|;\s*--|\bunion select\b",
]
OFF_TOPIC = [
    r"\b(write|create|generate|give me|make)\b.{0,25}\b(poem|essay|story|song|lyrics|joke|cover letter|resume|thesis)\b",
    r"\b(write|debug|fix|generate)\b.{0,25}\b(python|javascript|java|c\+\+|sql|html|css|program|script|function)\b",
    r"\b(homework|assignment|solve (this|the) (equation|problem)|integral|derivative)\b",
    r"\b(who (won|will win)|election|prime minister|president|politic)\w*\b",
    r"\b(recipe|biryani|weather forecast|horoscope|lottery|betting|crypto signals?|stock tips?)\b",
    r"\b(diagnos|symptom|medicine|dosage|prescription|legal advice)\w*\b",
    r"\b(hack|crack|malware|virus|phish|exploit|ddos|keylogger)\w*\b",
    r"\b(capital of|history of the|meaning of life|who invented)\b",
    r"\b(tell me a joke|weather (in|today|tomorrow|forecast)|what'?s the weather|translate (this|the following)|"
    r"solve|math problem|write (an? )?(email|letter|article|blog))\b",
    r"\b(bomb|weapon|gun|drugs?|kill|suicide)\b",
]
SHOP_WORDS = re.compile(
    r"\b(order|cart|buy|price|product|deliver|ship|return|refund|warrant|discount|code|coupon|stock|earbud|headphone|"
    r"speaker|charger|cable|power ?bank|case|watch|camera|mouse|keyboard|hub|plug|bulb|laptop|phone|pkr|rs)\w*\b", re.I)
HARD = re.compile(r"\b(hack|malware|phish|bomb|weapon|drugs?|kill|suicide|python|javascript|poem|essay|homework)\b", re.I)
INJ_RE = [re.compile(p, re.I) for p in INJECTION]
OFF_RE = [re.compile(p, re.I) for p in OFF_TOPIC]

REFUSE_INJECTION = ("I can't do that. I'm ShopBot, the TechTokri shopping assistant, and I only help with our "
                    "products, your cart and your own orders. What can I help you find today?")
REFUSE_OFF_TOPIC = ("Sorry, that's outside what I can help with. I'm ShopBot: I can find gadgets, compare products, "
                    "manage your cart, place orders and track them. What are you looking for?")


def check(message: str) -> str | None:
    """'injection' / 'off_topic' when the message must be refused, else None."""
    text = message or ""
    if any(r.search(text) for r in INJ_RE):
        return "injection"
    if any(r.search(text) for r in OFF_RE) and (HARD.search(text) or not SHOP_WORDS.search(text)):
        return "off_topic"
    return None


# Cheap long-term memory capture (no LLM call): obvious personal facts.
FACTS = [
    ("name", re.compile(r"\b(?i:my name is|call me|name'?s)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)")),
    ("name", re.compile(r"(?:^|[.!,]\s*)(?i:i'?m|i am|this is)\s+([A-Z][a-z]{2,})(?=\s*[,.!]|\s+(?:here|and|from)\b|$)")),
    ("phone", re.compile(r"\b(?:i use|i have|my phone is)\s+(?:an?\s+)?((?:iphone|samsung|galaxy|pixel|xiaomi|redmi|oppo|vivo|infinix|tecno|realme|oneplus)[\w\s]{0,15}?)(?=[,.!?]|\s+and\b|$)", re.I)),
    ("city", re.compile(r"\b(?:i live in|i'?m from|i am from|based in)\s+([A-Z][a-zA-Z]+)", re.I)),
    ("budget", re.compile(r"\bmy budget is\s+(?:around\s+|about\s+)?(?:rs\.?|pkr)?\s*([\d,]+k?)", re.I)),
    ("likes", re.compile(r"\bi (?:prefer|like|love|always buy|only buy|am a fan of)\s+([^.,!?]{3,50})", re.I)),
    ("dislikes", re.compile(r"\bi (?:hate|dislike|don'?t like|do not like|avoid)\s+([^.,!?]{3,50})", re.I)),
    ("favourite", re.compile(r"\bmy fav(?:ou?rite)? (?:brand|colou?r)\s+is\s+([^.,!?]{2,30})", re.I)),
]
NOT_NAMES = {"Looking", "Interested", "Trying", "Not", "Just", "Here", "Fine", "Good", "Back", "Sorry", "Using",
             "Buying", "Going", "From", "The", "Very", "Also", "Ready", "Done", "Happy", "Okay"}


def extract_facts(message: str) -> dict:
    found = {}
    for key, rx in FACTS:
        m = rx.search(message or "")
        if m and key not in found:
            val = m.group(1).strip().rstrip(".")
            if key == "name" and val.split()[0] in NOT_NAMES:
                continue
            found[key] = val
    return found
