# ruff: noqa: E501
"""What to ask about each track, and how to notice a student's interest in it.

The backend sends the tracks (code, name, profile) with every request. For the tracks we know,
this module adds:

* ``probes``   - concrete angles for DEEP questions (a real situation or a "would you rather"),
                 not "what do you like?". The model picks one that was not asked yet.
* ``keywords`` - words (English + Arabic/Egyptian) that, when the student says them, show interest.
                 They only decide WHICH track to dig into next; the final ranking is still the
                 result step's job.

An unknown track still works: its deep question is built from the profile the backend sent.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.common import QA, Track


@dataclass(frozen=True)
class TrackKnowledge:
    key: str
    aliases: tuple[str, ...]  # normalised codes / names that map to this track
    what_it_is: str  # one line for the model (not for the student)
    probes: tuple[str, ...]  # deep angles, in English instructions for the model
    keywords: tuple[str, ...]  # English words (matched as whole words) + Arabic stems (substring)


TRACKS_KNOWLEDGE: tuple[TrackKnowledge, ...] = (
    TrackKnowledge(
        key="frontend",
        aliases=("frontend", "front", "web", "webdev", "frontenddeveloper", "webdevelopment"),
        what_it_is="building the parts of websites and apps that people see and click",
        probes=(
            "Noticing screens: when they open a website or app, do they notice the buttons, colours, "
            "menus or little animations, and do they ever think 'I would change this'? Ask what exactly they would change.",
            "Instant result: would they enjoy making a page and seeing the change on screen immediately "
            "(a button that changes colour when pressed) and keep adjusting sizes and colours until it looks right?",
            "Interaction: do they like making something react (press a button and something happens, "
            "like a quiz, a counter or a like button)? Ask them to imagine one they would build.",
            "Thinking: a friend says the school's website is hard to read on a phone. Ask what they would "
            "look at first and what they would change to make it nicer.",
        ),
        keywords=(
            "website",
            "web",
            "page",
            "button",
            "colors",
            "colours",
            "animation",
            "html",
            "css",
            "javascript",
            "frontend",
            "layout",
            "interface",
            "موقع",
            "مواقع",
            "صفحه",
            "صفحة",
            "زرار",
            "ازرار",
            "الوان",
            "ألوان",
            "انيميشن",
            "واجهه",
            "واجهة",
        ),
    ),
    TrackKnowledge(
        key="backend",
        aliases=("backend", "back", "server", "backenddeveloper", "serverside"),
        what_it_is="building the hidden engine of apps: logic, rules, storing and moving information",
        probes=(
            "Behind the scenes: do they wonder what happens when they press 'login', 'send' or 'order' "
            "(where the information goes, how the app remembers them)? Ask what they imagine happens.",
            "Rules and steps: do they enjoy thinking in rules ('if this, then that'), like the rules of a game, "
            "a vending machine or a school schedule? Ask them to explain one rule system they know.",
            "Keeping things organised: would they enjoy keeping information in order "
            "(a list of players and their scores, a library of books) so it can be found quickly?",
            "Thinking: how would they keep track of who borrowed which book from a class library? "
            "Ask what they would write down and what could go wrong (two students want the same book).",
        ),
        keywords=(
            "backend",
            "server",
            "database",
            "login",
            "logic",
            "rules",
            "system",
            "api",
            "python",
            "code",
            "سيرفر",
            "قاعده بيانات",
            "قاعدة بيانات",
            "منطق",
            "قواعد",
            "نظام",
            "تسجيل دخول",
            "برمجه",
            "برمجة",
        ),
    ),
    TrackKnowledge(
        key="uiux",
        aliases=("uiux", "ux", "ui", "uxui", "design", "uidesign", "uxdesign", "productdesign"),
        what_it_is="designing how apps look and feel, and making them easy and pleasant to use",
        probes=(
            "Frustration: has an app, game or website ever confused or annoyed them? "
            "Ask what was confusing and how they would make it easier.",
            "Other people: would they enjoy imagining how a grandparent or a younger child would use an app, "
            "and designing it for them? Ask who they would design for and why.",
            "Sketching: do they like sketching a screen on paper first (where the buttons go, which colours "
            "and icons) before building anything? Ask them to describe a screen they would sketch.",
            "Thinking: a new student cannot find the cafeteria using the school map. Ask how they would "
            "change the map so anyone finds it fast.",
        ),
        keywords=(
            "design",
            "draw",
            "drawing",
            "sketch",
            "ui",
            "ux",
            "colors",
            "colours",
            "logo",
            "icons",
            "canva",
            "figma",
            "photoshop",
            "poster",
            "تصميم",
            "ديزاين",
            "رسم",
            "ارسم",
            "أرسم",
            "فوتوشوب",
            "كانفا",
            "لوجو",
            "شعار",
            "بوستر",
        ),
    ),
    TrackKnowledge(
        key="data",
        aliases=("data", "datascience", "dataanalysis", "dataanalytics", "analytics", "datascientist"),
        what_it_is="finding patterns in numbers and explaining them with charts",
        probes=(
            "Numbers they follow: do they follow numbers about something they love (football stats, game scores, "
            "video views)? Ask which numbers and what they noticed in them.",
            "Why questions: do they like checking a guess with evidence "
            "(which game do most friends play, and why?)? Ask how they would find out.",
            "Charts: would they enjoy turning a pile of numbers into a chart that tells a story? "
            "Ask what they would make a chart about.",
            "Thinking: they want to know which snack is the most popular at school. Ask how they would "
            "find out and how they would show the answer to friends.",
        ),
        keywords=(
            "data",
            "numbers",
            "statistics",
            "stats",
            "chart",
            "graph",
            "excel",
            "pattern",
            "patterns",
            "survey",
            "math",
            "maths",
            "analysis",
            "بيانات",
            "داتا",
            "ارقام",
            "أرقام",
            "احصائيات",
            "إحصائيات",
            "رسم بياني",
            "اكسل",
            "إكسل",
            "حساب",
            "رياضيات",
            "نمط",
            "انماط",
            "أنماط",
        ),
    ),
    TrackKnowledge(
        key="mobile",
        aliases=(
            "mobile",
            "mobileapps",
            "mobiledev",
            "mobiledevelopment",
            "android",
            "ios",
            "apps",
            "appdev",
        ),
        what_it_is="building apps for phones",
        probes=(
            "Daily apps: which phone app do they use the most, and what one thing would they add "
            "or change in it? Ask for the exact feature.",
            "Own app idea: is there a small app that would make their day easier "
            "(homework reminder, workout counter, game score keeper)? Ask what it would do.",
            "Phone powers: would they enjoy using what a phone has (camera, location, notifications, "
            "touch)? Ask which one they would use in an app and how.",
            "Thinking: an app to remember homework. Ask which three buttons or screens it needs "
            "and why, and what else a phone could do to help (alarm, camera).",
        ),
        keywords=(
            "mobile",
            "phone",
            "app",
            "apps",
            "android",
            "iphone",
            "ios",
            "notification",
            "tiktok",
            "تطبيق",
            "تطبيقات",
            "موبايل",
            "تليفون",
            "هاتف",
            "اندرويد",
            "أندرويد",
            "ايفون",
            "آيفون",
            "اشعارات",
            "إشعارات",
        ),
    ),
    TrackKnowledge(
        key="games",
        aliases=("games", "game", "gamedev", "gamedevelopment", "gamedesign", "gaming"),
        what_it_is="building games: rules, characters, levels and worlds",
        probes=(
            "Behind the game: when they play, do they wonder how it works (how enemies decide what to do, "
            "how levels or points work)? Ask about one thing in a game they love.",
            "Making: have they ever built or changed something in a game (a Minecraft world, a Roblox map, "
            "their own rules)? Ask what they made and how it went.",
            "Story and characters: do they like inventing characters, worlds or stories? "
            "Ask them to describe a character or place from their own game.",
            "Thinking: invent a simple game for the class with only paper and a dice. Ask what the goal is, "
            "how you win, and what would make it more fun.",
        ),
        keywords=(
            "game",
            "games",
            "gaming",
            "minecraft",
            "roblox",
            "fortnite",
            "pubg",
            "fifa",
            "unity",
            "level",
            "character",
            "player",
            "gamer",
            "لعبه",
            "لعبة",
            "العاب",
            "ألعاب",
            "جيم",
            "ماين كرافت",
            "روبلوكس",
            "فورتنايت",
            "ببجي",
            "فيفا",
            "شخصيه",
            "شخصية",
            "مرحله",
            "مرحلة",
            "العب",
            "ألعب",
            "بلاي ستيشن",
        ),
    ),
    TrackKnowledge(
        key="ai",
        aliases=("ai", "ml", "artificialintelligence", "machinelearning", "deeplearning", "aiml"),
        what_it_is="teaching computers to learn, recognise things and make decisions",
        probes=(
            "How does it know: do they wonder how a voice assistant, a video recommendation, a chatbot "
            "or a camera filter 'knows' things? Ask what they think happens inside.",
            "Teaching a computer: would they enjoy teaching a computer to tell two things apart "
            "(cats and dogs, two drawings, two voices)? Ask what they would teach it and how.",
            "Smart helper: if they could build a robot or smart helper that decides things by itself, "
            "what problem would it solve for them?",
            "Thinking: how would they teach a computer to tell a cat from a dog? Ask what examples "
            "they would show it and what mistakes it might make.",
        ),
        keywords=(
            "ai",
            "robot",
            "robots",
            "chatgpt",
            "chatbot",
            "siri",
            "alexa",
            "machine",
            "learning",
            "smart",
            "artificial",
            "intelligence",
            "ذكاء",
            "ذكاء اصطناعي",
            "روبوت",
            "روبوتات",
            "شات جي بي تي",
            "سيري",
            "الكسا",
            "الذكي",
            "ذكي",
            "خيال علمي",
        ),
    ),
    TrackKnowledge(
        key="cyber",
        aliases=("cyber", "cybersecurity", "security", "infosec", "ethicalhacking", "networksecurity"),
        what_it_is="protecting people and systems online; finding weak spots in order to fix them",
        probes=(
            "Staying safe: have they noticed fake messages, scams or suspicious links online? "
            "Ask how they could tell it was fake (never ask about their own passwords or accounts).",
            "Detective: do they enjoy clues, secret codes, escape rooms or working out how a trick was done? "
            "Ask for the one they enjoyed most.",
            "Defender: would they enjoy finding a weak spot in a game or app so it can be FIXED before "
            "bad people use it? Ask how they would look for it.",
            "Thinking: a secret treasure hunt for a club, and only members should be able to read "
            "the clue. Ask how they would make sure only members can, and how someone might cheat.",
        ),
        keywords=(
            "cyber",
            "security",
            "hack",
            "hacker",
            "hacking",
            "password",
            "scam",
            "virus",
            "privacy",
            "encrypt",
            "secret",
            "puzzle",
            "bug",
            "اختراق",
            "هاكر",
            "هكر",
            "حمايه",
            "حماية",
            "امن",
            "أمن",
            "فيروس",
            "تشفير",
            "اسرار",
            "أسرار",
            "لغز",
            "الغاز",
            "ألغاز",
            "باج",
        ),
    ),
)

_BY_ALIAS: dict[str, TrackKnowledge] = {a: k for k in TRACKS_KNOWLEDGE for a in (k.key, *k.aliases)}

_ARABIC_DIACRITICS = re.compile("[\u064b-\u0652\u0640]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _alias(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower())


def normalize_arabic(text: str) -> str:
    """Lower-case, drop diacritics, unify alef/ya/ta-marbuta so keyword matching is forgiving."""
    text = _ARABIC_DIACRITICS.sub("", text.lower())
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي")):
        text = text.replace(src, dst)
    return text


def knowledge_for(track: Track) -> TrackKnowledge | None:
    """Match by code first (FRONTEND, UIUX...), then by display name (Game Dev, UI/UX...)."""
    return _BY_ALIAS.get(_alias(track.code)) or _BY_ALIAS.get(_alias(track.name))


def generic_probes(track: Track) -> tuple[str, ...]:
    """Deep angles for a track we do not know, built from the profile the backend sent."""
    profile = track.profile.strip().rstrip(".")
    return (
        f"Concrete activity: pick ONE specific activity from this description - '{profile}' - and ask a real "
        "'would you enjoy ...' or 'have you ever ...' question about it, with an example from the student's life.",
        "Hands-on: ask what small thing they would make or try in this area, and what part they would enjoy most.",
        "Curiosity: ask what they have wondered about in this area and how they would find the answer.",
        "Thinking: give a small everyday problem in this area and ask how they would approach it, step by step.",
    )


def probes_for(track: Track) -> tuple[str, ...]:
    known = knowledge_for(track)
    return known.probes if known else generic_probes(track)


# ------------------------------------------------------------------- signals
def _compile(keyword: str) -> re.Pattern[str]:
    word = normalize_arabic(keyword)
    if word.isascii():
        return re.compile(rf"\b{re.escape(word)}\b")
    return re.compile(re.escape(word))


_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    k.key: tuple(_compile(w) for w in k.keywords) for k in TRACKS_KNOWLEDGE
}


def signal_score(track: Track, answers: Sequence[QA]) -> int:
    """How many different interest words of this track the student used (max 2 hits per word)."""
    known = knowledge_for(track)
    if not known:
        return 0
    text = normalize_arabic(" ".join(qa.transcript for qa in answers))
    return sum(min(len(p.findall(text)), 2) for p in _PATTERNS[known.key])
