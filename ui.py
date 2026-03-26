# ui.py
from rich.table import Table
from rich.panel import Panel
from collections import deque

# Shared memory for the screen
recent_alerts = deque(maxlen=15)

def push_alert(time_str: str, source: str, category: str, title: str):
    """Adds a new breaking headline to the UI memory."""
    recent_alerts.appendleft({
        'time': time_str,
        'source': source,
        'category': category,
        'title': title
    })

def render_dashboard() -> Panel:
    """Draws the Bloomberg-style grid."""
    table = Table(show_lines=True, header_style="bold cyan", expand=True)
    table.add_column("Time", justify="left", style="dim", width=10)
    table.add_column("Source", justify="center", style="bold blue", width=10)
    table.add_column("Category", justify="center", style="bold red", width=16) 
    table.add_column("Live Feed (Zero Latency)", justify="left", style="white")

    for alert in recent_alerts:
        cat_style = alert['category']
        # Dynamic color coding based on the event type
        styled_cat = f"[bold yellow]{cat_style}[/bold yellow]" if "TRUMP" in cat_style else f"[bold magenta]{cat_style}[/bold magenta]"
        table.add_row(alert['time'], alert['source'], styled_cat, alert['title'])

    return Panel(
        table, 
        title="[bold yellow]⚡ MASTER TERMINAL: OMNI-CHANNEL INGESTION ⚡[/bold yellow]", 
        border_style="blue"
    )