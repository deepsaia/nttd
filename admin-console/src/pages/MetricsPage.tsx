import { useCallback, useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar,
} from 'recharts';
import * as api from '../api/client';
import type { FinancePoint } from '../api/client';
import { useGameStore } from '../store/gameStore';

const COMPANY_COLORS = [
  '#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#f97316', '#14b8a6', '#a855f7',
  '#64748b', '#84cc16', '#e11d48', '#0ea5e9', '#d946ef',
];

const fmtMoney = (v: unknown) => `£${Number(v).toLocaleString()}`;

export default function MetricsPage() {
  const companies = useGameStore((s) => s.companies);
  const activeSessionId = useGameStore((s) => s.activeSessionId);
  const [selectedCompany, setSelectedCompany] = useState<number | 'all'>('all');
  const [financeData, setFinanceData] = useState<Record<number, FinancePoint[]>>({});
  const [mergedTimeline, setMergedTimeline] = useState<Record<string, unknown>[]>([]);

  const companyList = Object.values(companies);
  const sessionId = activeSessionId || '';

  const fetchFinances = useCallback(async () => {
    if (!sessionId) return;
    const data: Record<number, FinancePoint[]> = {};
    for (const c of companyList) {
      try {
        const { data: d } = await api.getFinanceSeries(sessionId, c.id);
        data[c.id] = d;
      } catch {
        // ignore
      }
    }
    setFinanceData(data);

    // Merge into timeline for multi-company line chart
    const dateMap: Record<number, Record<string, unknown>> = {};
    for (const [cid, points] of Object.entries(data)) {
      for (const p of points) {
        if (!dateMap[p.game_date]) {
          dateMap[p.game_date] = { game_date: p.game_date };
        }
        dateMap[p.game_date][`balance_${cid}`] = p.balance;
        dateMap[p.game_date][`value_${cid}`] = p.company_value;
        dateMap[p.game_date][`income_${cid}`] = p.income;
      }
    }
    setMergedTimeline(Object.values(dateMap).sort((a, b) => (a.game_date as number) - (b.game_date as number)));
  }, [sessionId, companyList.length]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchFinances();
    const timer = setInterval(fetchFinances, 10000);
    return () => clearInterval(timer);
  }, [fetchFinances]);

  const singleCompanyData = selectedCompany !== 'all' ? (financeData[selectedCompany] || []) : [];

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h5">Metrics & Timeline</Typography>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Company</InputLabel>
          <Select
            value={selectedCompany}
            label="Company"
            onChange={(e) => setSelectedCompany(e.target.value as number | 'all')}
          >
            <MenuItem value="all">All Companies</MenuItem>
            {companyList.map((c) => (
              <MenuItem key={c.id} value={c.id}>{c.name} (#{c.id})</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {!sessionId && (
        <Card><CardContent>
          <Typography color="text.secondary">Select or create a session on the Session page first.</Typography>
        </CardContent></Card>
      )}

      {sessionId && (
        <Stack spacing={3}>
          {/* Balance over time — all companies */}
          {selectedCompany === 'all' && (
            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>Balance Over Time</Typography>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={mergedTimeline}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="game_date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `£${(Number(v) / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={fmtMoney} />
                    <Legend />
                    {companyList.map((c, i) => (
                      <Line
                        key={c.id}
                        dataKey={`balance_${c.id}`}
                        name={c.name}
                        stroke={COMPANY_COLORS[i % COMPANY_COLORS.length]}
                        dot={false}
                        strokeWidth={2}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* Company value over time — all companies */}
          {selectedCompany === 'all' && (
            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>Company Value Over Time</Typography>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={mergedTimeline}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="game_date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `£${(Number(v) / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={fmtMoney} />
                    <Legend />
                    {companyList.map((c, i) => (
                      <Line
                        key={c.id}
                        dataKey={`value_${c.id}`}
                        name={c.name}
                        stroke={COMPANY_COLORS[i % COMPANY_COLORS.length]}
                        dot={false}
                        strokeWidth={2}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* Single company detail charts */}
          {selectedCompany !== 'all' && singleCompanyData.length > 0 && (
            <>
              {/* Balance + Income + Expenses */}
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>
                    Financial Overview — {companies[String(selectedCompany)]?.name}
                  </Typography>
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={singleCompanyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="game_date" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `£${(Number(v) / 1000).toFixed(0)}k`} />
                      <Tooltip formatter={fmtMoney} />
                      <Legend />
                      <Line dataKey="balance" stroke="#3b82f6" dot={false} strokeWidth={2} />
                      <Line dataKey="income" stroke="#22c55e" dot={false} strokeWidth={2} />
                      <Line dataKey="expenses" stroke="#ef4444" dot={false} strokeWidth={2} />
                      <Line dataKey="company_value" stroke="#f59e0b" dot={false} strokeWidth={2} />
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Performance rating */}
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>Performance Rating</Typography>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={singleCompanyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="game_date" tick={{ fontSize: 11 }} />
                      <YAxis domain={[0, 1000]} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="performance_rating" fill="#8b5cf6" />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Cargo delivered */}
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>Cargo Delivered</Typography>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={singleCompanyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="game_date" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="cargo_delivered" fill="#06b6d4" />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </>
          )}

          {/* Summary cards */}
          {selectedCompany === 'all' && companyList.length > 0 && (
            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>Company Comparison (Latest)</Typography>
                <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 2 }}>
                  {companyList.map((c, i) => (
                    <Card key={c.id} variant="outlined">
                      <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
                        <Stack direction="row" alignItems="center" spacing={1} mb={0.5}>
                          <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: COMPANY_COLORS[i % COMPANY_COLORS.length] }} />
                          <Typography variant="subtitle2">{c.name}</Typography>
                        </Stack>
                        <Typography variant="body2">Balance: £{(c.balance ?? 0).toLocaleString()}</Typography>
                        <Typography variant="body2">Value: £{(c.company_value ?? 0).toLocaleString()}</Typography>
                        <Typography variant="body2">Rating: {c.performance_rating ?? '—'}</Typography>
                        <Chip size="small" label={c.is_ai ? 'AI' : 'Human'} sx={{ mt: 0.5 }} />
                      </CardContent>
                    </Card>
                  ))}
                </Box>
              </CardContent>
            </Card>
          )}
        </Stack>
      )}
    </Box>
  );
}
