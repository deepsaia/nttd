import { useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import PersonOffIcon from '@mui/icons-material/PersonOff';
import SendIcon from '@mui/icons-material/Send';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import { useGameStore } from '../store/gameStore';
import type { EventEntry } from '../store/gameStore';
import * as api from '../api/client';

export default function PlayersPage() {
  const companies = useGameStore((s) => s.companies);
  const clients = useGameStore((s) => s.clients);
  const agents = useGameStore((s) => s.agents);
  const events = useGameStore((s) => s.events);
  const [chatMsg, setChatMsg] = useState('');
  const [messages, setMessages] = useState<api.Message[]>([]);
  const activeSessionId = useGameStore((s) => s.activeSessionId);

  useEffect(() => {
    if (!activeSessionId) return;
    api.getMessageHistory(activeSessionId, 50).then(({ messages: m }) => setMessages(m)).catch(() => {});
  }, [activeSessionId]);

  async function handleSendChat() {
    if (!chatMsg.trim() || !activeSessionId) return;
    try {
      await api.sendMessage(activeSessionId, chatMsg, 'admin');
      setChatMsg('');
      const { messages: m } = await api.getMessageHistory(activeSessionId, 50);
      setMessages(m);
    } catch {
      // error
    }
  }

  const spectators = clients.filter((c) => c.company_id === 255);
  const players = clients.filter((c) => c.company_id !== 255);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" mb={3}>Players & Agents</Typography>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3, mb: 3 }}>
        {/* Connected players */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              Human Players ({players.length})
            </Typography>
            <List dense>
              {players.map((c) => (
                <ListItem
                  key={c.client_id}
                  secondaryAction={
                    <Stack direction="row" spacing={0.5}>
                      <IconButton
                        size="small"
                        title="Move to company"
                        onClick={() => {
                          const target = prompt('Move to company ID:');
                          if (target) api.moveClient(c.client_id, Number(target));
                        }}
                      >
                        <SwapHorizIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        title="Kick"
                        color="error"
                        onClick={() => api.kickClient(c.client_id)}
                      >
                        <PersonOffIcon fontSize="small" />
                      </IconButton>
                    </Stack>
                  }
                >
                  <ListItemText
                    primary={c.name}
                    secondary={`Client #${c.client_id} → Company ${c.company_id}`}
                  />
                </ListItem>
              ))}
              {players.length === 0 && (
                <ListItem><ListItemText secondary="No human players connected" /></ListItem>
              )}
            </List>
          </CardContent>
        </Card>

        {/* Agents */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              AI Agents ({agents.length})
            </Typography>
            <List dense>
              {agents.map((a) => (
                <ListItem key={a.agent_id}>
                  <ListItemText
                    primary={a.agent_id}
                    secondary={
                      <span>
                        Companies: {a.company_scope.join(', ') || 'all'}
                        &nbsp;&middot;&nbsp;
                        Subs: {a.subscriptions.length}
                      </span>
                    }
                  />
                  <Chip size="small" label="online" color="success" variant="outlined" />
                </ListItem>
              ))}
              {agents.length === 0 && (
                <ListItem><ListItemText secondary="No agents connected" /></ListItem>
              )}
            </List>
          </CardContent>
        </Card>
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3, mb: 3 }}>
        {/* Spectators */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              Spectators ({spectators.length})
            </Typography>
            <List dense>
              {spectators.map((c) => (
                <ListItem key={c.client_id}>
                  <ListItemText primary={c.name} secondary={`Client #${c.client_id}`} />
                </ListItem>
              ))}
              {spectators.length === 0 && (
                <ListItem><ListItemText secondary="No spectators" /></ListItem>
              )}
            </List>
          </CardContent>
        </Card>

        {/* Companies overview */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              Companies ({Object.keys(companies).length})
            </Typography>
            <List dense>
              {Object.values(companies).map((c) => (
                <ListItem key={c.id}>
                  <ListItemText
                    primary={`${c.name}`}
                    secondary={
                      <span>
                        {c.is_ai ? 'AI' : 'Human'}
                        &nbsp;&middot; Balance: £{(c.balance ?? 0).toLocaleString()}
                        &nbsp;&middot; Rating: {c.performance_rating ?? '—'}
                      </span>
                    }
                  />
                  <Chip
                    size="small"
                    label={c.is_ai ? 'AI' : 'Human'}
                    color={c.is_ai ? 'info' : 'primary'}
                    variant="outlined"
                  />
                </ListItem>
              ))}
            </List>
          </CardContent>
        </Card>
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3 }}>
        {/* Event feed */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>Live Event Feed</Typography>
            <Paper
              variant="outlined"
              sx={{ maxHeight: 300, overflow: 'auto', p: 1, bgcolor: 'background.default' }}
            >
              {events.length === 0 && (
                <Typography variant="body2" color="text.secondary">No events yet</Typography>
              )}
              {events.map((e: EventEntry) => (
                <Box key={e.id} sx={{ mb: 0.5 }}>
                  <Typography variant="caption" color="text.secondary">{e.time}</Typography>
                  <Typography variant="body2">
                    <Chip size="small" label={e.type} sx={{ mr: 1, height: 18, fontSize: 11 }} />
                    {e.message}
                  </Typography>
                </Box>
              ))}
            </Paper>
          </CardContent>
        </Card>

        {/* Message center */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>Messages</Typography>
            <Paper
              variant="outlined"
              sx={{ maxHeight: 240, overflow: 'auto', p: 1, mb: 1, bgcolor: 'background.default' }}
            >
              {messages.length === 0 && (
                <Typography variant="body2" color="text.secondary">No messages</Typography>
              )}
              {messages.map((m) => (
                <Box key={m.message_id} sx={{ mb: 0.5 }}>
                  <Typography variant="caption" color="text.secondary">
                    {m.from_id || 'system'} → {m.to_id || 'all'}
                  </Typography>
                  <Typography variant="body2">{m.body}</Typography>
                </Box>
              ))}
            </Paper>
            <Divider sx={{ mb: 1 }} />
            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                fullWidth
                placeholder="Send a message..."
                value={chatMsg}
                onChange={(e) => setChatMsg(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendChat()}
              />
              <Button variant="contained" onClick={handleSendChat} disabled={!chatMsg.trim()}>
                <SendIcon />
              </Button>
            </Stack>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
