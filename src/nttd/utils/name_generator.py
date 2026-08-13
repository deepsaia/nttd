"""Human-readable name generators for sessions and companies.

Sessions: crimson-falcon-blaze-06apr2026-160734pdt
Companies: jade-heron-4f2a
"""
import random
import uuid
from datetime import datetime

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
    """Generate a timestamp suffix like '06apr2026-160734pdt'."""
    now = datetime.now().astimezone()
    date_str = now.strftime("%d%b%Y").lower()
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
    """Generate a company name like 'jade-heron-4f2a'.

    Format: <adj>-<noun>-<4 hex chars>. Companies default to "Unnamed" in
    OpenTTD, which makes a leaderboard row unable to identify who played, so
    every contestant company gets a readable name it can still override.

    The hex suffix keeps names distinct when two companies draw the same pair.
    """
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    return f"{adj}-{noun}-{uuid.uuid4().hex[:4]}"
