# ===== Configuration =====
import pytz

# --- Telegram Bot ---
BOT_TOKEN = "8293725078:AAG_fRkeDIfXGqudEENiD6wuN_xB87JbqHA"

# --- Google Sheet ---
GOOGLE_CREDENTIALS_FILE = "credentials.json"   # Service account key file
SHEET_ID = "10TpLVJrWP60btW5plk6m7iMCXqZi9ZHLeV9z7QoqAL8"                # From Sheet URL
SHEET_NAME = "Sheet1"                          # The tab name inside the Sheet
ADMIN_ID = 1831664678   # 👈 replace with your own Telegram numeric user ID
UPI_ID = "vinod.uptt@okaxis"  # 👈 your real UPI ID

# --- Date Handling ---
DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d %b %Y"]  # Accepted input formats
OUTPUT_DATE_FORMAT = "%d/%m/%Y"  # Consistent Indian format in output

# --- Job Sending Behavior ---
RESEND_ALL_ON_NEW = True  # If True, send full active list on any new job; else only send newly added

# --- Filenames for persistence ---
SENT_JOBS_FILE = "sent_jobs.json"
SUBSCRIBERS_FILE = "subscribers.json"

# --- Timezone ---
TIMEZONE = pytz.timezone("Asia/Kolkata")

CHECK_INTERVAL_MINUTES = 60  # how often to check jobs (in minutes)

# --- Sources ---
# Toggle per-source. If RSS is available, mention it here, else "scraper"
SOURCES = {
    "UPSC": {"enabled": True, "method": "scraper", "url": "https://www.upsc.gov.in/whats-new" },
    "SSC": {"enabled": True, "method": "rss",     "url": "https://ssc.nic.in/rss/JobsRss" },
    "ISRO": {"enabled": True, "method": "scraper", "url": "https://www.isro.gov.in/Careers.html" },
    "DRDO": {"enabled": True, "method": "scraper", "url": "https://www.drdo.gov.in/careers" },
    "UPPSC": {"enabled": True, "method": "scraper", "url": "https://uppsc.up.nic.in/Notifications.aspx" },
}

# --- Keywords (Optional filtering) ---
# Leave empty list [] to allow all jobs
KEYWORDS = [
    # Examples:
    # "Engineer",
    # "Scientist",
    # "Clerk",
    # "UPSC Civil Services",
]

# --- Default substitution text for missing info ---
DEFAULT_SUBSTITUTION = "Refer official ad"
