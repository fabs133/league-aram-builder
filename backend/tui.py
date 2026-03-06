"""
ARAM Oracle — Live Terminal UI
Polls the in-game API and prints recommendations using Rich.
"""
import time
import sys
import os
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.columns import Columns
from rich import box

from backend.static_data.loader import StaticData
from backend.workflow.pipeline import Pipeline
from backend.collectors.lcda import get_raw_game_data, parse_game_snapshot
from backend.storage.db import init_db
from backend.models import GamePhase, GameSnapshot, PipelineResult

console = Console()

# State for augment tracking (not available from LCDA)
chosen_augments: list[str] = []
augment_choices: list[str] = []
current_phase: GamePhase = GamePhase.IN_GAME


def build_header(champion_name: str, game_time: float, gold: int, phase: str) -> Panel:
    minutes = int(game_time) // 60
    seconds = int(game_time) % 60
    header_text = Text()
    header_text.append("ARAM ORACLE", style="bold magenta")
    header_text.append(f"  |  ", style="dim")
    header_text.append(f"{champion_name}", style="bold cyan")
    header_text.append(f"  |  ", style="dim")
    header_text.append(f"{minutes}:{seconds:02d}", style="yellow")
    header_text.append(f"  |  ", style="dim")
    header_text.append(f"{gold}g", style="bold green")
    header_text.append(f"  |  ", style="dim")
    header_text.append(f"{phase}", style="dim italic")
    return Panel(header_text, box=box.HEAVY, style="bright_blue")


def build_items_table(items: list[str], static_data: StaticData) -> Panel:
    table = Table(title="Current Items", box=box.SIMPLE, show_header=False,
                  title_style="bold white", expand=True)
    table.add_column("Item", style="white")

    if not items:
        table.add_row("[dim]No items yet[/dim]")
    else:
        for item_id in items:
            item = static_data.get_item(item_id)
            name = item.name if item else f"#{item_id}"
            table.add_row(name)

    return Panel(table, box=box.ROUNDED, style="blue", title="Inventory")


def build_enemies_table(enemies: list[str], static_data: StaticData) -> Panel:
    table = Table(box=box.SIMPLE, show_header=False, expand=True)
    table.add_column("Enemy", style="red")

    if not enemies:
        table.add_row("[dim]Unknown[/dim]")
    else:
        for eid in enemies:
            champ = static_data.get_champion(eid)
            name = champ.name if champ else eid
            cc_info = ""
            if champ and champ.cc_profile and champ.cc_profile.total_hard_cc_sec > 0:
                cc_info = f" [yellow]({champ.cc_profile.total_hard_cc_sec:.1f}s CC)[/yellow]"
            table.add_row(f"{name}{cc_info}")

    return Panel(table, box=box.ROUNDED, style="red", title="Enemies")


def build_recommendations_panel(result: PipelineResult, static_data: StaticData) -> Panel:
    if not result.recommendations:
        return Panel("[dim]No augment choices to evaluate[/dim]",
                     title="Augment Recommendations", box=box.DOUBLE, style="magenta")

    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_edge=False)
    table.add_column("#", style="bold", width=3)
    table.add_column("Augment", style="bold white", min_width=20)
    table.add_column("Score", style="bold green", width=8, justify="right")
    table.add_column("Label", style="cyan", width=20)
    table.add_column("Core Items", style="yellow", min_width=30)
    table.add_column("Why", style="dim", min_width=30)

    for i, rec in enumerate(result.recommendations):
        rank = f"{'>>>' if i == 0 else f' {i+1}.'}"
        rank_style = "bold green" if i == 0 else "dim"

        label_str = f"{rec.label[0]} · {rec.label[1]}"

        core_names = []
        for item_id in rec.core_items:
            item = static_data.get_item(item_id)
            core_names.append(item.name if item else item_id)
        core_str = " → ".join(core_names)

        score_str = f"{rec.score:.3f}"

        table.add_row(
            Text(rank, style=rank_style),
            rec.augment_name,
            score_str,
            label_str,
            core_str,
            rec.explanation,
        )

    title = "Augment Recommendations"
    if result.suggest_reroll:
        title += " [bold red]⟳ REROLL SUGGESTED[/bold red]"

    panel = Panel(table, title=title, box=box.DOUBLE, style="magenta")
    return panel


def build_build_panel(result: PipelineResult, static_data: StaticData) -> Panel:
    bs = result.build_state
    table = Table(box=box.SIMPLE, show_header=True, expand=True)
    table.add_column("Slot", style="dim", width=5)
    table.add_column("Item", style="bold white")
    table.add_column("Status", style="dim", width=12)

    for i, item_id in enumerate(bs.full_build):
        item = static_data.get_item(item_id)
        name = item.name if item else item_id

        if item_id in bs.purchased_items:
            status = "[green]Owned[/green]"
        elif item_id == bs.next_item_id:
            status = "[bold yellow]BUY NEXT[/bold yellow]"
        else:
            status = "[dim]Planned[/dim]"

        table.add_row(f"{i+1}", name, status)

    footer = ""
    if bs.next_item_id:
        next_item = static_data.get_item(bs.next_item_id)
        footer = f"Next: {next_item.name if next_item else bs.next_item_id}"
    elif bs.gold_to_next > 0:
        footer = f"[red]Need {bs.gold_to_next}g more for next item[/red]"

    return Panel(table, title="Recommended Build", subtitle=footer,
                 box=box.ROUNDED, style="green")


def build_reroll_banner(result: PipelineResult) -> Panel | None:
    if not result.suggest_reroll:
        return None
    return Panel(
        f"[bold red]{result.reroll_reason}[/bold red]",
        title="⟳ Reroll Advisory",
        box=box.DOUBLE,
        style="bold red",
    )


def build_augment_status() -> Panel:
    lines = []
    if chosen_augments:
        lines.append(f"[green]Chosen: {', '.join(chosen_augments)}[/green]")
    else:
        lines.append("[dim]No augments chosen yet[/dim]")

    if augment_choices:
        lines.append(f"[yellow]Evaluating: {', '.join(augment_choices)}[/yellow]")

    lines.append("")
    lines.append("[dim]Commands: [bold]a[/bold]=set augment choices  "
                 "[bold]c[/bold]=mark chosen  [bold]q[/bold]=quit[/dim]")

    return Panel("\n".join(lines), title="Augment Tracker", box=box.ROUNDED, style="yellow")


def render_dashboard(result: PipelineResult | None, snapshot: GameSnapshot | None,
                     static_data: StaticData) -> list:
    panels = []

    if snapshot and result:
        champ = static_data.get_champion(snapshot.champion_id)
        champ_name = champ.name if champ else snapshot.champion_id

        panels.append(build_header(champ_name, snapshot.game_time,
                                   snapshot.current_gold, snapshot.phase.value))

        # Middle row: items + enemies side by side
        items_panel = build_items_table(snapshot.purchased_items, static_data)
        enemies_panel = build_enemies_table(snapshot.enemy_champion_ids, static_data)
        panels.append(Columns([items_panel, enemies_panel], expand=True, equal=True))

        # Augment status
        panels.append(build_augment_status())

        # Recommendations
        panels.append(build_recommendations_panel(result, static_data))

        # Reroll banner
        reroll = build_reroll_banner(result)
        if reroll:
            panels.append(reroll)

        # Build
        panels.append(build_build_panel(result, static_data))
    else:
        panels.append(Panel(
            "[bold yellow]Waiting for game...[/bold yellow]\n\n"
            "[dim]Start an ARAM game and this dashboard will activate automatically.\n"
            "The Live Client Data API runs on https://127.0.0.1:2999 during a match.[/dim]\n\n"
            "[dim]Commands: [bold]a[/bold]=set augment choices  "
            "[bold]c[/bold]=mark chosen  [bold]q[/bold]=quit[/dim]",
            title="ARAM ORACLE",
            box=box.DOUBLE,
            style="bright_blue",
        ))

    return panels


def handle_input(static_data: StaticData):
    """Non-blocking input handler between poll cycles."""
    global augment_choices, chosen_augments

    console.print("\n[bold cyan]Enter command:[/bold cyan] ", end="")
    try:
        cmd = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if cmd == "q":
        return False
    elif cmd == "a":
        console.print("[yellow]Enter augment IDs or names (comma-separated):[/yellow] ", end="")
        try:
            raw = input().strip()
        except (EOFError, KeyboardInterrupt):
            return True

        if raw:
            # Try to find augments by name or ID
            candidates = [x.strip() for x in raw.split(",")]
            resolved = []
            for c in candidates:
                # Search by name first
                found = None
                for aug in static_data.all_augments():
                    if aug.name.lower() == c.lower() or aug.id == c:
                        found = aug.id
                        break
                if found:
                    resolved.append(found)
                    console.print(f"  [green]Found: {found}[/green]")
                else:
                    # Try partial match
                    matches = [a for a in static_data.all_augments()
                               if c.lower() in a.name.lower()]
                    if matches:
                        console.print(f"  [yellow]Matches for '{c}':[/yellow]")
                        for m in matches[:5]:
                            console.print(f"    {m.id}: {m.name}")
                        console.print(f"  [yellow]Using first match: {matches[0].name}[/yellow]")
                        resolved.append(matches[0].id)
                    else:
                        console.print(f"  [red]'{c}' not found, using as raw ID[/red]")
                        resolved.append(c)

            augment_choices = resolved
            console.print(f"[green]Set {len(augment_choices)} augment choices[/green]")

    elif cmd == "c":
        if augment_choices:
            console.print(f"[yellow]Which augment was chosen? (1-{len(augment_choices)}):[/yellow] ", end="")
            try:
                idx = int(input().strip()) - 1
                if 0 <= idx < len(augment_choices):
                    chosen_augments.append(augment_choices[idx])
                    console.print(f"[green]Marked {augment_choices[idx]} as chosen[/green]")
                    augment_choices = []
            except (ValueError, EOFError, KeyboardInterrupt):
                pass
        else:
            console.print("[red]No augment choices set. Use 'a' first.[/red]")

    elif cmd == "s":
        # Search augments
        console.print("[yellow]Search augments:[/yellow] ", end="")
        try:
            query = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return True
        matches = [a for a in static_data.all_augments() if query in a.name.lower()]
        for m in matches[:10]:
            console.print(f"  {m.id}: [bold]{m.name}[/bold] (T{m.tier.value}) - {m.description[:60]}")
        if len(matches) > 10:
            console.print(f"  ... and {len(matches) - 10} more")

    return True


def main():
    console.print(Panel(
        "[bold magenta]ARAM ORACLE[/bold magenta] — Live Game Dashboard\n\n"
        "[dim]Loading static data...[/dim]",
        box=box.DOUBLE,
    ))

    init_db()
    static_data = StaticData()
    static_data.load()

    champ_count = len(static_data._champions)
    aug_count = len(static_data._augments)
    item_count = len(static_data._items)
    console.print(f"[green]Loaded {champ_count} champions, {aug_count} augments, {item_count} items[/green]\n")

    pipeline = Pipeline(static_data)

    console.print("[bold]Commands:[/bold]")
    console.print("  [cyan]a[/cyan] = set augment choices (enter IDs or search by name)")
    console.print("  [cyan]c[/cyan] = mark which augment you chose")
    console.print("  [cyan]s[/cyan] = search augments by name")
    console.print("  [cyan]q[/cyan] = quit")
    console.print()

    poll_interval = 3.0
    last_result = None
    last_snapshot = None

    while True:
        # Poll game data
        raw = get_raw_game_data()
        if raw:
            snapshot = parse_game_snapshot(raw, current_phase)
            # Inject our tracked augment state
            snapshot.augment_choices = list(augment_choices)
            snapshot.chosen_augments = list(chosen_augments)

            result = pipeline.run(snapshot)
            if result:
                last_result = result
                last_snapshot = snapshot

                # Clear and render
                os.system("cls" if os.name == "nt" else "clear")
                for panel in render_dashboard(result, snapshot, static_data):
                    console.print(panel)
        else:
            if last_result is None:
                os.system("cls" if os.name == "nt" else "clear")
                for panel in render_dashboard(None, None, static_data):
                    console.print(panel)

        # Handle user input with timeout
        import select
        if os.name == "nt":
            import msvcrt
            # Check if key pressed (non-blocking on Windows)
            if msvcrt.kbhit():
                if not handle_input(static_data):
                    break
            else:
                time.sleep(poll_interval)
        else:
            # Unix: use select
            ready, _, _ = select.select([sys.stdin], [], [], poll_interval)
            if ready:
                if not handle_input(static_data):
                    break


if __name__ == "__main__":
    main()
