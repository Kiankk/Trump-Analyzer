# main.py
import os
import asyncio
import aiohttp
import feedparser
from datetime import datetime
from telethon import TelegramClient, events
from dotenv import load_dotenv

from rich.live import Live
from rich.console import Console

# Import your custom libraries!
from filters import analyze_text
from ui import push_alert, render_dashboard

load_dotenv()
console = Console()

# --- SECURE CREDENTIALS ---
try:
    API_ID = int(os.getenv('TG_API_ID')) 
    API_HASH = os.getenv('TG_API_HASH')
except (TypeError, ValueError):
    console.print("[bold red]CRITICAL ERROR:[/bold red] Missing credentials in .env file.")
    exit(1)

# --- DATA CONFIG ---
TARGET_CHANNELS = ['newrulesgeo', 'rybar_in_english', 'intelslava', 'ClashReport', 'worldnews'] 
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=%22Donald+Trump%22+OR+POTUS+OR+Tariffs+when:1h",
    "https://news.google.com/rss/search?q=Federal+Reserve+OR+CPI+OR+NFP+OR+Powell+when:1h",
    "https://finance.yahoo.com/news/rssindex"
]

seen_rss_links = set()

# --- ASYNC TASKS ---
async def ui_refresh_loop(live_ui):
    """Redraws the screen 4 times a second."""
    while True:
        live_ui.update(render_dashboard())
        await asyncio.sleep(0.25)

async def fetch_rss(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            return feedparser.parse(await response.text())
    except:
        return None

async def poll_rss_feeds():
    """Polls the web in the background."""
    async with aiohttp.ClientSession() as session:
        while True:
            tasks = [fetch_rss(session, url) for url in RSS_FEEDS]
            results = await asyncio.gather(*tasks)
            
            for feed in results:
                if not feed or not hasattr(feed, 'entries'): continue
                
                for entry in feed.entries:
                    if entry.link in seen_rss_links: continue
                    
                    # Call your custom library
                    category = analyze_text(entry.title)
                    if category:
                        print("\a", end="") # System Beep
                        push_alert(datetime.now().strftime('%H:%M:%S'), 'WEB/RSS', category, entry.title[:120])
                        seen_rss_links.add(entry.link)
            
            await asyncio.sleep(15)

# --- MAIN EXECUTION ---
async def main():
    client = TelegramClient('terminal_session', API_ID, API_HASH)
    await client.start()

    # Telegram MTProto Listener
    @client.on(events.NewMessage(chats=TARGET_CHANNELS))
    async def telegram_handler(event):
        # Call your custom library
        category = analyze_text(event.message.message)
        
        if category:
            print("\a", end="") 
            clean_text = event.message.message.replace('\n', ' | ')
            push_alert(datetime.now().strftime('%H:%M:%S'), 'TELEGRAM', category, clean_text[:120])

    # Boot initialization
    push_alert(datetime.now().strftime('%H:%M:%S'), 'SYSTEM', 'BOOT', "Omni-Channel Engine Online. Merging Web and MTProto Firehose...")

    # Run all tasks concurrently
    with Live(render_dashboard(), screen=True) as live_ui:
        ui_task = asyncio.create_task(ui_refresh_loop(live_ui))
        rss_task = asyncio.create_task(poll_rss_feeds())
        
        await client.run_until_disconnected()
        
        ui_task.cancel()
        rss_task.cancel()

if __name__ == "__main__":
    console.clear()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.clear()
        print("\nTerminal shut down safely.")