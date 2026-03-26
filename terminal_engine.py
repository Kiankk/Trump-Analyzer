import asyncio
import aiohttp
import feedparser
from datetime import datetime
from collections import deque

from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.console import Console

console = Console()

# 1. The Data Sources
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=%22Donald+Trump%22+OR+POTUS+OR+Tariffs+when:1h",
    "https://news.google.com/rss/search?q=Federal+Reserve+OR+CPI+OR+NFP+OR+Powell+when:1h",
    "https://finance.yahoo.com/news/rssindex"
]

# 2. The Filter Matrix
KEYWORDS = ["trump", "potus", "tariff", "china", "fed", "powell", "cpi", "nfp", "fomc", "white house"]

# State management
seen_articles = set()
# Keep exactly 15 of the most recent alerts for the UI
recent_alerts = deque(maxlen=15) 

def generate_dashboard() -> Panel:
    """Creates the Bloomberg-style UI element."""
    table = Table(show_lines=True, header_style="bold cyan", expand=True)
    table.add_column("Time", justify="left", style="dim", width=10)
    table.add_column("Catalyst Keyword", justify="center", style="bold red", width=15)
    table.add_column("Breaking Headline", justify="left", style="white")

    # Populate table with our recent alerts
    for alert in recent_alerts:
        table.add_row(alert['time'], alert['keyword'], alert['title'])

    # Wrap the table in a stylized border
    return Panel(
        table, 
        title="[bold yellow]⚡ TERMINAL: TRUMP & MACRO FUTURES ⚡[/bold yellow]", 
        border_style="blue"
    )

async def fetch_feed(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            text = await response.text()
            return feedparser.parse(text)
    except:
        return None

async def poll_feeds(live_ui):
    """The main loop."""
    async with aiohttp.ClientSession() as session:
        while True:
            tasks = [fetch_feed(session, url) for url in RSS_FEEDS]
            results = await asyncio.gather(*tasks)
            
            new_alert_found = False

            for feed in results:
                if not feed or not hasattr(feed, 'entries'): 
                    continue
                
                for entry in feed.entries:
                    link = entry.link
                    if link in seen_articles:
                        continue
                        
                    title = entry.title
                    title_lower = title.lower()
                    
                    # Check for keywords
                    triggered_keyword = next((kw for kw in KEYWORDS if kw in title_lower), None)
                    
                    if triggered_keyword:
                        # Cross-platform audio beep
                        print("\a", end="") 
                        
                        # Add to our UI memory
                        recent_alerts.appendleft({
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'keyword': triggered_keyword.upper(),
                            'title': title
                        })
                        seen_articles.add(link)
                        new_alert_found = True

            # If we found new data, instantly update the visual dashboard
            if new_alert_found:
                live_ui.update(generate_dashboard())
                
            # Wait 15 seconds before pinging again
            await asyncio.sleep(15)

if __name__ == "__main__":
    console.clear()
    
    # Setup initial empty UI
    recent_alerts.appendleft({
        'time': datetime.now().strftime('%H:%M:%S'),
        'keyword': "SYSTEM",
        'title': "Connecting to nodes... waiting for catalysts."
    })
    
    # Run the Live UI context manager
    with Live(generate_dashboard(), refresh_per_second=4, screen=True) as live_ui:
        try:
            asyncio.run(poll_feeds(live_ui))
        except KeyboardInterrupt:
            pass
            
    console.print("[bold red]Terminal offline.[/bold red]")