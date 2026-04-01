import { useCallback, useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Tab from '@mui/material/Tab';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TableSortLabel from '@mui/material/TableSortLabel';
import Tabs from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import RefreshIcon from '@mui/icons-material/Refresh';
import Stack from '@mui/material/Stack';
import * as api from '../api/client';
import type { LeaderboardEntry, GlobalLeaderboardEntry } from '../api/client';
import { useGameStore } from '../store/gameStore';

type SortKey = keyof LeaderboardEntry;
type SortDir = 'asc' | 'desc';

export default function LeaderboardPage() {
  const [tab, setTab] = useState(0);
  const activeSessionId = useGameStore((s) => s.activeSessionId);
  const [sessionBoard, setSessionBoard] = useState<LeaderboardEntry[]>([]);
  const [globalBoard, setGlobalBoard] = useState<GlobalLeaderboardEntry[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>('rank');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const sessionId = activeSessionId || '';

  const fetchSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      const { leaderboard } = await api.getSessionLeaderboard(sessionId);
      setSessionBoard(leaderboard);
    } catch {
      // ignore
    }
  }, [sessionId]);

  const fetchGlobal = useCallback(async () => {
    try {
      const { leaderboard } = await api.getGlobalLeaderboard();
      setGlobalBoard(leaderboard);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchSession();
    fetchGlobal();
  }, [fetchSession, fetchGlobal]);

  async function handleCompute() {
    if (!sessionId) return;
    await api.computeLeaderboard(sessionId);
    await fetchSession();
  }

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  const sorted = [...sessionBoard].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    if (av < bv) return sortDir === 'asc' ? -1 : 1;
    if (av > bv) return sortDir === 'asc' ? 1 : -1;
    return 0;
  });

  const SESSION_COLUMNS: { key: SortKey; label: string; format?: (v: unknown) => string }[] = [
    { key: 'rank', label: '#' },
    { key: 'company_id', label: 'Company' },
    { key: 'participant_id', label: 'Player' },
    { key: 'final_balance', label: 'Balance', format: (v) => `£${Number(v).toLocaleString()}` },
    { key: 'final_value', label: 'Value', format: (v) => `£${Number(v).toLocaleString()}` },
    { key: 'final_rating', label: 'Rating' },
    { key: 'total_cargo', label: 'Cargo' },
    { key: 'total_actions', label: 'Actions' },
    { key: 'action_success_rate', label: 'Success %', format: (v) => `${(Number(v) * 100).toFixed(1)}%` },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" mb={3}>Leaderboard</Typography>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Session" />
        <Tab label="Global" />
      </Tabs>

      {tab === 0 && (
        <Card>
          <CardContent>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
              <Typography variant="subtitle2">
                Session Leaderboard {sessionId && <Chip size="small" label={sessionId} sx={{ ml: 1 }} />}
              </Typography>
              <Button
                startIcon={<RefreshIcon />}
                variant="outlined"
                size="small"
                onClick={handleCompute}
                disabled={!sessionId}
              >
                Recompute
              </Button>
            </Stack>

            {sessionBoard.length === 0 ? (
              <Typography color="text.secondary">
                No leaderboard data. Click "Recompute" to generate rankings from current game state.
              </Typography>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {SESSION_COLUMNS.map((col) => (
                        <TableCell key={col.key}>
                          <TableSortLabel
                            active={sortKey === col.key}
                            direction={sortKey === col.key ? sortDir : 'asc'}
                            onClick={() => handleSort(col.key)}
                          >
                            {col.label}
                          </TableSortLabel>
                        </TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {sorted.map((row) => (
                      <TableRow key={row.company_id} hover>
                        {SESSION_COLUMNS.map((col) => (
                          <TableCell key={col.key}>
                            {col.format
                              ? col.format(row[col.key])
                              : String(row[col.key] ?? '—')}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </CardContent>
        </Card>
      )}

      {tab === 1 && (
        <Card>
          <CardContent>
            <Typography variant="subtitle2" mb={2}>Global Leaderboard (Cross-Session)</Typography>
            {globalBoard.length === 0 ? (
              <Typography color="text.secondary">
                No cross-session data yet. Rankings appear after sessions are completed and computed.
              </Typography>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Player</TableCell>
                      <TableCell>Type</TableCell>
                      <TableCell>Sessions</TableCell>
                      <TableCell>Avg Rank</TableCell>
                      <TableCell>Total Cargo</TableCell>
                      <TableCell>Avg Success %</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {globalBoard.map((row) => (
                      <TableRow key={row.participant_id} hover>
                        <TableCell>{row.participant_id}</TableCell>
                        <TableCell>
                          <Chip size="small" label={row.participant_type} color={row.participant_type === 'agent' ? 'info' : 'default'} />
                        </TableCell>
                        <TableCell>{row.sessions}</TableCell>
                        <TableCell>{Number(row.avg_rank).toFixed(1)}</TableCell>
                        <TableCell>{Number(row.total_cargo).toLocaleString()}</TableCell>
                        <TableCell>{(Number(row.avg_success_rate) * 100).toFixed(1)}%</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
