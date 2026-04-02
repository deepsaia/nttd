import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import MenuItem from '@mui/material/MenuItem';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';

// ---------------------------------------------------------------------------
// Setting definitions
// ---------------------------------------------------------------------------

interface SettingOption {
  value: string;
  label: string;
}

interface SettingDef {
  key: string;
  label: string;
  type: 'select' | 'number';
  default: string;
  options?: SettingOption[];
  min?: number;
  max?: number;
  helperText?: string;
  showWhen?: (values: Record<string, string>) => boolean;
}

interface SettingGroupDef {
  id: string;
  label: string;
  settings: SettingDef[];
}

const MAP_SIZES: SettingOption[] = [
  { value: '6', label: '64' },
  { value: '7', label: '128' },
  { value: '8', label: '256' },
  { value: '9', label: '512' },
  { value: '10', label: '1024' },
  { value: '11', label: '2048' },
  { value: '12', label: '4096' },
];

const SETTING_GROUPS: SettingGroupDef[] = [
  {
    id: 'world',
    label: 'World Generation',
    settings: [
      {
        key: 'game_creation.landscape',
        label: 'Landscape',
        type: 'select',
        default: '0',
        options: [
          { value: '0', label: 'Temperate' },
          { value: '1', label: 'Sub-Arctic' },
          { value: '2', label: 'Sub-Tropical' },
          { value: '3', label: 'Toyland' },
        ],
      },
      {
        key: 'game_creation.map_x',
        label: 'Map Width',
        type: 'select',
        default: '6',
        options: MAP_SIZES,
      },
      {
        key: 'game_creation.map_y',
        label: 'Map Height',
        type: 'select',
        default: '6',
        options: MAP_SIZES,
      },
      {
        key: 'difficulty.terrain_type',
        label: 'Terrain Type',
        type: 'select',
        default: '0',
        options: [
          { value: '0', label: 'Flat' },
          { value: '1', label: 'Hilly' },
          { value: '2', label: 'Mountainous' },
          { value: '3', label: 'Alpinist' },
          { value: '4', label: 'Custom Height' },
        ],
      },
      {
        key: 'game_creation.custom_terrain_type',
        label: 'Custom Height',
        type: 'number',
        default: '30',
        min: 1,
        max: 255,
        helperText: 'Max terrain height (1-255)',
        showWhen: (v) => v['difficulty.terrain_type'] === '4',
      },
      {
        key: 'game_creation.variety',
        label: 'Variety Distribution',
        type: 'select',
        default: '0',
        options: [
          { value: '0', label: 'None' },
          { value: '1', label: 'Very Low' },
          { value: '2', label: 'Low' },
          { value: '3', label: 'Medium' },
          { value: '4', label: 'High' },
          { value: '5', label: 'Very High' },
        ],
      },
      {
        key: 'game_creation.tgen_smoothness',
        label: 'Smoothness',
        type: 'select',
        default: '1',
        options: [
          { value: '1', label: 'Smooth' },
          { value: '0', label: 'Very Smooth' },
          { value: '2', label: 'Rough' },
          { value: '3', label: 'Very Rough' },
        ],
      },
      {
        key: 'game_creation.amount_of_rivers',
        label: 'Rivers',
        type: 'select',
        default: '2',
        options: [
          { value: '2', label: 'Medium' },
          { value: '0', label: 'None' },
          { value: '1', label: 'Few' },
          { value: '3', label: 'Many' },
        ],
      },
      {
        key: 'game_creation.water_borders',
        label: 'Map Edges',
        type: 'select',
        default: '16',
        helperText: 'Controls water placement at map edges',
        options: [
          { value: '16', label: 'Random' },
          { value: '0', label: 'Freeform (No Water)' },
          { value: '15', label: 'Infinite Water (All Sides)' },
          { value: '1', label: 'Water NE only' },
          { value: '2', label: 'Water SE only' },
          { value: '4', label: 'Water SW only' },
          { value: '8', label: 'Water NW only' },
          { value: '3', label: 'Water NE + SE' },
          { value: '5', label: 'Water NE + SW' },
          { value: '9', label: 'Water NE + NW' },
          { value: '6', label: 'Water SE + SW' },
          { value: '10', label: 'Water SE + NW' },
          { value: '12', label: 'Water SW + NW' },
        ],
      },
      {
        key: 'game_creation.starting_year',
        label: 'Starting Year',
        type: 'number',
        default: '1950',
        min: 0,
        max: 5000000,
      },
    ],
  },
  {
    id: 'towns',
    label: 'Towns & Industries',
    settings: [
      {
        key: 'game_creation.town_name',
        label: 'Town Names',
        type: 'select',
        default: '0',
        options: [
          { value: '0', label: 'English (Original)' },
          { value: '13', label: 'Austrian' },
          { value: '20', label: 'Catalan' },
          { value: '15', label: 'Czech' },
          { value: '17', label: 'Danish' },
          { value: '7', label: 'Dutch' },
          { value: '3', label: 'English (Additional)' },
          { value: '8', label: 'Finnish' },
          { value: '1', label: 'French' },
          { value: '2', label: 'German' },
          { value: '12', label: 'Hungarian' },
          { value: '19', label: 'Italian' },
          { value: '4', label: 'Latin-American' },
          { value: '11', label: 'Norwegian' },
          { value: '9', label: 'Polish' },
          { value: '14', label: 'Romanian' },
          { value: '5', label: 'Silly' },
          { value: '10', label: 'Slovak' },
          { value: '6', label: 'Swedish' },
          { value: '16', label: 'Swiss' },
          { value: '18', label: 'Turkish' },
        ],
      },
      {
        key: 'difficulty.number_towns',
        label: 'Number of Towns',
        type: 'select',
        default: '2',
        options: [
          { value: '2', label: 'Normal' },
          { value: '0', label: 'Very Low' },
          { value: '1', label: 'Low' },
          { value: '3', label: 'High' },
          { value: '4', label: 'Custom' },
        ],
      },
      {
        key: 'game_creation.custom_town_number',
        label: 'Custom Town Count',
        type: 'number',
        default: '1',
        min: 1,
        max: 5000,
        showWhen: (v) => v['difficulty.number_towns'] === '4',
      },
      {
        key: 'difficulty.industry_density',
        label: 'Number of Industries',
        type: 'select',
        default: '4',
        options: [
          { value: '4', label: 'Normal' },
          { value: '0', label: 'Funding Only' },
          { value: '1', label: 'Minimal' },
          { value: '2', label: 'Very Low' },
          { value: '3', label: 'Low' },
          { value: '5', label: 'High' },
          { value: '6', label: 'Custom' },
        ],
      },
      {
        key: 'game_creation.custom_industry_number',
        label: 'Custom Industry Count',
        type: 'number',
        default: '1',
        min: 1,
        max: 5000,
        helperText: 'Number of industries to generate',
        showWhen: (v) => v['difficulty.industry_density'] === '6',
      },
      {
        key: 'difficulty.quantity_sea_lakes',
        label: 'Sea Level',
        type: 'select',
        default: '2',
        options: [
          { value: '2', label: 'Medium' },
          { value: '0', label: 'Very Low' },
          { value: '1', label: 'Low' },
          { value: '3', label: 'High' },
          { value: '4', label: 'Custom' },
        ],
      },
      {
        key: 'game_creation.custom_sea_level',
        label: 'Custom Sea Level (%)',
        type: 'number',
        default: '1',
        min: 1,
        max: 90,
        helperText: 'Percentage of map covered by water (1-90%)',
        showWhen: (v) => v['difficulty.quantity_sea_lakes'] === '4',
      },
    ],
  },
  {
    id: 'economy',
    label: 'Economy',
    settings: [
      {
        key: 'difficulty.max_loan',
        label: 'Max Loan',
        type: 'number',
        default: '300000',
        min: 0,
        max: 2000000000,
      },
      {
        key: 'economy.inflation',
        label: 'Inflation',
        type: 'select',
        default: 'false',
        options: [
          { value: 'false', label: 'Off' },
          { value: 'true', label: 'On' },
        ],
      },
      {
        key: 'economy.type',
        label: 'Economy Type',
        type: 'select',
        default: '1',
        options: [
          { value: '1', label: 'Smooth' },
          { value: '0', label: 'Original' },
        ],
      },
    ],
  },
  {
    id: 'vehicles',
    label: 'Vehicles',
    settings: [
      {
        key: 'vehicle.max_trains',
        label: 'Max Trains',
        type: 'number',
        default: '500',
        min: 0,
        max: 5000,
      },
      {
        key: 'vehicle.max_roadveh',
        label: 'Max Road Vehicles',
        type: 'number',
        default: '500',
        min: 0,
        max: 5000,
      },
      {
        key: 'vehicle.max_aircraft',
        label: 'Max Aircraft',
        type: 'number',
        default: '200',
        min: 0,
        max: 5000,
      },
      {
        key: 'vehicle.max_ships',
        label: 'Max Ships',
        type: 'number',
        default: '300',
        min: 0,
        max: 5000,
      },
    ],
  },
  {
    id: 'ai',
    label: 'AI Competitors',
    settings: [
      {
        key: 'difficulty.max_no_competitors',
        label: 'Number of AI Competitors',
        type: 'select',
        default: '0',
        options: Array.from({ length: 15 }, (_, i) => ({
          value: String(i),
          label: i === 0 ? '0 (None)' : String(i),
        })),
      },
      {
        key: 'difficulty.competitors_interval',
        label: 'Interval Between AI Starts (minutes)',
        type: 'number',
        default: '10',
        min: 0,
        max: 3600,
        helperText: 'Minutes between each AI company starting. 0 = all start immediately.',
        showWhen: (v) => Number(v['difficulty.max_no_competitors'] ?? '0') > 0,
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns a map of all setting keys to their default values. */
function getAllDefaults(): Record<string, string> {
  const defaults: Record<string, string> = {};
  for (const group of SETTING_GROUPS) {
    for (const s of group.settings) {
      defaults[s.key] = s.default;
    }
  }
  return defaults;
}

function resolveLabel(def: SettingDef, value: string): string {
  if (def.options) {
    const match = def.options.find((o) => o.value === value);
    if (match) return match.label;
  }
  if (def.key === 'game_creation.map_x' || def.key === 'game_creation.map_y') {
    const n = Number(value);
    if (n >= 6 && n <= 12) return String(2 ** n);
  }
  return value;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  values: Record<string, string>;
  onChange?: (key: string, value: string) => void;
}

export default function SessionSettingsForm({ values, onChange }: Props) {
  const readOnly = !onChange;

  function getValue(def: SettingDef): string {
    return values[def.key] ?? def.default;
  }

  function isVisible(def: SettingDef): boolean {
    if (!def.showWhen) return true;
    const merged: Record<string, string> = {};
    for (const group of SETTING_GROUPS) {
      for (const s of group.settings) {
        merged[s.key] = values[s.key] ?? s.default;
      }
    }
    return def.showWhen(merged);
  }

  return (
    <Box>
      {SETTING_GROUPS.map((group) => {
        const visibleSettings = group.settings.filter(isVisible);
        if (visibleSettings.length === 0) return null;

        return (
          <Box key={group.id} sx={{ mb: 2 }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              {group.label}
            </Typography>
            <Divider sx={{ mb: 1 }} />
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
              {visibleSettings.map((def) => {
                const val = getValue(def);

                if (readOnly) {
                  return (
                    <Typography key={def.key} variant="body2" color="text.secondary">
                      <strong>{def.label}:</strong> {resolveLabel(def, val)}
                    </Typography>
                  );
                }

                if (def.type === 'select' && def.options) {
                  return (
                    <TextField
                      key={def.key}
                      select
                      size="small"
                      label={def.label}
                      value={val}
                      onChange={(e) => onChange(def.key, e.target.value)}
                      helperText={def.helperText}
                    >
                      {def.options.map((opt) => (
                        <MenuItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </MenuItem>
                      ))}
                    </TextField>
                  );
                }

                return (
                  <TextField
                    key={def.key}
                    size="small"
                    type="number"
                    label={def.label}
                    value={val}
                    onChange={(e) => onChange(def.key, e.target.value)}
                    helperText={def.helperText}
                    slotProps={{
                      htmlInput: {
                        min: def.min,
                        max: def.max,
                      },
                    }}
                  />
                );
              })}
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}

export { SETTING_GROUPS, getAllDefaults };
export type { SettingGroupDef, SettingDef };
