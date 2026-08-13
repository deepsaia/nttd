"""Human-readable name generators for sessions and companies.

One shape for both, <adj>-<noun>-<date>-<time><tz>:

    session   crimson-falcon-06apr2026-160734pdt
    company   jade-heron-06apr2026-160734pdt

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


def generate_session_name() -> str:
    """Generate a human-readable session name with timestamp.

    Format: <adj>-<noun>-06apr2026-160734pdt
    """
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    return f"{adj}-{noun}-{generate_timestamp()}"


def generate_company_name() -> str:
    """Generate a company name like 'jade-heron-06apr2026-160734pdt'.

    The same shape as a session name, deliberately. Companies default to "Unnamed" in
    OpenTTD, which makes a leaderboard row unable to identify who played, so every
    contestant company gets a readable name it can still override.

    It used to end in four hex characters, which made a company name and a session name
    look like different kinds of thing and told a reader nothing about when the run
    happened. The timestamp keeps names distinct as well as the hex did, since two
    companies minted in the same second on the same adjective and noun is not a case that
    arises: one session plays one scored company.

    The word pair is chosen to FIT rather than freely, because OpenTTD caps a company name
    at MAX_COMPANY_NAME characters and the timestamp alone is 19 of them. Picking freely
    gives up to 35, which the game would refuse, and a refused rename leaves the company
    called "Unnamed" so a leaderboard row cannot say who played. Shape is preserved: still
    exactly <adj>-<noun>-<timestamp>, only drawn from the pairs that fit.
    """
    timestamp = generate_timestamp()
    budget = MAX_COMPANY_NAME - len(timestamp) - 2  # two hyphens
    pairs = [
        (adj, noun)
        for adj in _ADJECTIVES
        for noun in _NOUNS
        if len(adj) + len(noun) <= budget
    ]
    if not pairs:
        # A timestamp long enough to leave no room at all. Truncating beats refusing,
        # because a named company is the point.
        return f"{_ADJECTIVES[0]}-{_NOUNS[0]}-{timestamp}"[:MAX_COMPANY_NAME]
    adj, noun = random.choice(pairs)
    return f"{adj}-{noun}-{timestamp}"
