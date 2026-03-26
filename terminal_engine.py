import asyncio
import aiohttp
import feedparser
import time
from datetime import datetime

# 1. The Zero-Cost Data Sources
# Using advanced Google News search operators to create custom RSS feeds
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=%22Donald+Trump%22+OR+POTUS+OR+Tariffs+when:1h",
    "https://news.google.com/rss/search?q=Federal+Reserve+OR+CPI+OR+NFP+OR+Powell+when:1h",
    "https://finance.yahoo.com/news/rssindex"
]

# 2. The Filter Matrix
# The headline must contain one of these words to trigger an alert
KEYWORDS = ["trump", "potus", "tariff", "china", "fed", "powell", "cpi", "nfp", "fomc", "white house"]

# Memory buffer to prevent showing the same news twice
seen_articles = set()

async def fetch_feed(session, url):
    """Fetches the XML data from the RSS feed asynchronously."""
    try:
        # 10-second timeout so a dead feed doesn't hang the program
        async with session.get(url, timeout=10) as response:
            text = await response.text()
            return feedparser.parse(text)
    except Exception as e:
        # Silently fail if a feed drops connection, keep the terminal running
        return None

async def poll_feeds():
    """The main loop that pings all sources simultaneously."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Booting up Terminal Engine Phase 1...")
    print("Monitoring for Trump & Macro catalysts. Press Ctrl+C to stop.\n")
    print("-" * 50)
    
    async with aiohttp.ClientSession() as session:
        while True:
            # Fire all requests at the exact same time
            tasks = [fetch_feed(session, url) for url in RSS_FEEDS]
            results = await asyncio.gather(*tasks)
            
            for feed in results:
                if not feed or not hasattr(feed, 'entries'): 
                    continue
                
                # Check the latest headlines
                for entry in feed.entries:
                    link = entry.link
                    
                    # Skip if we already alerted you about this
                    if link in seen_articles:
                        continue
                        
                    title = entry.title
                    title_lower = title.lower()
                    
                    # 3. The Filter Gate
                    if any(kw in title_lower for kw in KEYWORDS):
                        
                        # Basic ANSI color coding for terminal visibility
                        time_stamp = datetime.now().strftime('%H:%M:%S')
                        print(f"\033[91m[ALERT]\033[0m \033[90m{time_stamp}\033[0m")
                        print(f"\033[93mHeadline:\033[0m {title}")
                        print(f"\033[94mSource:\033[0m   {link}\n")
                        
                        # Add to memory so it doesn't repeat
                        seen_articles.add(link)
                        
            # Wait 15 seconds before pinging again to avoid IP bans from Google/Yahoo
            await asyncio.sleep(15)

if __name__ == "__main__":
    # Run the async loop
    try:
        asyncio.run(poll_feeds())
    except KeyboardInterrupt:
        print("\nTerminal shut down safely.")