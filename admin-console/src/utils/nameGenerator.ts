const ADJECTIVES = [
  'amber', 'azure', 'bold', 'brave', 'bright', 'calm', 'clever', 'cosmic',
  'crimson', 'crystal', 'daring', 'deft', 'eager', 'emerald', 'fabled',
  'fierce', 'fleet', 'gallant', 'gentle', 'gilded', 'golden', 'grand',
  'hardy', 'hollow', 'humble', 'ivory', 'jade', 'keen', 'lively', 'lucky',
  'lunar', 'marble', 'mighty', 'misty', 'noble', 'onyx', 'opal', 'pale',
  'prime', 'proud', 'quiet', 'rapid', 'regal', 'risen', 'rosy', 'royal',
  'rustic', 'sage', 'scarlet', 'serene', 'sharp', 'silver', 'sleek',
  'solar', 'solid', 'stark', 'steady', 'steel', 'stern', 'stout', 'sturdy',
  'subtle', 'sunny', 'swift', 'tawny', 'tidal', 'vast', 'vivid', 'warm',
  'wild', 'wily', 'wise', 'witty', 'zealous',
];

const NOUNS = [
  'anchor', 'arrow', 'badger', 'beacon', 'bridge', 'canyon', 'cedar',
  'cinder', 'cliff', 'comet', 'condor', 'coral', 'crane', 'creek',
  'dagger', 'depot', 'drake', 'eagle', 'ember', 'falcon', 'ferry',
  'flint', 'forge', 'frost', 'gale', 'grove', 'harbor', 'heron',
  'hunter', 'iris', 'jasper', 'kestrel', 'lance', 'lark', 'ledger',
  'maple', 'marsh', 'meadow', 'mesa', 'meteor', 'minnow', 'moose',
  'orchid', 'osprey', 'otter', 'panther', 'pebble', 'pine', 'plover',
  'quarry', 'quartz', 'raven', 'reef', 'ridge', 'river', 'robin',
  'rocket', 'sage', 'sentry', 'sierra', 'signal', 'slate', 'sparrow',
  'spruce', 'summit', 'thistle', 'timber', 'trail', 'trout', 'tundra',
  'valley', 'viper', 'walrus', 'warden', 'willow', 'wolf', 'wren',
];

const VERBS = [
  'blazing', 'brewing', 'charging', 'climbing', 'coasting', 'crossing',
  'cruising', 'dashing', 'drifting', 'driving', 'flowing', 'flying',
  'forging', 'gliding', 'hauling', 'hosting', 'hunting', 'joining',
  'jumping', 'landing', 'leading', 'leaping', 'loading', 'mapping',
  'marching', 'mining', 'moving', 'paving', 'racing', 'rallying',
  'ranging', 'rising', 'rolling', 'roaming', 'routing', 'running',
  'rushing', 'sailing', 'scaling', 'seeking', 'shaping', 'shipping',
  'soaring', 'spanning', 'speeding', 'steaming', 'steering', 'surging',
  'trading', 'trailing', 'turning', 'vaulting', 'winding',
];

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

/** Generate a random human-readable session name like "crimson-falcon-blazing". */
export function generateSessionName(): string {
  return `${pick(ADJECTIVES)}-${pick(NOUNS)}-${pick(VERBS)}`;
}
