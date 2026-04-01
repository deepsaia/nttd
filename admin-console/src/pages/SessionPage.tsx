import { useCallback, useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import SaveIcon from '@mui/icons-material/Save';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import * as api from '../api/client';
import type { Session, SessionDetail } from '../api/client';
import { useGameStore } from '../store/gameStore';

const SETTING_GROUPS: Record<string, { label: string; settings: { key: string; label: string; default: string }[] }> = {
  map: {
    label: 'Map',
    settings: [
      { key: 'map_x', label: 'Map Width (2^n)', default: '8' },
      { key: 'map_y', label: 'Map Height (2^n)', default: '8' },
      { key: 'game_creation.landscape', label: 'Landscape (0=temp,1=arctic,2=tropic,3=toy)', default: '0' },
      { key: 'game_creation.variety', label: 'Terrain Variety (0-5)', default: '0' },
    ],
  },
  economy: {
    label: 'Economy',
    settings: [
      { key: 'difficulty.max_loan', label: 'Max Loan', default: '300000' },
      { key: 'economy.inflation', label: 'Inflation (0/1)', default: '0' },
      { key: 'economy.smooth_economy', label: 'Smooth Economy (0/1)', default: '1' },
    ],
  },
  vehicles: {
    label: 'Vehicles',
    settings: [
      { key: 'vehicle.max_trains', label: 'Max Trains', default: '500' },
      { key: 'vehicle.max_roadveh', label: 'Max Road Vehicles', default: '500' },
      { key: 'vehicle.max_aircraft', label: 'Max Aircraft', default: '200' },
      { key: 'vehicle.max_ships', label: 'Max Ships', default: '300' },
    ],
  },
  competitors: {
    label: 'AI',
    settings: [
      { key: 'difficulty.max_no_competitors', label: 'Max AI Competitors', default: '0' },
      { key: 'ai_in_multiplayer', label: 'AI in Multiplayer (true/false)', default: 'true' },
    ],
  },
};

export default function SessionPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<SessionDetail | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newSettings, setNewSettings] = useState<Record<string, string>>({});
  const [aiCount, setAiCount] = useState(0);
  const [saveFilename, setSaveFilename] = useState('');
  const [loadFilename, setLoadFilename] = useState('');
  const status = useGameStore((s) => s.status);

  const fetchSessions = useCallback(async () => {
    try {
      const { sessions: s } = await api.listSessions();
      setSessions(s);
    } catch {
      // offline
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  async function handleCreate() {
    try {
      const { session_id } = await api.createSession(newName || 'New Session', newSettings);
      setCreateOpen(false);
      setNewName('');
      setNewSettings({});
      await fetchSessions();
      await selectSession(session_id);
    } catch {
      // error
    }
  }

  async function selectSession(id: string) {
    try {
      const detail = await api.getSession(id);
      setSelected(detail);
    } catch {
      // error
    }
  }

  async function handleStart() {
    if (!selected) return;
    try {
      await api.startSession(selected.session_id, 'newgame', aiCount);
      await selectSession(selected.session_id);
    } catch {
      // error
    }
  }

  async function handleStop() {
    if (!selected) return;
    try {
      await api.stopSession(selected.session_id);
      await fetchSessions();
      await selectSession(selected.session_id);
    } catch {
      // error
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.deleteSession(id);
      if (selected?.session_id === id) setSelected(null);
      await fetchSessions();
    } catch {
      // error
    }
  }

  async function handleSave() {
    if (!saveFilename) return;
    try {
      await api.saveGame(saveFilename);
      setSaveFilename('');
    } catch {
      // error
    }
  }

  async function handleLoad() {
    if (!loadFilename) return;
    try {
      await api.loadGame(loadFilename);
      setLoadFilename('');
    } catch {
      // error
    }
  }

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h5">Sessions</Typography>
        <Button startIcon={<AddIcon />} variant="contained" onClick={() => setCreateOpen(true)}>
          New Session
        </Button>
      </Stack>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 3 }}>
        {/* Session list */}
        <Card>
          <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
            <List dense>
              {sessions.map((s) => (
                <ListItem
                  key={s.session_id}
                  secondaryAction={
                    <IconButton size="small" onClick={() => handleDelete(s.session_id)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  }
                  onClick={() => selectSession(s.session_id)}
                  sx={{
                    cursor: 'pointer',
                    bgcolor: selected?.session_id === s.session_id ? 'action.selected' : 'transparent',
                  }}
                >
                  <ListItemText
                    primary={s.name}
                    secondary={
                      <Chip
                        size="small"
                        label={s.status}
                        color={s.status === 'active' ? 'success' : 'default'}
                        sx={{ mt: 0.5 }}
                      />
                    }
                  />
                </ListItem>
              ))}
              {sessions.length === 0 && (
                <ListItem>
                  <ListItemText secondary="No sessions yet" />
                </ListItem>
              )}
            </List>
          </CardContent>
        </Card>

        {/* Session detail */}
        <Stack spacing={2}>
          {selected ? (
            <>
              <Card>
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Box>
                      <Typography variant="h6">{selected.name}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {selected.session_id} &middot; {selected.status}
                      </Typography>
                    </Box>
                    <Stack direction="row" spacing={1}>
                      {selected.status === 'active' ? (
                        <Button startIcon={<StopIcon />} color="error" variant="outlined" onClick={handleStop}>
                          Stop
                        </Button>
                      ) : (
                        <>
                          <Select
                            size="small"
                            value={aiCount}
                            onChange={(e) => setAiCount(Number(e.target.value))}
                            sx={{ minWidth: 80 }}
                          >
                            {[0, 1, 2, 3, 4, 5, 7, 10, 14].map((n) => (
                              <MenuItem key={n} value={n}>{n} AI</MenuItem>
                            ))}
                          </Select>
                          <Button startIcon={<PlayArrowIcon />} variant="contained" onClick={handleStart}>
                            Start
                          </Button>
                        </>
                      )}
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>

              {/* Settings */}
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>Settings</Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
                    {Object.entries(selected.settings || {}).map(([k, v]) => (
                      <Typography key={k} variant="body2" color="text.secondary">
                        <strong>{k}:</strong> {v}
                      </Typography>
                    ))}
                  </Box>
                </CardContent>
              </Card>

              {/* Participants */}
              {selected.participants && selected.participants.length > 0 && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" gutterBottom>Participants</Typography>
                    {selected.participants.map((p) => (
                      <Chip key={p.participant_id} label={`${p.name} (${p.participant_type}, Co.${p.company_id})`} sx={{ mr: 1, mb: 1 }} />
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Save / Load */}
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>Save / Load Game</Typography>
                  <Stack direction="row" spacing={1} mb={1}>
                    <TextField
                      size="small"
                      placeholder="save_name"
                      value={saveFilename}
                      onChange={(e) => setSaveFilename(e.target.value)}
                    />
                    <Button startIcon={<SaveIcon />} variant="outlined" onClick={handleSave} disabled={!saveFilename}>
                      Save
                    </Button>
                  </Stack>
                  <Stack direction="row" spacing={1}>
                    <TextField
                      size="small"
                      placeholder="filename.sav"
                      value={loadFilename}
                      onChange={(e) => setLoadFilename(e.target.value)}
                    />
                    <Button startIcon={<UploadFileIcon />} variant="outlined" onClick={handleLoad} disabled={!loadFilename}>
                      Load
                    </Button>
                  </Stack>
                </CardContent>
              </Card>

              {/* Connection info */}
              {status && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" gutterBottom>Connection Info</Typography>
                    <Typography variant="body2" color="text.secondary">
                      To join from OpenTTD client: Add Server → <strong>127.0.0.1:3979</strong>
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Map: {status.map_x}×{status.map_y} &middot; Landscape: {status.landscape || 'temperate'}
                    </Typography>
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <Card>
              <CardContent>
                <Typography color="text.secondary">Select a session or create a new one.</Typography>
              </CardContent>
            </Card>
          )}
        </Stack>
      </Box>

      {/* Create session dialog */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Session</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Session Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            sx={{ mt: 1, mb: 2 }}
          />
          {Object.entries(SETTING_GROUPS).map(([groupKey, group]) => (
            <Box key={groupKey} sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                {group.label}
              </Typography>
              <Divider sx={{ mb: 1 }} />
              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
                {group.settings.map((s) => (
                  <TextField
                    key={s.key}
                    size="small"
                    label={s.label}
                    value={newSettings[s.key] ?? s.default}
                    onChange={(e) => setNewSettings((prev) => ({ ...prev, [s.key]: e.target.value }))}
                  />
                ))}
              </Box>
            </Box>
          ))}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate}>Create</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
