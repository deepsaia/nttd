"""Human-readable session name generator.

Produces names like: crimson-falcon-blaze-06apr2026-160734pdt
"""
import random
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

_VERBS = [
    "amble", "beam", "blaze", "blink", "boing", "bolt", "bounce", "brew", "charge", "chase", "cheer",
    "climb", "coast", "cruise", "dash", "dart", "dive", "dodge", "drift", "drive", "float", "flow",
    "fly", "forge", "frolic", "glide", "groove", "hop", "hover", "hustle", "jive", "join", "jolt",
    "jump", "kick", "land", "lead", "leap", "lift", "loop", "march", "mingle", "mix", "move", "nudge",
    "paddle", "pave", "pivot", "pounce", "prance", "puff", "pull", "purr", "race", "rally", "range",
    "rip", "rise", "roam", "roll", "rush", "sail", "scale", "scoot", "scout", "seek", "shake", "shape",
    "ship", "skip", "slide", "soar", "spark", "spin", "splash", "spring", "sprint", "stash", "steer",
    "stomp", "stride", "surge", "swoop", "swing", "tackle", "trade", "trail", "trek", "trot", "vault",
    "veer", "vibe", "wade", "waltz", "weave", "whirl", "whisk", "whiz", "wiggle", "wind", "wink",
    "wobble", "zoom", "zip", "zap", "zig",
]


def _local_tz_suffix() -> str:
    """Return lowercase timezone abbreviation (e.g. 'pdt', 'est', 'utc')."""
    now = datetime.now().astimezone()
    tz_name = now.strftime("%Z").lower()
    return tz_name if tz_name else "utc"


def generate_session_name() -> str:
    """Generate a human-readable session name with timestamp.

    Format: <adj>-<noun>-<verb>-06apr2026-160734pdt
    """
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    verb = random.choice(_VERBS)

    now = datetime.now().astimezone()
    date_str = now.strftime("%d%b%Y").lower()
    time_str = now.strftime("%H%M%S")
    tz_str = _local_tz_suffix()

    return f"{adj}-{noun}-{verb}-{date_str}-{time_str}{tz_str}"
