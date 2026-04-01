import { createTheme } from '@mui/material/styles';

export function buildTheme(mode: 'light' | 'dark') {
  return createTheme({
    palette: {
      mode,
      ...(mode === 'dark'
        ? {
            background: { default: '#0f172a', paper: '#1e293b' },
            primary: { main: '#3b82f6' },
            secondary: { main: '#8b5cf6' },
            success: { main: '#22c55e' },
            warning: { main: '#f59e0b' },
            error: { main: '#ef4444' },
            text: { primary: '#e2e8f0', secondary: '#94a3b8' },
            divider: '#334155',
          }
        : {
            background: { default: '#f8fafc', paper: '#ffffff' },
            primary: { main: '#2563eb' },
            secondary: { main: '#7c3aed' },
            success: { main: '#16a34a' },
            warning: { main: '#d97706' },
            error: { main: '#dc2626' },
            text: { primary: '#1e293b', secondary: '#64748b' },
            divider: '#e2e8f0',
          }),
    },
    typography: {
      fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
      h4: { fontWeight: 600 },
      h5: { fontWeight: 600 },
      h6: { fontWeight: 600 },
    },
    shape: { borderRadius: 8 },
    components: {
      MuiCard: {
        defaultProps: { variant: 'outlined' },
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: { textTransform: 'none', fontWeight: 500 },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 500 },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: { borderColor: 'inherit' },
        },
      },
    },
  });
}
