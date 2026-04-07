#!/usr/bin/env python3
"""Analyze and compare nttd sessions.

Usage:
    # Compare two sessions, save plots to reports/
    python scripts/analyze_sessions.py ses_4771aa1e1fdb ses_8608a9542696 --output reports/comparison

    # Analyze a single session
    python scripts/analyze_sessions.py ses_8608a9542696

    # Just print summary, no plots
    python scripts/analyze_sessions.py ses_8608a9542696 --summary-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from nttd.analysis.loader import SessionData, load_sessions
from nttd.analysis.plots import generate_all_plots


def print_session_summary(s: SessionData) -> None:
    """Print a text summary of a session."""
    print(f"\n{'=' * 70}")
    print(f"Session: {s.session_id}  ({s.name})")
    print(f"{'=' * 70}")
    print(f"  Model:       {s.model}")
    print(f"  Status:      {s.status}")
    print(f"  Duration:    {s.duration_minutes:.1f} min")
    print(f"  End reason:  {s.end_reason or 'N/A'}")
    print(f"  Settings:    {len(s.settings)} keys")
    print()

    # Agent summary
    print("  Agents:")
    print(f"  {'Agent':<15} {'Cycles':>7} {'Actions':>8} {'OK':>5} {'Fail':>5} {'Rate':>6} {'Avg Decide':>11}")
    print(f"  {'-'*15} {'-'*7} {'-'*8} {'-'*5} {'-'*5} {'-'*6} {'-'*11}")
    total_actions = 0
    total_ok = 0
    for agent_id, info in s.agents.items():
        t = info.get("total_actions", 0)
        ok = info.get("successful_actions", 0)
        fail = info.get("failed_actions", 0)
        rate = ok / t * 100 if t > 0 else 0
        decide = info.get("avg_decide_ms", 0)
        total_actions += t
        total_ok += ok
        print(f"  {agent_id:<15} {info.get('total_cycles', 0):>7} {t:>8} {ok:>5} {fail:>5} {rate:>5.1f}% {decide:>9.0f}ms")

    overall_rate = total_ok / total_actions * 100 if total_actions > 0 else 0
    print(f"  {'TOTAL':<15} {'':>7} {total_actions:>8} {total_ok:>5} {total_actions - total_ok:>5} {overall_rate:>5.1f}%")
    print()

    # Data summary
    print("  Data:")
    print(f"    Actions:      {len(s.actions):>6} rows")
    print(f"    Agent cycles: {len(s.agent_cycles):>6} rows")
    print(f"    Events:       {len(s.events):>6} rows")
    print(f"    Snapshots:    {len(s.snapshots):>6} rows")
    print(f"    Tiles:        {len(s.tiles):>6} rows")

    # Financial summary from snapshots
    if not s.snapshots.empty:
        final = s.snapshots.sort_values("game_date").iloc[-1]
        first = s.snapshots.sort_values("game_date").iloc[0]
        print()
        print("  Finances (Company 0):")
        print(f"    Starting balance: {first['c0_balance']:>12,.0f}")
        print(f"    Final balance:    {final['c0_balance']:>12,.0f}")
        print(f"    Final loan:       {final['c0_loan']:>12,.0f}")
        print(f"    Final income:     {final['c0_income']:>12,.0f}")
        print(f"    Final value:      {final['c0_value']:>12,.0f}")
        print(f"    Vehicles:         {final['num_vehicles']:>12,.0f}")
        print(f"    Stations:         {final['num_stations']:>12,.0f}")

    # Top action types
    if not s.actions.empty:
        print()
        print("  Top Action Types:")
        top = s.actions.groupby("action_type").agg(
            total=("status", "count"),
            ok=("status", lambda x: (x == "success").sum()),
        ).sort_values("total", ascending=False).head(10)
        top["rate"] = top["ok"] / top["total"] * 100
        for action_type, row in top.iterrows():
            print(f"    {action_type:<30} {row['total']:>4} ({row['rate']:>5.1f}% ok)")


def print_comparison(sessions: list[SessionData]) -> None:
    """Print a side-by-side comparison table."""
    print(f"\n{'=' * 70}")
    print("COMPARISON SUMMARY")
    print(f"{'=' * 70}")

    labels = [s.model for s in sessions]
    print(f"  {'Metric':<30} {labels[0]:>18} {labels[1]:>18}")
    print(f"  {'-'*30} {'-'*18} {'-'*18}")

    def row(label: str, vals: list) -> None:
        print(f"  {label:<30} {str(vals[0]):>18} {str(vals[1]):>18}")

    row("Total actions", [len(s.actions) for s in sessions])
    row("Total cycles", [len(s.agent_cycles) for s in sessions])

    for s in sessions:
        total = sum(a.get("total_actions", 0) for a in s.agents.values())
        ok = sum(a.get("successful_actions", 0) for a in s.agents.values())
        s._overall_rate = ok / total * 100 if total > 0 else 0
    row("Overall success rate", [f"{s._overall_rate:.1f}%" for s in sessions])

    if all(not s.snapshots.empty for s in sessions):
        row("Final balance", [f"{s.snapshots.sort_values('game_date').iloc[-1]['c0_balance']:,.0f}" for s in sessions])
        row("Final vehicles", [str(s.snapshots.sort_values('game_date').iloc[-1]['num_vehicles']) for s in sessions])
        row("Final stations", [str(s.snapshots.sort_values('game_date').iloc[-1]['num_stations']) for s in sessions])

    # Per-agent comparison
    all_agents = sorted(set(a for s in sessions for a in s.agents))
    print()
    print(f"  {'Agent Success Rates':<30} {labels[0]:>18} {labels[1]:>18}")
    print(f"  {'-'*30} {'-'*18} {'-'*18}")
    for agent in all_agents:
        vals = []
        for s in sessions:
            info = s.agents.get(agent, {})
            t = info.get("total_actions", 0)
            ok = info.get("successful_actions", 0)
            vals.append(f"{ok}/{t} ({ok/t*100:.0f}%)" if t > 0 else "N/A")
        row(agent, vals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze nttd sessions")
    parser.add_argument("session_ids", nargs="+", help="Session IDs to analyze")
    parser.add_argument("--output", "-o", help="Output directory for plots")
    parser.add_argument("--sessions-dir", default="logs/sessions", help="Sessions data directory")
    parser.add_argument("--summary-only", action="store_true", help="Print text summary only, no plots")
    args = parser.parse_args()

    sessions = load_sessions(args.session_ids, args.sessions_dir)

    # Print summaries
    for s in sessions:
        print_session_summary(s)

    if len(sessions) > 1:
        print_comparison(sessions)

    if args.summary_only:
        return

    # Generate plots
    output_dir = args.output or f"reports/{'_vs_'.join(s.session_id[:8] for s in sessions)}"
    print(f"\nGenerating plots to {output_dir}/ ...")
    figs = generate_all_plots(sessions, output_dir=output_dir)
    print(f"Generated {len(figs)} plots.")
    print(f"Open {output_dir}/02_agent_performance.html in a browser for interactive plots.")


if __name__ == "__main__":
    main()
