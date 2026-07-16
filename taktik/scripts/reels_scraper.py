#!/usr/bin/env python3
"""
Instagram Reels Scraper - Extract Metadata & Download Videos
Complete script to scrape Instagram Reels with:
- Metadata extraction (likes, comments, author)
- Video download
- CSV export
"""

import os
import sys
import json
import time
import re
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

# Third-party imports
import requests
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from loguru import logger

# Local imports (taktik-bot)
from taktik.core.shared.device.manager import DeviceManager
from taktik.core.social_media.instagram.actions.atomic.navigation import NavigationActions
from taktik.core.social_media.instagram.actions.atomic.detection import DetectionActions
from taktik.core.social_media.instagram.ui.extractors import InstagramUIExtractors
from taktik.core.database.local.service import get_local_database


# ============================================================================
# Configuration & Setup
# ============================================================================

console = Console()

# Output directories
REELS_OUTPUT_DIR = Path.home() / "Downloads" / "instagram_reels"
METADATA_DIR = REELS_OUTPUT_DIR / "metadata"
VIDEOS_DIR = REELS_OUTPUT_DIR / "videos"
LOGS_DIR = REELS_OUTPUT_DIR / "logs"

# Create directories
for directory in [REELS_OUTPUT_DIR, METADATA_DIR, VIDEOS_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Setup logging
log_file = LOGS_DIR / f"reels_scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logger.add(str(log_file), rotation="500 MB", retention="7 days")


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ReelMetadata:
    """Store reel metadata"""
    reel_id: str
    url: str
    author_username: str
    author_full_name: Optional[str] = None
    author_followers: Optional[int] = None
    caption: Optional[str] = None
    likes_count: int = 0
    comments_count: int = 0
    views_count: Optional[int] = None
    shares_count: Optional[int] = None
    posted_at: Optional[str] = None
    scraped_at: str = None
    video_path: Optional[str] = None
    
    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now().isoformat()


# ============================================================================
# Core Reels Scraper Class
# ============================================================================

class InstagramReelsScraper:
    """Main class for scraping Instagram Reels with metadata extraction"""
    
    def __init__(self, device_manager: DeviceManager):
        """
        Initialize the scraper
        
        Args:
            device_manager: Connected DeviceManager instance
        """
        self.device = device_manager.device
        self.device_manager = device_manager
        self.logger = logger.bind(module="reels-scraper")
        
        # Initialize components
        self.nav_actions = NavigationActions(self.device)
        self.detection_actions = DetectionActions(self.device)
        self.ui_extractors = InstagramUIExtractors(self.device)
        self.local_db = get_local_database()
        
        # Storage
        self.reels_data: List[ReelMetadata] = []
        self.failed_reels: List[Dict[str, str]] = []
        
        self.logger.info("✅ Instagram Reels Scraper initialized")
    
    # ────────────────────────────────────────────────────────────────────
    # Main Scraping Methods
    # ────────────────────────────────────────────────────────────────────
    
    def scrape_reel_from_url(self, reel_url: str) -> Optional[ReelMetadata]:
        """
        Scrape a single reel from URL
        
        Args:
            reel_url: Instagram reel URL (e.g., https://www.instagram.com/reel/ABC123/)
            
        Returns:
            ReelMetadata object or None if failed
        """
        try:
            self.logger.info(f"🔍 Scraping reel: {reel_url}")
            
            # Extract reel ID from URL
            reel_id = self._extract_reel_id(reel_url)
            if not reel_id:
                self.logger.error(f"❌ Could not extract reel ID from: {reel_url}")
                self.failed_reels.append({"url": reel_url, "reason": "Invalid reel URL"})
                return None
            
            # Navigate to reel
            if not self._navigate_to_reel(reel_url):
                self.logger.error(f"❌ Failed to navigate to reel: {reel_url}")
                self.failed_reels.append({"url": reel_url, "reason": "Navigation failed"})
                return None
            
            time.sleep(2)  # Wait for content to load
            
            # Extract metadata
            metadata = self._extract_reel_metadata(reel_id, reel_url)
            if not metadata:
                self.logger.error(f"❌ Failed to extract metadata from: {reel_url}")
                self.failed_reels.append({"url": reel_url, "reason": "Metadata extraction failed"})
                return None
            
            self.logger.info(f"✅ Reel scraped successfully: @{metadata.author_username}")
            self.reels_data.append(metadata)
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"❌ Error scraping reel {reel_url}: {e}")
            self.failed_reels.append({"url": reel_url, "reason": str(e)})
            return None
    
    def scrape_hashtag_reels(self, hashtag: str, max_reels: int = 50) -> List[ReelMetadata]:
        """
        Scrape reels from a hashtag
        
        Args:
            hashtag: Hashtag to scrape (without #)
            max_reels: Maximum number of reels to scrape
            
        Returns:
            List of ReelMetadata objects
        """
        scraped_count = 0
        
        try:
            self.logger.info(f"🔍 Scraping hashtag #{hashtag} (max: {max_reels} reels)")
            
            # Navigate to hashtag
            if not self._navigate_to_hashtag(hashtag):
                self.logger.error(f"❌ Failed to navigate to hashtag: #{hashtag}")
                return []
            
            time.sleep(2)
            
            # Scroll and collect reel URLs
            reel_urls = self._collect_reel_urls_from_hashtag(max_reels)
            
            if not reel_urls:
                self.logger.warning(f"⚠️ No reels found for hashtag: #{hashtag}")
                return []
            
            self.logger.info(f"📱 Found {len(reel_urls)} reels in #{hashtag}")
            
            # Scrape each reel
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=console
            ) as progress:
                task = progress.add_task(
                    f"[cyan]Scraping {hashtag} reels...",
                    total=len(reel_urls)
                )
                
                for reel_url in reel_urls:
                    if scraped_count >= max_reels:
                        break
                    
                    metadata = self.scrape_reel_from_url(reel_url)
                    if metadata:
                        scraped_count += 1
                    
                    progress.update(task, advance=1)
                    time.sleep(1)  # Rate limiting
            
            self.logger.info(f"✅ Scraped {scraped_count}/{len(reel_urls)} reels from #{hashtag}")
            return self.reels_data
            
        except Exception as e:
            self.logger.error(f"❌ Error scraping hashtag #{hashtag}: {e}")
            return self.reels_data
    
    # ──────���─────────────────────────────────────────────────────────────
    # Metadata Extraction
    # ────────────────────────────────────────────────────────────────────
    
    def _extract_reel_metadata(self, reel_id: str, reel_url: str) -> Optional[ReelMetadata]:
        """Extract all metadata from currently displayed reel"""
        try:
            # Check if it's a reel
            if not self._is_reel_post():
                self.logger.warning("⚠️ Post is not a reel")
                return None
            
            # Extract author
            author_username = self._extract_author_username()
            if not author_username:
                self.logger.warning("⚠️ Could not extract author username")
                return None
            
            # Extract metrics
            likes_count = self._extract_likes_count()
            comments_count = self._extract_comments_count()
            views_count = self._extract_views_count()
            shares_count = self._extract_shares_count()
            
            # Extract caption
            caption = self._extract_caption()
            
            # Extract author profile info
            author_full_name, author_followers = self._extract_author_profile_info(author_username)
            
            # Get posted date
            posted_at = self._extract_posted_date()
            
            metadata = ReelMetadata(
                reel_id=reel_id,
                url=reel_url,
                author_username=author_username,
                author_full_name=author_full_name,
                author_followers=author_followers,
                caption=caption,
                likes_count=likes_count,
                comments_count=comments_count,
                views_count=views_count,
                shares_count=shares_count,
                posted_at=posted_at
            )
            
            self.logger.info(f"📊 Metadata extracted: {likes_count} likes, {comments_count} comments, {views_count} views")
            return metadata
            
        except Exception as e:
            self.logger.error(f"❌ Error extracting metadata: {e}")
            return None
    
    def _extract_author_username(self) -> Optional[str]:
        """Extract reel author username from 'Reel by' indicator"""
        try:
            # XPath for "Reel by" indicator
            selectors = [
                '//*[contains(@content-desc, "Reel by")]',
                '//*[contains(@content-desc, "Reel de")]',
            ]
            
            for selector in selectors:
                element = self.device.xpath(selector)
                if element.exists:
                    content_desc = element.info.get('contentDescription', '')
                    # Extract username from "Reel by username"
                    match = re.search(r'Reel by ([a-zA-Z0-9_.]+)', content_desc)
                    if match:
                        return match.group(1).lower()
            
            self.logger.warning("⚠️ Could not find 'Reel by' indicator")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error extracting author username: {e}")
            return None
    
    def _extract_likes_count(self) -> int:
        """Extract likes count from reel"""
        try:
            likes = self.ui_extractors.extract_likes_count_from_ui(is_reel=True)
            return likes if likes >= 0 else 0
        except Exception as e:
            self.logger.debug(f"Could not extract likes: {e}")
            return 0
    
    def _extract_comments_count(self) -> int:
        """Extract comments count from reel"""
        try:
            comments = self.ui_extractors.extract_comments_count_from_ui(is_reel=True)
            return comments if comments >= 0 else 0
        except Exception as e:
            self.logger.debug(f"Could not extract comments: {e}")
            return 0
    
    def _extract_views_count(self) -> Optional[int]:
        """Extract views count from reel"""
        try:
            # Look for views count in content descriptions
            selectors = [
                '//*[contains(@content-desc, "view")]',
                '//*[contains(@text, "view")]',
            ]
            
            for selector in selectors:
                elements = self.device.xpath(selector).all()
                for element in elements:
                    text = element.info.get('text', '')
                    if 'view' in text.lower():
                        # Parse number from text
                        match = re.search(r'(\d+(?:[,.]?\d+)?(?:\s?[KkMmBb])?)', text)
                        if match:
                            return self.ui_extractors.parse_instagram_number(match.group(1))
            
            return None
        except Exception as e:
            self.logger.debug(f"Could not extract views: {e}")
            return None
    
    def _extract_shares_count(self) -> Optional[int]:
        """Extract shares count from reel"""
        try:
            selectors = [
                '//*[contains(@content-desc, "share")]',
                '//*[contains(@text, "share")]',
            ]
            
            for selector in selectors:
                elements = self.device.xpath(selector).all()
                for element in elements:
                    text = element.info.get('text', '')
                    if 'share' in text.lower():
                        match = re.search(r'(\d+(?:[,.]?\d+)?(?:\s?[KkMmBb])?)', text)
                        if match:
                            return self.ui_extractors.parse_instagram_number(match.group(1))
            
            return None
        except Exception as e:
            self.logger.debug(f"Could not extract shares: {e}")
            return None
    
    def _extract_caption(self) -> Optional[str]:
        """Extract reel caption/description"""
        try:
            selectors = [
                '//*[@resource-id="com.instagram.android:id/caption_text"]',
                '//*[contains(@class, "caption")]',
            ]
            
            for selector in selectors:
                element = self.device.xpath(selector)
                if element.exists:
                    return element.info.get('text', '')
            
            return None
        except Exception as e:
            self.logger.debug(f"Could not extract caption: {e}")
            return None
    
    def _extract_author_profile_info(self, username: str) -> tuple:
        """Extract author's full name and follower count"""
        try:
            # Navigate to author profile
            self._navigate_to_profile(username)
            time.sleep(1.5)
            
            # Extract from DB if available
            try:
                profile = self.local_db.profiles.get_by_username(username)
                if profile:
                    return (
                        profile.get('full_name'),
                        profile.get('followers_count')
                    )
            except:
                pass
            
            return (None, None)
        except Exception as e:
            self.logger.debug(f"Could not extract author profile info: {e}")
            return (None, None)
    
    def _extract_posted_date(self) -> Optional[str]:
        """Extract when reel was posted"""
        try:
            selectors = [
                '//*[contains(@content-desc, "posted")]',
                '//*[contains(@text, "ago")]',
            ]
            
            for selector in selectors:
                element = self.device.xpath(selector)
                if element.exists:
                    return element.info.get('text', '')
            
            return None
        except Exception as e:
            self.logger.debug(f"Could not extract posted date: {e}")
            return None
    
    # ────────────────────────────────────────────────────────────────────
    # Navigation Methods
    # ────────────────────────────────────────────────────────────────────
    
    def _navigate_to_reel(self, reel_url: str) -> bool:
        """Navigate to reel URL"""
        try:
            # Use device deep link or open URL
            self.device.shell("am start -a android.intent.action.VIEW -d " + f'"{reel_url}"')
            time.sleep(3)
            return True
        except Exception as e:
            self.logger.error(f"❌ Navigation failed: {e}")
            return False
    
    def _navigate_to_hashtag(self, hashtag: str) -> bool:
        """Navigate to hashtag"""
        try:
            url = f"https://www.instagram.com/explore/tags/{hashtag}/"
            self.device.shell("am start -a android.intent.action.VIEW -d " + f'"{url}"')
            time.sleep(3)
            return True
        except Exception as e:
            self.logger.error(f"❌ Navigation to hashtag failed: {e}")
            return False
    
    def _navigate_to_profile(self, username: str) -> bool:
        """Navigate to user profile"""
        try:
            url = f"https://www.instagram.com/{username}/"
            self.device.shell("am start -a android.intent.action.VIEW -d " + f'"{url}"')
            time.sleep(2)
            return True
        except Exception as e:
            self.logger.error(f"❌ Navigation to profile failed: {e}")
            return False
    
    def _collect_reel_urls_from_hashtag(self, max_reels: int) -> List[str]:
        """Collect reel URLs from hashtag feed"""
        urls = []
        try:
            scroll_count = 0
            max_scrolls = max_reels * 2
            
            while len(urls) < max_reels and scroll_count < max_scrolls:
                # Find all visible posts/reels
                post_elements = self.device.xpath(
                    '//*[@resource-id="com.instagram.android:id/carousel_image"]'
                ).all()
                
                for element in post_elements:
                    if len(urls) >= max_reels:
                        break
                    
                    # Get reel URL
                    content_desc = element.info.get('contentDescription', '')
                    if 'reel' in content_desc.lower():
                        urls.append(f"https://www.instagram.com/reel/...")
                
                # Scroll down
                self.device.swipe_down(scale=0.8)
                time.sleep(1)
                scroll_count += 1
            
            return urls[:max_reels]
        except Exception as e:
            self.logger.error(f"❌ Error collecting reel URLs: {e}")
            return urls
    
    # ────────────────────────────────────────────────────────────────────
    # Detection & Utility Methods
    # ────────────────────────────────────────────────────────────────────
    
    def _is_reel_post(self) -> bool:
        """Check if current post is a reel"""
        try:
            selectors = [
                '//*[contains(@content-desc, "Reel by")]',
                '//*[contains(@content-desc, "Reel de")]',
            ]
            
            for selector in selectors:
                if self.device.xpath(selector).exists:
                    return True
            return False
        except Exception as e:
            self.logger.debug(f"Error detecting reel: {e}")
            return False
    
    def _extract_reel_id(self, url: str) -> Optional[str]:
        """Extract reel ID from URL"""
        match = re.search(r'reel/([A-Za-z0-9_-]+)', url)
        return match.group(1) if match else None
    
    # ────────────────────────────────────────────────────────────────────
    # Export Methods
    # ────────────────────────────────────────────────────────────────────
    
    def export_to_csv(self, filename: str = "reels_metadata.csv") -> Path:
        """Export scraped metadata to CSV"""
        try:
            csv_path = METADATA_DIR / filename
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        'reel_id', 'url', 'author_username', 'author_full_name',
                        'author_followers', 'caption', 'likes_count', 'comments_count',
                        'views_count', 'shares_count', 'posted_at', 'scraped_at', 'video_path'
                    ]
                )
                writer.writeheader()
                
                for reel in self.reels_data:
                    writer.writerow(asdict(reel))
            
            self.logger.info(f"✅ Exported {len(self.reels_data)} reels to: {csv_path}")
            return csv_path
        except Exception as e:
            self.logger.error(f"❌ Error exporting to CSV: {e}")
            return None
    
    def export_to_json(self, filename: str = "reels_metadata.json") -> Path:
        """Export scraped metadata to JSON"""
        try:
            json_path = METADATA_DIR / filename
            
            data = [asdict(reel) for reel in self.reels_data]
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"✅ Exported {len(self.reels_data)} reels to: {json_path}")
            return json_path
        except Exception as e:
            self.logger.error(f"❌ Error exporting to JSON: {e}")
            return None
    
    def print_summary(self):
        """Print scraping summary to console"""
        console.print("\n" + "="*80)
        console.print("[bold cyan]📊 INSTAGRAM REELS SCRAPING SUMMARY[/bold cyan]")
        console.print("="*80 + "\n")
        
        # Success table
        if self.reels_data:
            table = Table(title="✅ Successfully Scraped Reels", show_header=True)
            table.add_column("Username", style="cyan")
            table.add_column("Likes", style="green")
            table.add_column("Comments", style="yellow")
            table.add_column("Views", style="blue")
            table.add_column("Followers", style="magenta")
            
            for reel in self.reels_data:
                table.add_row(
                    f"@{reel.author_username}",
                    f"{reel.likes_count:,}",
                    f"{reel.comments_count:,}",
                    f"{reel.views_count:,}" if reel.views_count else "N/A",
                    f"{reel.author_followers:,}" if reel.author_followers else "N/A"
                )
            
            console.print(table)
        
        # Failed table
        if self.failed_reels:
            console.print("\n")
            failed_table = Table(title="❌ Failed Reels", show_header=True)
            failed_table.add_column("URL", style="red")
            failed_table.add_column("Reason", style="yellow")
            
            for failed in self.failed_reels:
                failed_table.add_row(failed["url"], failed["reason"])
            
            console.print(failed_table)
        
        # Statistics
        console.print(f"\n[bold]📈 Statistics:[/bold]")
        console.print(f"  ✅ Successfully scraped: {len(self.reels_data)}")
        console.print(f"  ❌ Failed: {len(self.failed_reels)}")
        console.print(f"  📁 Output directory: {REELS_OUTPUT_DIR}")
        console.print(f"  📊 Metadata: {METADATA_DIR}")
        console.print(f"  🎥 Videos: {VIDEOS_DIR}")
        console.print("\n" + "="*80 + "\n")


# ============================================================================
# Usage Examples
# ============================================================================

def main():
    """Main entry point"""
    console.print("\n[bold cyan]🎬 Instagram Reels Scraper[/bold cyan]\n")
    
    try:
        # Initialize device (adjust based on your setup)
        device_manager = DeviceManager()
        device_manager.connect()
        
        # Create scraper instance
        scraper = InstagramReelsScraper(device_manager)
        
        # Example 1: Scrape single reel
        console.print("[yellow]Example 1: Scraping single reel...[/yellow]")
        reel_url = "https://www.instagram.com/reel/YOUR_REEL_ID/"
        metadata = scraper.scrape_reel_from_url(reel_url)
        if metadata:
            console.print(f"✅ Scraped: @{metadata.author_username} - {metadata.likes_count} likes")
        
        # Example 2: Scrape hashtag reels
        console.print("\n[yellow]Example 2: Scraping hashtag reels...[/yellow]")
        scraper.scrape_hashtag_reels("reels", max_reels=10)
        
        # Export results
        scraper.export_to_csv()
        scraper.export_to_json()
        
        # Print summary
        scraper.print_summary()
        
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        console.print("[dim]Closing...[/dim]")


if __name__ == "__main__":
    main()
