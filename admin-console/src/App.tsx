import { useMemo } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import Box from '@mui/material/Box';
import { buildTheme } from './theme';
import { useThemeStore } from './store/themeStore';
import { useWebSocket } from './hooks/useWebSocket';
import { usePoller } from './hooks/usePoller';
import TopBar from './components/layout/TopBar';
import Sidebar, { DRAWER_WIDTH } from './components/layout/Sidebar';
import SessionPage from './pages/SessionPage';
import PlayersPage from './pages/PlayersPage';
import MetricsPage from './pages/MetricsPage';
import LeaderboardPage from './pages/LeaderboardPage';

function AppContent() {
  useWebSocket();
  usePoller(3000);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <TopBar />
      <Box sx={{ display: 'flex', flex: 1 }}>
        <Sidebar />
        <Box component="main" sx={{ flex: 1, ml: `${DRAWER_WIDTH}px`, overflow: 'auto' }}>
          <Routes>
            <Route path="/" element={<SessionPage />} />
            <Route path="/players" element={<PlayersPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/leaderboard" element={<LeaderboardPage />} />
          </Routes>
        </Box>
      </Box>
    </Box>
  );
}

export default function App() {
  const mode = useThemeStore((s) => s.mode);
  const theme = useMemo(() => buildTheme(mode), [mode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </ThemeProvider>
  );
}
