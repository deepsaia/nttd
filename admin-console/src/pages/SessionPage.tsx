import { useCallback, useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Snackbar from '@mui/material/Snackbar';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import RefreshIcon from '@mui/icons-material/Refresh';
import StopIcon from '@mui/icons-material/Stop';
import SaveIcon from '@mui/icons-material/Save';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import * as api from '../api/client';
import type { Session, SessionDetail } from '../api/client';
import SessionSettingsForm, { getAllDefaults } from '../components/SessionSettingsForm';
import { useGameStore } from '../store/gameStore';
import { generateSessionName } from '../utils/nameGenerator';

function statusColor(status: string): 'success' | 'warning' | 'default' | 'error' {
  if (status === 'active') return 'success';
  if (status === 'archived') return 'warning';
  return 'default';
}

export default function SessionPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<SessionDetail | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newSettings, setNewSettings] = useState<Record<string, string>>({});
  const [editingSettings, setEditingSettings] = useState(false);
  const [editSettings, setEditSettings] = useState<Record<string, string>>({});
  const [saveFilename, setSaveFilename] = useState('');
  const [loadFilename, setLoadFilename] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setActiveSession = useGameStore((s) => s.setActiveSession);

  const fetchSessions = useCallback(async () => {
    try {
      const { sessions: s } = await api.listSessions();
      setSessions(s);
    } catch (e) {
      setError(`Failed to load sessions: ${e}`);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  async function handleCreate() {
    try {
      // Merge defaults with user selections so all settings are stored
      const allSettings = { ...getAllDefaults(), ...newSettings };
      const { session_id } = await api.createSession(newName || 'New Session', allSettings);
      setCreateOpen(false);
      setNewName('');
      setNewSettings({});
      await fetchSessions();
      await selectSession(session_id);
    } catch (e) {
      setError(`Failed to create session: ${e}`);
    }
  }

  async function selectSession(id: string) {
    try {
      const detail = await api.getSession(id);
      setSelected(detail);
      setEditingSettings(false);
      if (detail.status === 'active' && detail.running) {
        setActiveSession(detail.session_id);
      }
    } catch (e) {
      setError(`Failed to load session: ${e}`);
    }
  }

  function startEditSettings() {
    if (!selected) return;
    // Merge defaults so user sees all fields populated
    setEditSettings({ ...getAllDefaults(), ...selected.settings });
    setEditingSettings(true);
  }

  async function handleSaveSettings() {
    if (!selected) return;
    try {
      await api.updateSettings(selected.session_id, editSettings);
      setEditingSettings(false);
      await selectSession(selected.session_id);
    } catch (e) {
      setError(`Failed to update settings: ${e}`);
    }
  }

  async function handleStart() {
    if (!selected) return;
    setStarting(true);
    try {
      const aiCount = Number(selected.settings['difficulty.max_no_competitors'] ?? '0');
      await api.startSession(selected.session_id, 'newgame', aiCount);
      setActiveSession(selected.session_id);
      await fetchSessions();
      await selectSession(selected.session_id);
    } catch (e) {
      setError(`Failed to start session: ${e}`);
    } finally {
      setStarting(false);
    }
  }

  async function handleStop() {
    if (!selected) return;
    try {
      await api.stopSession(selected.session_id);
      await fetchSessions();
      await selectSession(selected.session_id);
    } catch (e) {
      setError(`Failed to stop session: ${e}`);
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.deleteSession(id);
      if (selected?.session_id === id) setSelected(null);
      setConfirmDeleteId(null);
      await fetchSessions();
    } catch (e) {
      setError(`Failed to delete session: ${e}`);
    }
  }

  async function handleSave() {
    if (!selected || !saveFilename) return;
    try {
      await api.saveGame(selected.session_id, saveFilename);
      setSaveFilename('');
    } catch (e) {
      setError(`Failed to save: ${e}`);
    }
  }

  async function handleLoad() {
    if (!selected || !loadFilename) return;
    try {
      await api.loadGame(selected.session_id, loadFilename);
      setLoadFilename('');
    } catch (e) {
      setError(`Failed to load: ${e}`);
    }
  }

  const isActive = selected?.status === 'active';
  const isRunning = selected?.running === true;
  const isArchived = selected?.status === 'archived';
  const canEditSettings = selected && selected.status === 'pending';
  // Show all settings (merge with defaults so all fields appear even if only some stored)
  const displaySettings = selected ? { ...getAllDefaults(), ...selected.settings } : {};

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h5">Sessions</Typography>
        <Stack direction="row" spacing={1}>
          <Tooltip title="Refresh session list">
            <IconButton onClick={fetchSessions}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
          <Button startIcon={<AddIcon />} variant="contained" onClick={() => {
            setNewName(generateSessionName());
            setCreateOpen(true);
          }}>
            New Session
          </Button>
        </Stack>
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
                    (s.status === 'archived' || s.status === 'ended') ? (
                      <Tooltip title="Permanently delete session">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(s.session_id); }}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : undefined
                  }
                  onClick={() => selectSession(s.session_id)}
                  sx={{
                    cursor: 'pointer',
                    bgcolor: selected?.session_id === s.session_id ? 'action.selected' : 'transparent',
                    '&:hover': { bgcolor: 'action.hover' },
                  }}
                >
                  <ListItemText
                    primary={
                      <Stack direction="row" spacing={1} alignItems="center">
                        <span>{s.name}</span>
                        {s.running && (
                          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main' }} />
                        )}
                      </Stack>
                    }
                    secondary={
                      <Chip
                        size="small"
                        label={s.status}
                        color={statusColor(s.status)}
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
              {/* Header */}
              <Card>
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Box>
                      <Typography variant="h6">{selected.name}</Typography>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Typography variant="body2" color="text.secondary">
                          {selected.session_id}
                        </Typography>
                        <Chip size="small" label={selected.status} color={statusColor(selected.status)} />
                        {isRunning && (
                          <Chip size="small" label="running" color="success" variant="outlined" />
                        )}
                      </Stack>
                      {isActive && selected.game_port && (
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          Game port: {selected.game_port} / Admin port: {selected.admin_port}
                        </Typography>
                      )}
                    </Box>
                    <Stack direction="row" spacing={1} alignItems="center">
                      {isActive && (
                        <Button startIcon={<StopIcon />} color="error" variant="outlined" onClick={handleStop}>
                          Stop
                        </Button>
                      )}
                      {canEditSettings && (
                        <Button
                          startIcon={<PlayArrowIcon />}
                          variant="contained"
                          onClick={handleStart}
                          disabled={starting}
                        >
                          {starting ? 'Starting...' : 'Start Game'}
                        </Button>
                      )}
                      {isArchived && (
                        <Typography variant="body2" color="text.secondary">
                          Session archived{selected.end_reason ? ` (${selected.end_reason})` : ''}
                        </Typography>
                      )}
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>

              {/* Settings — always show all fields */}
              <Card>
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                    <Typography variant="subtitle2">Settings</Typography>
                    {canEditSettings && !editingSettings && (
                      <Button size="small" startIcon={<EditIcon />} onClick={startEditSettings}>
                        Edit
                      </Button>
                    )}
                    {editingSettings && (
                      <Stack direction="row" spacing={1}>
                        <Button size="small" onClick={() => setEditingSettings(false)}>Cancel</Button>
                        <Button size="small" variant="contained" onClick={handleSaveSettings}>Save</Button>
                      </Stack>
                    )}
                  </Stack>

                  {editingSettings ? (
                    <SessionSettingsForm
                      values={editSettings}
                      onChange={(key, value) => setEditSettings((prev) => ({ ...prev, [key]: value }))}
                    />
                  ) : (
                    <SessionSettingsForm values={displaySettings} />
                  )}
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

              {/* Save / Load — only when active */}
              {isActive && (
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
              )}

              {/* How to Join / Spectate */}
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>
                    How to Join
                  </Typography>

                  {canEditSettings && (
                    <Alert severity="info" sx={{ mb: 1 }}>
                      Configure settings above, then click <strong>Start Game</strong>. This will spawn a dedicated OpenTTD server for this session.
                    </Alert>
                  )}

                  {isActive && selected.game_port && (
                    <>
                      <Typography variant="subtitle2" sx={{ mt: 1, mb: 0.5 }}>
                        To spectate or play from the OpenTTD client:
                      </Typography>
                      <Box component="ol" sx={{ pl: 2.5, my: 0, '& li': { mb: 0.5 } }}>
                        <Typography component="li" variant="body2" color="text.secondary">
                          Open the <strong>OpenTTD GUI client</strong>.
                        </Typography>
                        <Typography component="li" variant="body2" color="text.secondary">
                          Click <strong>Multiplayer</strong> on the main menu.
                        </Typography>
                        <Typography component="li" variant="body2" color="text.secondary">
                          In the server address field, type{' '}
                          <strong>127.0.0.1:{selected.game_port}</strong>{' '}
                          and press Enter or click <strong>Join</strong>.
                        </Typography>
                        <Typography component="li" variant="body2" color="text.secondary">
                          You join as a <strong>spectator</strong> by default. Open the company list to create or join a company.
                        </Typography>
                      </Box>
                      <Alert severity="info" sx={{ mt: 1.5 }}>
                        <strong>Tip:</strong> Client and server must be the same OpenTTD version (15.2). Each session runs its own server on a unique port.
                      </Alert>
                    </>
                  )}

                  {isArchived && (
                    <Typography variant="body2" color="text.secondary">
                      This session has been archived. Create a new session to start another game.
                    </Typography>
                  )}
                </CardContent>
              </Card>
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
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>New Session</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Session Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            sx={{ mt: 1, mb: 2 }}
          />
          <SessionSettingsForm
            values={newSettings}
            onChange={(key, value) => setNewSettings((prev) => ({ ...prev, [key]: value }))}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate}>Create</Button>
        </DialogActions>
      </Dialog>

      {/* Confirm delete dialog */}
      <Dialog open={confirmDeleteId !== null} onClose={() => setConfirmDeleteId(null)}>
        <DialogTitle>Delete Session Permanently?</DialogTitle>
        <DialogContent>
          <Typography>
            This will permanently remove the session and all its data. This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDeleteId(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={() => confirmDeleteId && handleDelete(confirmDeleteId)}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      {/* Error snackbar */}
      <Snackbar
        open={error !== null}
        autoHideDuration={5000}
        onClose={() => setError(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="error" onClose={() => setError(null)} variant="filled">
          {error}
        </Alert>
      </Snackbar>
    </Box>
  );
}
