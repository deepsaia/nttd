import AppBar from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Box from '@mui/material/Box';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import { useGameStore } from '../../store/gameStore';
import { useThemeStore } from '../../store/themeStore';
import * as api from '../../api/client';

function gameDateToString(date: number): string {
  if (!date || date <= 0) return '\u2014';
  const year = Math.floor(date / 365);
  const dayOfYear = date % 365;
  const month = Math.floor(dayOfYear / 30) + 1;
  const day = (dayOfYear % 30) + 1;
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export default function TopBar() {
  const status = useGameStore((s) => s.status);
  const connected = useGameStore((s) => s.connected);
  const activeSessionId = useGameStore((s) => s.activeSessionId);
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  const paused = status?.paused ?? true;

  async function handlePauseToggle() {
    if (!activeSessionId) return;
    try {
      if (paused) {
        await api.unpauseGame(activeSessionId);
      } else {
        await api.pauseGame(activeSessionId);
      }
    } catch {
      // ignore
    }
  }

  return (
    <AppBar position="static" color="default" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
      <Toolbar sx={{ gap: 2 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, mr: 1 }}>
          nttd
        </Typography>

        <Chip
          size="small"
          icon={<FiberManualRecordIcon sx={{ fontSize: 10 }} />}
          label={connected ? 'Connected' : 'Disconnected'}
          color={connected ? 'success' : 'error'}
          variant="outlined"
        />

        {status && activeSessionId && (
          <>
            <Chip size="small" label={gameDateToString(status.game_date)} variant="outlined" />
            <Chip size="small" label={status.mode} variant="outlined" color="info" />
            <Chip size="small" label={`${Object.keys(useGameStore.getState().companies).length} companies`} variant="outlined" />

            <Tooltip title={paused ? 'Unpause' : 'Pause'}>
              <IconButton size="small" onClick={handlePauseToggle} color={paused ? 'warning' : 'success'}>
                {paused ? <PlayArrowIcon /> : <PauseIcon />}
              </IconButton>
            </Tooltip>

            {/*
              A speed slider used to live here. OpenTTD 15.3 has no runtime
              game-speed setting, so it never did anything: the rcon call failed
              while the API reported success. The economy clock is fixed at
              1 wall-minute per economy month.
            */}
          </>
        )}

        <Box sx={{ flex: 1 }} />

        <Tooltip title={`Switch to ${mode === 'dark' ? 'light' : 'dark'} mode`}>
          <IconButton size="small" onClick={toggle}>
            {mode === 'dark' ? <Brightness7Icon /> : <Brightness4Icon />}
          </IconButton>
        </Tooltip>
      </Toolbar>
    </AppBar>
  );
}
