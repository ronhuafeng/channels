import os
import time
import telegram
import sqlite3
import re
import os
import time
import sqlite3
import asyncio
import re
import argparse
from datetime import datetime, timezone
from mastodon import Mastodon
from mastodon.types_base import PaginatableList
from mastodon.return_types import Status
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# Configuration from environment variables
MASTODON_USER_ID = os.getenv('MASTODON_USER_ID') # The numeric ID of the user to track

MASTODON_INSTANCE_URL = os.getenv('MASTODON_INSTANCE_URL', 'https://mastodon.social') # e.g., 'https://mastodon.social'
MASTODON_ACCESS_TOKEN = os.getenv('MASTODON_ACCESS_TOKEN')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_IDS = os.getenv('TELEGRAM_CHANNEL_IDS', '').split(',')
TELEGRAM_CHANNEL_IDS = [channel_id.strip() for channel_id in TELEGRAM_CHANNEL_IDS if channel_id.strip()]  # Clean up whitespace

# How often to check for new posts (in seconds)
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '300')) # 5 minutes

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_NAME = os.getenv('DATABASE_NAME', os.path.join(SCRIPT_DIR, 'synced_posts.db'))

# Validate required environment variables
def validate_config():
    """Validate that all required environment variables are set."""
    required_vars = {
        'MASTODON_USER_ID': MASTODON_USER_ID,
        'MASTODON_ACCESS_TOKEN': MASTODON_ACCESS_TOKEN,
        'TELEGRAM_BOT_TOKEN': TELEGRAM_BOT_TOKEN,
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file and ensure all required variables are set.")
        exit(1)
    
    if not TELEGRAM_CHANNEL_IDS:
        print("Error: TELEGRAM_CHANNEL_IDS is not set or empty.")
        print("Please provide at least one Telegram channel ID.")
        exit(1)

def clean_html_for_telegram(html_content):
    """Clean HTML content to be compatible with Telegram's HTML parser."""
    if not html_content:
        return ""
    
    # Replace common HTML tags with Telegram-compatible ones
    content = html_content
    
    # Replace paragraph tags with line breaks
    content = re.sub(r'<p[^>]*>', '', content)
    content = re.sub(r'</p>', '\n\n', content)
    
    # Replace line breaks
    content = re.sub(r'<br[^>]*/?>', '\n', content)
    
    # Keep basic formatting that Telegram supports
    content = re.sub(r'<strong[^>]*>', '<b>', content)
    content = re.sub(r'</strong>', '</b>', content)
    content = re.sub(r'<em[^>]*>', '<i>', content)
    content = re.sub(r'</em>', '</i>', content)
    
    # Remove other unsupported HTML tags but keep their content
    content = re.sub(r'<[^>]+>', '', content)
    
    # Clean up multiple newlines
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    content = content.strip()
    
    return content

async def send_to_all_channels(bot, message_text, media_attachments=None):
    """Send message to all configured Telegram channels."""
    for channel_id in TELEGRAM_CHANNEL_IDS:
        try:
            if media_attachments:
                # Handle media attachments
                for media in media_attachments:
                    if media['type'] == 'image':
                        await bot.send_photo(chat_id=channel_id, photo=media['url'], caption=message_text, parse_mode='HTML')
                    elif media['type'] == 'video':
                        await bot.send_video(chat_id=channel_id, video=media['url'], caption=message_text, parse_mode='HTML')
                    else: # Send as a text message if media type is not supported for direct sending
                        await bot.send_message(chat_id=channel_id, text=message_text, parse_mode='HTML', disable_web_page_preview=False)
            else:
                # If there's no media, just send the text message
                await bot.send_message(chat_id=channel_id, text=message_text, parse_mode='HTML', disable_web_page_preview=False)
            
            print(f"Sent message to channel {channel_id}")
        except Exception as e:
            print(f"Failed to send message to channel {channel_id}: {e}")

def init_db():
    """Initializes the SQLite database and creates the synced_posts table."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS synced_posts (
            post_id TEXT PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def insert_synced_post_id(post_id):
    """Inserts a synced post ID into the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO synced_posts (post_id) VALUES (?)", (post_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        print(f"Post ID {post_id} already exists in the database.")
    finally:
        conn.close()

def is_post_synced(post_id):
    """Checks if a post ID already exists in the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM synced_posts WHERE post_id = ?", (post_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

async def main(last_synced_post_time=None, run_once=False):
    """Main function to run the bot."""
    print("Starting Mastodon-to-Telegram Bridge...")

    validate_config() # Validate configuration before starting

    init_db() # Initialize the database

    # Initialize APIs (we know these are not None after validation)
    mastodon = Mastodon(
        access_token=MASTODON_ACCESS_TOKEN,  # type: ignore
        api_base_url=MASTODON_INSTANCE_URL
    )
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)  # type: ignore

    # Get the ID of the last post we processed (from DB, if any)
    # For initial run, we might not have a last_post_id, so we fetch all new posts
    # and then only process those not already in DB.
    # After the first run, since_id will be the latest post ID from the DB.
    since_id = None # We will rely on is_post_synced for filtering
    
    # Track the latest post time for GitHub Actions
    latest_post_time = last_synced_post_time

    if last_synced_post_time:
        print(f"Starting bot. Will only sync posts created after: {last_synced_post_time}")
    else:
        print(f"Starting bot. Will check for new posts and filter out already synced ones.")

    while True:
        try:
            print(f"Checking for new posts from user {MASTODON_USER_ID}...")
            
            # Fetch new posts from the user
            # We only want original posts, not boosts/replies
            # We fetch without since_id initially to get all recent posts,
            # then filter using the database.
            new_posts: PaginatableList[Status] = mastodon.account_statuses(
                id=MASTODON_USER_ID,  # type: ignore
                # exclude_reblogs=True,
                # exclude_replies=True,
                limit=20 # Fetch a reasonable number of recent posts
            )

            if new_posts:
                # The API returns posts in reverse chronological order, so we reverse them back
                for post in reversed(new_posts):
                    post_id = post.id
                    post_date = post.created_at
                    print(f"Processing post {post_id} created at {post_date}...")
                    
                    # Check if post was created after the specified time
                    if last_synced_post_time and post_date <= last_synced_post_time:
                        print(f"Post {post_id} was created before the specified time. Skipping.")
                        continue
                    
                    if not is_post_synced(post_id):
                        print(f"Found new post: {post_id}")
                        
                        # Format the message for Telegram
                        # Clean the HTML content to be compatible with Telegram
                        cleaned_content = clean_html_for_telegram(post['content'])
                        
                        # Using HTML for better formatting
                        message_text = f"<b>New Post from {post['account']['display_name']}</b>\n\n"
                        message_text += cleaned_content
                        message_text += f"\n\n<a href='{post.url}'>View on Mastodon</a>"

                        # Send to all channels
                        await send_to_all_channels(bot, message_text, post.media_attachments)

                        # Insert the post ID into the database after successful sending
                        insert_synced_post_id(post_id)
                        print(f"Sent post {post_id} to all Telegram channels and recorded in DB.")
                        
                        # Update the latest post time for GitHub Actions
                        if not latest_post_time or post_date > latest_post_time:
                            latest_post_time = post_date
                    else:
                        print(f"Post {post_id} already synced. Skipping.")

            else:
                print("No new posts found.")

        except Exception as e:
            print(f"An error occurred: {e}")

        # If run_once is True, exit after one iteration
        if run_once:
            # Output the latest post time for GitHub Actions
            if latest_post_time:
                print(f"LAST_SYNCED_POST_TIME={latest_post_time.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"LAST_SYNCED_POST_TIME={last_synced_post_time.strftime('%Y-%m-%d %H:%M:%S') if last_synced_post_time else '2000-01-01 12:00:00'}")
            break

        print(f"Sleeping for {POLLING_INTERVAL} seconds...")
        time.sleep(POLLING_INTERVAL)

if __name__ == '__main__':
    import asyncio
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Mastodon to Telegram Bridge')
    parser.add_argument(
        '--last-synced-post-time',
        type=str,
        help='Only sync posts created after this time (format: YYYY-MM-DD HH:MM:SS)'
    )
    parser.add_argument(
        '--run-once',
        action='store_true',
        help='Run once and exit (useful for GitHub Actions)'
    )
    
    args = parser.parse_args()
    
    # Parse the datetime if provided
    last_synced_post_time = "2000-01-01 12:00:00"  # Default value if not provided
    if args.last_synced_post_time:
        try:
            # Parse the datetime and make it timezone-aware (UTC)
            parsed_time = datetime.strptime(args.last_synced_post_time, '%Y-%m-%d %H:%M:%S')
            last_synced_post_time = parsed_time.replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"Error: Invalid datetime format. Please use YYYY-MM-DD HH:MM:SS")
            exit(1)
    
    asyncio.run(main(last_synced_post_time, args.run_once))