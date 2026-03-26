import os
import asyncio
from datetime import datetime
from collections import deque
from telethon import TelegramClient, events
from dotenv import load_dotenv

from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.console import Console

# Load environment variables from the .env file
load_dotenv()

console = Console()

# --- 1. SECURE CREDENTIALS ---
try:
    # We must cast the API_ID to an integer for Telethon
    API_ID = int(os.getenv('TG_API_ID')) 
    API_HASH = os.getenv('TG_API_HASH')
    
    if not API_ID or not API_HASH:
        raise ValueError
except (TypeError, ValueError):
    console.print("[bold red]CRITICAL ERROR:[/bold red] Missing or invalid credentials in .env file.")
    console.print("Please check your .env file and ensure TG_API_ID and TG_API_HASH are set.")
    exit(1)

# --- 2. TARGET CHANNELS & FILTER MATRIX ---
TARGET_CHANNELS = ['tree_news', 'FirstSquawk', 'tier10k', 'geopolitics_live'] 
KEYWORDS = ["trump", "potus", "tariff", "china", "fed", "powell", "cpi", "nfp", "fomc", "white house", "rates", "sec"]

# State management
recent_alerts = deque(maxlen=15)

def generate_dashboard() -> Panel:
    table = Table(show_lines=True, header_style="bold cyan", expand=True)
    table.add_column("Time", justify="left", style="dim", width=10)
    table.add_column("Catalyst", justify="center", style="bold red", width=12)
    table.add_column("Live Feed (Zero Latency)", justify="left", style="white")

    for alert in recent_alerts:
        table.add_row(alert['time'], alert['keyword'], alert['title'])

    return Panel(
        table, 
        title="[bold yellow]⚡ TERMINAL: DIRECT FIREHOSE ⚡[/bold yellow]", 
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
            
        text_lower = text.lower()
        triggered_keyword = next((kw for kw in KEYWORDS if kw in text_lower), None)
        
        if triggered_keyword:
            print("\a", end="") 
            clean_text = text.replace('\n', ' | ')
            
            recent_alerts.appendleft({
                'time': datetime.now().strftime('%H:%M:%S'),
                'keyword': triggered_keyword.upper(),
                'title': clean_text[:120] + ('...' if len(clean_text) > 120 else '')
            })

    recent_alerts.appendleft({
        'time': datetime.now().strftime('%H:%M:%S'),
        'keyword': "SYSTEM",
        'title': "MTProto Connection Established. SECURE MODE ACTIVE."
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