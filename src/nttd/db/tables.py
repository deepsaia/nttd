"""Fully normalized SQLAlchemy table definitions for nttd.

Ref: docs/openttd_study_part4_multiplayer_agent_design.md §13
Time-series pattern: one row per entity per snapshot interval.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)

metadata = MetaData()

# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

sessions = Table(
    "sessions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(256), nullable=False, default=""),
    Column("status", String(32), nullable=False, default="active"),
    Column("created_at", DateTime, server_default=func.now()),
    Column("started_at", DateTime, nullable=True),
    Column("ended_at", DateTime, nullable=True),
    Column("game_start_date", Integer, nullable=True),
    Column("game_end_date", Integer, nullable=True),
    Column("end_reason", String(128), nullable=True),
    Column("game_port", Integer, nullable=True),
    Column("admin_port", Integer, nullable=True),
    Column("pid", Integer, nullable=True),
)

session_settings = Table(
    "session_settings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("key", String(128), nullable=False),
    Column("value", String(512), nullable=False),
    Index("idx_session_settings_lookup", "session_id", "key", unique=True),
)

# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

participants = Table(
    "participants",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("participant_type", String(32), nullable=False),
    Column("participant_id", String(128), nullable=False),
    Column("name", String(256), nullable=True),
    Column("company_id", Integer, nullable=True),
    Column("config", Text, nullable=True),
    Column("joined_at", DateTime, server_default=func.now()),
    Column("left_at", DateTime, nullable=True),
    Index("idx_participants_session", "session_id", "participant_id", unique=True),
)

# ---------------------------------------------------------------------------
# Snapshots (compressed JSON blob for replay only)
# ---------------------------------------------------------------------------

snapshots = Table(
    "snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("snapshot_id", String(64), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("tick", Integer, nullable=True),
    Column("captured_at", DateTime, server_default=func.now()),
    Index("idx_snapshots_session_date", "session_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Companies (time-series: one row per company per snapshot)
# ---------------------------------------------------------------------------

companies = Table(
    "companies",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("name", String(256), nullable=True),
    Column("manager", String(256), nullable=True),
    Column("color", Integer, default=0),
    Column("is_ai", Boolean, default=False),
    Column("is_active", Boolean, default=True),
    Index("idx_companies_ts", "session_id", "company_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Finances (time-series: per company per snapshot)
# ---------------------------------------------------------------------------

finances = Table(
    "finances",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("balance", Integer, default=0),
    Column("loan", Integer, default=0),
    Column("max_loan", Integer, default=0),
    Column("income", Integer, default=0),
    Column("expenses", Integer, default=0),
    Column("company_value", Integer, default=0),
    Column("performance_rating", Integer, default=0),
    Column("cargo_delivered", Integer, default=0),
    Index("idx_finances_ts", "session_id", "company_id", "game_date"),
)

finance_revenue = Table(
    "finance_revenue",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("source", String(32), nullable=False),
    Column("amount", Integer, default=0),
    Index("idx_finance_revenue_ts", "session_id", "company_id", "game_date"),
)

finance_expenses = Table(
    "finance_expenses",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("category", String(32), nullable=False),
    Column("amount", Integer, default=0),
    Index("idx_finance_expenses_ts", "session_id", "company_id", "game_date"),
)

finance_quarterly = Table(
    "finance_quarterly",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("quarter_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("q_income", Integer, default=0),
    Column("q_expenses", Integer, default=0),
    Column("q_cargo_delivered", Integer, default=0),
    Column("q_performance_rating", Integer, default=0),
    Column("q_company_value", Integer, default=0),
    Index("idx_finance_quarterly_ts", "session_id", "company_id", "quarter_date"),
)

# ---------------------------------------------------------------------------
# Infrastructure (time-series: per company per snapshot)
# ---------------------------------------------------------------------------

infrastructure = Table(
    "infrastructure",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("rail_pieces", Integer, default=0),
    Column("road_pieces", Integer, default=0),
    Column("water_pieces", Integer, default=0),
    Column("station_pieces", Integer, default=0),
    Column("airport_pieces", Integer, default=0),
    Column("rail_cost", Integer, default=0),
    Column("road_cost", Integer, default=0),
    Column("water_cost", Integer, default=0),
    Column("station_cost", Integer, default=0),
    Column("airport_cost", Integer, default=0),
    Index("idx_infrastructure_ts", "session_id", "company_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Towns (time-series: one row per town per snapshot)
# ---------------------------------------------------------------------------

towns = Table(
    "towns",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("town_id", Integer, nullable=False),
    Column("name", String(256), nullable=True),
    Column("population", Integer, default=0),
    Column("houses", Integer, default=0),
    Column("x", Integer, default=0),
    Column("y", Integer, default=0),
    Column("is_city", Boolean, default=False),
    Column("growth_rate", Integer, default=0),
    Index("idx_towns_ts", "session_id", "town_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Industries (time-series: one row per industry per snapshot)
# ---------------------------------------------------------------------------

industries = Table(
    "industries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("industry_id", Integer, nullable=False),
    Column("name", String(256), nullable=True),
    Column("type_id", Integer, default=0),
    Column("type_name", String(128), nullable=True),
    Column("x", Integer, default=0),
    Column("y", Integer, default=0),
    Column("is_raw", Boolean, default=False),
    Column("is_processing", Boolean, default=False),
    Index("idx_industries_ts", "session_id", "industry_id", "game_date"),
)

industry_production = Table(
    "industry_production",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("industry_id", Integer, nullable=False),
    Column("cargo_id", Integer, nullable=False),
    Column("cargo_label", String(32), nullable=True),
    Column("produced", Integer, default=0),
    Column("transported_pct", Integer, default=0),
    Index("idx_industry_prod_ts", "session_id", "industry_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Stations (time-series: one row per station per snapshot)
# ---------------------------------------------------------------------------

stations = Table(
    "stations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("station_id", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("name", String(256), nullable=True),
    Column("x", Integer, default=0),
    Column("y", Integer, default=0),
    Column("has_rail", Boolean, default=False),
    Column("has_truck", Boolean, default=False),
    Column("has_bus", Boolean, default=False),
    Column("has_airport", Boolean, default=False),
    Column("has_dock", Boolean, default=False),
    Index("idx_stations_ts", "session_id", "company_id", "station_id", "game_date"),
)

station_cargo = Table(
    "station_cargo",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("station_id", Integer, nullable=False),
    Column("cargo_id", Integer, nullable=False),
    Column("cargo_label", String(32), nullable=True),
    Column("waiting", Integer, default=0),
    Column("rating", Integer, nullable=True),
    Index("idx_station_cargo_ts", "session_id", "station_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Vehicles (time-series: one row per vehicle per snapshot)
# ---------------------------------------------------------------------------

vehicles = Table(
    "vehicles",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("vehicle_id", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("vehicle_type", String(32), nullable=True),
    Column("name", String(256), nullable=True),
    Column("engine_id", Integer, default=0),
    Column("x", Integer, default=0),
    Column("y", Integer, default=0),
    Column("profit_this_year", Integer, default=0),
    Column("profit_last_year", Integer, default=0),
    Column("age", Integer, default=0),
    Column("max_age", Integer, default=0),
    Column("current_speed", Integer, default=0),
    Column("state", Integer, default=0),
    Column("running", Boolean, default=True),
    Column("in_depot", Boolean, default=False),
    Index("idx_vehicles_ts", "session_id", "company_id", "vehicle_id", "game_date"),
)

vehicle_orders = Table(
    "vehicle_orders",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("vehicle_id", Integer, nullable=False),
    Column("order_index", Integer, nullable=False),
    Column("destination_id", Integer, default=0),
    Column("order_type", String(32), nullable=True),
    Column("flags", Integer, default=0),
    Index("idx_vehicle_orders_ts", "session_id", "vehicle_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Subsidies (time-series: one row per subsidy per snapshot)
# ---------------------------------------------------------------------------

subsidies = Table(
    "subsidies",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("subsidy_id", Integer, nullable=False),
    Column("cargo_id", Integer, default=0),
    Column("cargo_label", String(32), nullable=True),
    Column("src_type", String(32), nullable=True),
    Column("src_id", Integer, default=0),
    Column("src_name", String(256), nullable=True),
    Column("dst_type", String(32), nullable=True),
    Column("dst_id", Integer, default=0),
    Column("dst_name", String(256), nullable=True),
    Column("value", Integer, default=0),
    Column("remaining_years", Integer, default=0),
    Index("idx_subsidies_ts", "session_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Cargo Flows (delta counters from GSCargoMonitor)
# ---------------------------------------------------------------------------

cargo_flows = Table(
    "cargo_flows",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("cargo_id", Integer, nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", Integer, nullable=False),
    Column("direction", String(16), nullable=False),
    Column("amount", Integer, default=0),
    Index("idx_cargo_flows_ts", "session_id", "company_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Actions (one row per command from any participant)
# ---------------------------------------------------------------------------

actions = Table(
    "actions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("action_id", String(64), nullable=False),
    Column("participant_id", String(128), nullable=True),
    Column("participant_type", String(32), nullable=True),
    Column("company_id", Integer, nullable=True),
    Column("game_date", Integer, nullable=True),
    Column("action_type", String(64), nullable=False),
    Column("action_mode", String(32), default="atomic"),
    Column("status", String(32), nullable=False),
    Column("error", Text, nullable=True),
    Column("cost", Integer, nullable=True),
    Column("submitted_at", DateTime, nullable=True),
    Column("completed_at", DateTime, nullable=True),
    Index("idx_actions_session", "session_id", "game_date"),
    Index("idx_actions_participant", "session_id", "participant_id"),
)

action_parameters = Table(
    "action_parameters",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("action_id", String(64), nullable=False),
    Column("param_key", String(128), nullable=False),
    Column("param_value", String(512), nullable=True),
    Index("idx_action_params", "action_id"),
)

# ---------------------------------------------------------------------------
# Events (game events: crashes, subsidies, bankruptcies, etc.)
# ---------------------------------------------------------------------------

events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("tick", Integer, nullable=True),
    Column("event_type", String(64), nullable=False),
    Column("company_id", Integer, nullable=True),
    Column("entity_type", String(32), nullable=True),
    Column("entity_id", Integer, nullable=True),
    Column("detail", Text, nullable=True),
    Column("captured_at", DateTime, server_default=func.now()),
    Index("idx_events_session", "session_id", "game_date"),
    Index("idx_events_type", "session_id", "event_type"),
)

# ---------------------------------------------------------------------------
# Messages (chat, agent-to-agent, system)
# ---------------------------------------------------------------------------

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("message_id", String(64), nullable=False),
    Column("game_date", Integer, nullable=True),
    Column("message_type", String(32), nullable=False),
    Column("from_id", String(128), nullable=True),
    Column("to_id", String(128), nullable=True),
    Column("company_id", Integer, nullable=True),
    Column("body", Text, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
    Index("idx_messages_session", "session_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Metrics (generic time-series key-value for dashboard)
# ---------------------------------------------------------------------------

metrics = Table(
    "metrics",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("game_date", Integer, nullable=False),
    Column("company_id", Integer, nullable=True),
    Column("metric_name", String(128), nullable=False),
    Column("metric_value", Float, nullable=False),
    Column("captured_at", DateTime, server_default=func.now()),
    Index("idx_metrics_query", "session_id", "metric_name", "company_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Agent Connections (gameloop connection lifecycle)
# ---------------------------------------------------------------------------

agent_connections = Table(
    "agent_connections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("connection_id", Text, nullable=False),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("agent_id", String(128), nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("framework", String(32), nullable=False),
    Column("model", String(128), nullable=True),
    Column("observation_mode", String(32), default="compact"),
    Column("poll_interval", Float, default=5.0),
    Column("started_at", DateTime, nullable=True),
    Column("stopped_at", DateTime, nullable=True),
    Column("total_cycles", Integer, default=0),
    Column("total_actions", Integer, default=0),
    Column("successful_actions", Integer, default=0),
    Column("failed_actions", Integer, default=0),
    Column("avg_cycle_ms", Float, default=0),
    Column("avg_decide_ms", Float, default=0),
    Index("idx_agent_connections_session", "session_id", "agent_id", unique=True),
)

# ---------------------------------------------------------------------------
# Agent Cycles (per-cycle detail for debugging and analysis)
# ---------------------------------------------------------------------------

agent_cycles = Table(
    "agent_cycles",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("connection_id", Text, nullable=False),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("cycle_number", Integer, nullable=False),
    Column("game_date", Integer, nullable=True),
    Column("observe_ms", Float, nullable=True),
    Column("decide_ms", Float, nullable=True),
    Column("execute_ms", Float, nullable=True),
    Column("total_ms", Float, nullable=True),
    Column("actions_proposed", Integer, default=0),
    Column("actions_executed", Integer, default=0),
    Column("actions_succeeded", Integer, default=0),
    Column("actions_failed", Integer, default=0),
    Column("observation_size_bytes", Integer, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
    Index("idx_agent_cycles_conn", "connection_id", "cycle_number"),
    Index("idx_agent_cycles_session", "session_id", "game_date"),
)

# ---------------------------------------------------------------------------
# Leaderboard (computed per-session rankings)
# ---------------------------------------------------------------------------

leaderboard = Table(
    "leaderboard",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), ForeignKey("sessions.id"), nullable=False),
    Column("company_id", Integer, nullable=False),
    Column("participant_id", String(128), nullable=True),
    Column("participant_type", String(32), nullable=True),
    Column("rank", Integer, nullable=True),
    Column("final_balance", Integer, default=0),
    Column("final_value", Integer, default=0),
    Column("final_rating", Integer, default=0),
    Column("total_cargo", Integer, default=0),
    Column("total_vehicles", Integer, default=0),
    Column("total_stations", Integer, default=0),
    Column("total_actions", Integer, default=0),
    Column("action_success_rate", Float, default=0.0),
    Column("game_days_played", Integer, default=0),
    Column("computed_at", DateTime, server_default=func.now()),
    Index("idx_leaderboard_session", "session_id", "rank"),
)
