import os
import asyncio
import re
from datetime import datetime
from collections import deque
from telethon import TelegramClient, events
from dotenv import load_dotenv

from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.console import Console

load_dotenv()
console = Console()

try:
    API_ID = int(os.getenv('TG_API_ID')) 
    API_HASH = os.getenv('TG_API_HASH')
    if not API_ID or not API_HASH:
        raise ValueError
except (TypeError, ValueError):
    console.print("[bold red]CRITICAL ERROR:[/bold red] Missing credentials in .env file.")
    exit(1)

TARGET_CHANNELS = [
    'newrulesgeo', 
    'rybar_in_english', 
    'intelslava', 
    'ClashReport', 
    'worldnews'
] 

# --- 3. THE INSTITUTIONAL FILTER MATRIX (REGEX) ---
# We compile these expressions for lightning-fast matching.
# \b ensures we match exact words (so 'rate' doesn't trigger on 'corporate')
FILTER_MATRIX = {
    "TRUMP_POLICY": re.compile(r'\b(trump|potus|47)\b.*\b(tariff|sanction|executive order|veto|pardon|sign|china|mexico|nato)\b', re.IGNORECASE),
    "FED_MACRO": re.compile(r'\b(fomc|powell|yellen|cpi|ppi|nfp|inflation|basis points?|bps|rate (cut|hike|decision))\b', re.IGNORECASE),
    "GEO_ESCALATION": re.compile(r'\b(nuclear|airstrike|ballistic|mobilization|strait of hormuz|blockade|brics|embargo)\b', re.IGNORECASE),
    "COMMODITIES": re.compile(r'\b(opec\+?|brent crude|wti|strategic petroleum reserve|spr|gold|lng|supply chain)\b', re.IGNORECASE)
}

recent_alerts = deque(maxlen=15)

def generate_dashboard() -> Panel:
    table = Table(show_lines=True, header_style="bold cyan", expand=True)
    table.add_column("Time", justify="left", style="dim", width=10)
    # Upgraded column to show the Category of the alert
    table.add_column("Category", justify="center", style="bold red", width=16) 
    table.add_column("Live Feed (Zero Latency)", justify="left", style="white")

    for alert in recent_alerts:
        # Dynamically color the category tag based on what it is
        cat_style = alert['category']
        styled_cat = f"[bold yellow]{cat_style}[/bold yellow]" if "TRUMP" in cat_style else f"[bold magenta]{cat_style}[/bold magenta]"
        
        table.add_row(alert['time'], styled_cat, alert['title'])

    return Panel(
        table, 
        title="[bold yellow]⚡ TERMINAL: GEOPOLITICAL & MACRO FIREHOSE ⚡[/bold yellow]", 
        border_style="blue"
    )

async def ui_loop(live_ui):
    while True:
        live_ui.update(generate_dashboard())
        await asyncio.sleep(0.25)

async def main():
    client = TelegramClient('terminal_session', API_ID, API_HASH)
    
    await client.start()
    await asyncio.sleep(1) 

    @client.on(events.NewMessage(chats=TARGET_CHANNELS))
    async def handler(event):
        text = event.message.message
        if not text: 
            return
            
        # Clean text for display first
        clean_text = text.replace('\n', ' | ')
        
        # --- THE FILTER GATE ---
        triggered_category = None
        
        for category_name, regex_pattern in FILTER_MATRIX.items():
            if regex_pattern.search(text):
                triggered_category = category_name
                break # Stop searching once we find a match
        
        if triggered_category:
            print("\a", end="") # Audio beep
            
            recent_alerts.appendleft({
                'time': datetime.now().strftime('%H:%M:%S'),
                'category': triggered_category,
                'title': clean_text[:120] + ('...' if len(clean_text) > 120 else '')
            })

    recent_alerts.appendleft({
        'time': datetime.now().strftime('%H:%M:%S'),
        'category': "SYSTEM",
        'title': "Regex Filter Engine Online. SECURE MODE ACTIVE."
    })

    with Live(generate_dashboard(), screen=True) as live_ui:
        ui_task = asyncio.create_task(ui_loop(live_ui))
        await client.run_until_disconnected()
        ui_task.cancel()

if __name__ == "__main__":
    console.clear()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.clear()
        print("\nTerminal shut down safely.")