# Session Analyzer

Modular analysis system for nttd session data. Generates reports from parquet
files, renders to terminal/markdown/PNG/JSON, and serves data via API.

## Architecture

```
src/nttd/analysis/
    loader.py              -- SessionData, load_session(), fragment support
    date_utils.py          -- OpenTTD game date conversions
    plots.py               -- 15 reusable Plotly visualization functions
    reports/
        registry.py        -- ReportResult, @register decorator, run_reports()
        renderer.py        -- render_markdown(), render_plots(), render_json()
        video.py           -- generate_video() for screenshot timelapse
        session_summary.py -- Session overview (config, duration, agents)
        agent_performance.py -- Per-agent metrics (actions, success rate, latency)
        financial.py       -- Company finances (balance, income, loan, infra costs)
        cargo_delivery.py  -- Cargo and transport mode revenue
        vehicle_fleet.py   -- Vehicle roster, profits, type breakdown
        infrastructure.py  -- Build actions, stations, depots
        events_timeline.py -- Chronological game events
        action_analysis.py -- Action type distribution, failure patterns
        orders.py          -- Vehicle orders, routes
        world_state.py     -- Towns, industries, subsidies, cargo flows
        tile_map.py        -- Terrain heatmap from tile data
```

## Data Sources

All data lives in `logs/sessions/<session_id>/`:

| File | Content |
|------|---------|
| `session.parquet` | Session metadata, settings, timestamps (single-row) |
| `actions.parquet` | Action history (type, status, agent, error) |
| `result.parquet` | One row per scored company, with reported per-model spend |
| `events.parquet` | Game events (session_start, agent_start/stop) |
| `snapshots.parquet` | Full game state snapshots (companies, vehicles, towns, etc.) |
| `tiles.parquet` | Terrain data (height, slope, water/coast/buildable flags) |
| `screenshot/` | PNG screenshots for timelapse video (only created when enabled) |
| `save/` | Periodic game saves (only created when enabled) |
| `_fragments/` | In-progress session data (auto-merged on stop) |

The loader uses polars for fast parquet I/O and supports reading from
`_fragments/` when merged files don't exist yet (in-progress sessions).

## Reports

Each report module exposes a `generate(sessions)` function that returns a
`ReportResult` with structured data, Plotly figures, and markdown text.

All reports include a **period header** showing the game date range (date_from,
date_to, total_days). This is injected automatically by `run_reports()` into the
markdown (blockquote after the title), JSON (`data["period"]` dict), and plot
subtitles. Year-boundary metrics (last_year, total) only appear after a full
game year has elapsed.

| Report | Key Metrics | Figures |
|--------|-------------|---------|
| `session_summary` | Config, duration, agent list | Overview table |
| `agent_performance` | Actions, success rate, latency | 4 charts |
| `financial` | Balance, income (this_year/last_year/total), loan, infra costs | 2 timeseries |
| `cargo_delivery` | Vehicle profits by transport mode (this_year/last_year/total) | Transport finances |
| `vehicle_fleet` | Vehicle roster, profit ranking (this_year/last_year/total) | Entity growth |
| `infrastructure` | Build counts by type/agent | 2 charts |
| `events_timeline` | Chronological events | Timeline scatter |
| `action_analysis` | Action types, top errors | 3 charts |
| `orders` | Order chains, routes, per-vehicle profits (this_year/last_year/total) | -- |
| `route_completion` | Route build success/failure, profitability | -- |
| `cargo_routes` | Cargo flow per route, delivery counts | -- |
| `cargo_distances` | Delivery distances by cargo type | -- |
| `world_state` | Towns, industries, subsidies, cargo | -- |
| `tile_map` | Terrain height, water %, town/station overlay | Heatmap |

## CLI Usage

```bash
# Print all reports to terminal (default -- no files saved)
nttd analyze ses_abc123

# Print specific reports
nttd analyze ses_abc123 --reports session_summary,financial

# Print as JSON
nttd analyze ses_abc123 --json

# Save to files
nttd analyze ses_abc123 --save markdown,png
nttd analyze ses_abc123 --save markdown,png,json,html

# Custom output directory
nttd analyze ses_abc123 --save png --output-dir results/

# Generate video timelapse
nttd analyze ses_abc123 --save png --video

# Compare multiple sessions
nttd analyze ses_abc123 --compare ses_def456,ses_ghi789

# Open saved report in browser
nttd analyze ses_abc123 --save markdown --open
```

## API Endpoints

The analysis API serves the same report data as the CLI, for frontend consumption.

```
GET /analysis/{session_id}/reports
    Returns: {"session_id": "...", "reports": ["session_summary", ...]}

GET /analysis/{session_id}/report/{report_name}
    Returns: {"name": "...", "title": "...", "data": {...}, "figures": [...], "markdown": "..."}
    Query: ?compare=ses_other1,ses_other2

GET /analysis/{session_id}/report/{report_name}/plot/{plot_name}
    Returns: PNG image (or HTML with ?fmt=html)
    Query: ?compare=ses_other1,ses_other2
```

## Adding a New Report

1. Create `src/nttd/analysis/reports/my_report.py`
2. Use the `@register("my_report")` decorator on a `generate()` function
3. Add the import to `ensure_reports_loaded()` in `registry.py`

```python
from nttd.analysis.loader import SessionData
from nttd.analysis.reports.registry import ReportResult, register


@register("my_report")
def generate(sessions: list[SessionData]) -> ReportResult:
    data = {"key": "value"}
    md = "# My Report\n\nContent here."
    return ReportResult(
        name="my_report",
        title="My Report",
        data=data,
        figures=[],
        markdown=md,
    )
```

Reports should be agent-agnostic. Don't hardcode agent names or types.
Iterate over whatever agents and actions exist in the session data.

## ReportResult

```python
@dataclass
class ReportResult:
    name: str                           # Registry key
    title: str                          # Human-readable title
    data: dict[str, Any]                # JSON-serializable for frontend
    figures: list[tuple[str, Figure]]   # (name, plotly figure) pairs
    markdown: str                       # Rendered markdown text
```

- `data` should be JSON-serializable (no numpy arrays, no DataFrames)
- `figures` are Plotly Figure objects, rendered to PNG/HTML by the renderer
- `markdown` is printed to terminal and saved to `report.md`

## Dependencies

- **polars** -- fast parquet I/O (used by loader)
- **plotly** -- interactive charts
- **kaleido** -- static PNG export from Plotly
- **imageio[ffmpeg]** -- video generation (optional)
