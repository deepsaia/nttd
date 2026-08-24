"""Human-readable name generators for sessions and companies.

Two shapes, because they are read in different places:

    session   20260815-132431ist-quiet-pickle   date first, so a listing sorts by time
    company   jade-heron-20260813-160734pdt     words first, and capped in length

A company name is additionally capped, because OpenTTD refuses an over-long one and a
refused rename leaves the company called "Unnamed", which makes a leaderboard row unable to
say who played.
"""
import random
from datetime import datetime

# OpenTTD's limit for a company name. The timestamp is 19 characters of it, so the word
# pair is chosen to fit rather than drawn freely: see generate_company_name.
MAX_COMPANY_NAME = 31

_ADJECTIVES = [
    "amber", "arc", "ash", "azure", "beefy", "blithe", "bold", "bonny", "brave", "bright", "brisk",
    "bubbly", "calm", "cheery", "chief", "chirpy", "civic", "clever", "cloudy", "comic", "cosmic",
    "cozy", "crimson", "crisp", "crystal", "dandy", "daring", "deft", "dicey", "eager", "elfin",
    "ember", "emerald", "fabled", "fancy", "fierce", "fleet", "foxy", "fresh", "fuzzy", "gallant",
    "gentle", "giddy", "gilded", "golden", "grand", "happy", "hardy", "hasty", "hollow", "humble",
    "hyper", "ivory", "jade", "jaunty", "jazzy", "jolly", "keen", "kind", "lively", "lucky", "lunar",
    "magic", "marble", "mellow", "merry", "mighty", "misty", "nifty", "nimble", "noble", "opal",
    "peppy", "perky", "plucky", "poppy", "prime", "proud", "puffy", "quick", "quiet", "rapid",
    "regal", "risen", "rosy", "royal", "rustic", "sage", "scarlet", "serene", "sharp", "shiny",
    "silky", "silver", "sleek", "sly", "snappy", "solar", "solid", "sparky", "spry", "stark",
    "steady", "steel", "stout", "sturdy", "subtle", "sunny", "swift", "tidy", "tidal", "toasty",
    "tricky", "vast", "velvet", "vivid", "warm", "wild", "wily", "wise", "witty", "zappy", "zesty",
    "zippy",
]

_NOUNS = [
    "acorn", "alpaca", "anchor", "anvil", "arrow", "badger", "bagel", "basil", "beacon", "beetle",
    "berry", "biscuit", "blimp", "boulder", "bridge", "brook", "buffin", "cactus", "canyon", "cedar",
    "cinder", "cliff", "cloud", "comet", "condor", "coral", "crane", "creek", "cricket", "crouton",
    "dagger", "dingo", "drake", "drift", "eagle", "ember", "falcon", "ferry", "finch", "flint",
    "forge", "frost", "gale", "gecko", "glider", "gnome", "grove", "harbor", "heron", "hopper",
    "hunter", "iris", "islet", "jasper", "jelly", "junco", "kestrel", "kitten", "lance", "lark",
    "ledger", "lemur", "lotus", "maple", "marsh", "meadow", "mesa", "meteor", "minnow", "moose",
    "morsel", "muffin", "nectar", "noodle", "nova", "nylon", "orbit", "orchid", "osprey", "otter",
    "panda", "panther", "pebble", "pepper", "pickle", "pine", "pixel", "plover", "pocket", "puffin",
    "quarry", "quartz", "quokka", "rabbit", "raven", "reef", "ridge", "river", "robin", "rocket",
    "sage", "scooter", "sentry", "shadow", "signal", "skipper", "slate", "snail", "sparrow", "spruce",
    "sprite", "sprout", "summit", "taco", "thistle", "timber", "toffee", "trail", "trout", "tundra",
    "turbo", "valley", "velvet", "viper", "walrus", "warden", "weasel", "willow", "wolf", "wombat",
    "wren", "yeti", "zephyr",
]


def generate_timestamp() -> str:
    """Generate a timestamp suffix like '20260813-160734pdt'.

    Date first and numeric, so a plain lexical sort of names is also a chronological one.
    It used to read 13aug2026, which sorts august before february and tells a machine nothing.
    """
    now = datetime.now().astimezone()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")
    tz_name = now.strftime("%Z").lower()
    tz_str = tz_name if tz_name else "utc"
    return f"{date_str}-{time_str}{tz_str}"


def generate_session_id() -> str:
    """The one name a session has, like '20260815-073255-dandy-willow'.

    There used to be two, and they disagreed. A session was minted as
    ses_20260815_073254_060e426f on disk and shown as dandy-willow-20260815-073255ist in
    the monitor, generated a moment apart, so the same run carried two identities whose
    timestamps were off by a second.

    Date and time first, because these are directory names and a lexical sort is then a
    chronological one. The word pair last, because that is the part a person says out
    loud, and it is what keeps two runs minted in the same second apart: the eight hex
    characters it replaces did that job and told a reader nothing else.

    The timezone rides with the time it qualifies, as 132431ist, so a reader can tell at a
    glance which clock a run was on without opening the result. It is an abbreviation and
    abbreviations are ambiguous, IST being Indian, Irish and Israel standard time at once,
    so the unambiguous offset is still recorded as `started_at` on the result. The id says
    roughly when; the result says exactly.
    """
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    now = datetime.now().astimezone()
    zone = (now.strftime("%Z") or "utc").lower()
    return f"{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}{zone}-{adj}-{noun}"


def readable_part(session_id: str) -> str:
    """The words out of an id, for a heading that does not need to repeat the date.

    '20260815-073255ist-dandy-willow' reads back as 'dandy-willow'. An id from before the
    two names were collapsed, or any id that does not carry a word pair, is returned whole
    rather than mangled into a guess.
    """
    parts = session_id.split("-")
    if len(parts) >= 4 and parts[0].isdigit() and parts[1][:6].isdigit():
        return "-".join(parts[2:])
    return session_id


def company_name_for(session_id: str, company_id: int) -> str:
    """The company's name, taken from the session that created it.

    A company used to mint its own name, with its own adjective, noun and timestamp. So a run
    called 20260824-132212ist-sly-marsh was played by a company called
    chief-warden-20260824-132213ist: two identities for one run, generated a second apart,
    which is the exact bug that collapsing the session's two names into one id was meant to
    end. The monitor then showed one of them in its sidebar and the other in its URL.

    So the company carries the session's word pair. One run, one name.

    **The date is deliberately dropped.** OpenTTD caps a company name at MAX_COMPANY_NAME
    characters, and a session id runs to 35: the longest adjective and noun together are 14,
    a four-letter timezone makes the stamp 19, and 19 + 1 + 14 + 1 is over the cap. A rule
    that included the date would therefore fit most ids and silently truncate the longest,
    which is worse than a rule that never includes it. The date adds nothing inside a game
    anyway: a company name only has to be unambiguous in the game it belongs to, and the
    session id is what carries the date everywhere outside it.

    Extra companies are numbered. Only one company is scored, but `--ai-opponents N` creates
    idle ones and OpenTTD would otherwise leave them all sharing a name.
    """
    suffix = "" if company_id == 0 else f"-{company_id}"
    # readable_part answers the whole id for anything that is not the current shape, and a
    # supplied --name may be up to 128 characters, so the cap is enforced rather than assumed.
    # A named company is the point: truncating beats a refused rename, which leaves it
    # "Unnamed" and a leaderboard row unable to say who played.
    stem = readable_part(session_id)[:MAX_COMPANY_NAME - len(suffix)]
    return f"{stem}{suffix}"
