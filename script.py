import os
import re
import requests
import cloudinary
import cloudinary.uploader
import time
import tempfile

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ==========================================
# GOOGLE DRIVE AUTH
# ==========================================

SCOPES = ["https://www.googleapis.com/auth/drive"]
# TOKEN_FILE = "token.json"
# CREDENTIALS_FILE = "credentials.json"
DRIVE_FOLDER_ID = "1SkQgsJRR9G3lRYQlFzyR3wXz8gyjg4l3"

def get_drive_service():
    creds = Credentials.from_authorized_user_info(
        eval(os.environ["GOOGLE_TOKEN"]),
        SCOPES
    )

    return build("drive", "v3", credentials=creds)


drive_service = get_drive_service()

# ==========================================
# CLOUDINARY CONFIG
# ==========================================

cloudinary.config(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"]
)
# ==========================================
# INSTAGRAM CONFIG
# ==========================================

ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
INSTAGRAM_ID = os.environ["IG_ID"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]

# ==========================================
# SORTING KEY
# ==========================================

def sort_key(filename):
    match = re.match(r"(\d+)\s*\((\d+)\)_clip(\d+)", filename)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return (999, 999, 999)

# ==========================================
# STEP 1: LIST ALL FILES WITH PAGINATION
# ==========================================

print("Fetching video list from Google Drive...")

# No MIME filter — fetch all files, filter by name ending in .mp4
query = f"'{DRIVE_FOLDER_ID}' in parents and trashed=false"

all_files = []
page_token = None

while True:
    params = {
        "q": query,
        "fields": "nextPageToken, files(id, name, mimeType)",
        "pageSize": 1000
    }
    if page_token:
        params["pageToken"] = page_token

    results = drive_service.files().list(**params).execute()
    all_files.extend(results.get("files", []))

    page_token = results.get("nextPageToken")
    if not page_token:
        break

# Filter to only .mp4 named files (regardless of MIME type)
files = [f for f in all_files if f["name"].lower().endswith(".mp4")]

if not files:
    print("No .mp4 files found.")
    exit()

# Sort correctly
files_sorted = sorted(files, key=lambda f: sort_key(f["name"]))

print(f"Found {len(files_sorted)} video(s) in queue.")

target    = files_sorted[0]
file_id   = target["id"]
file_name = target["name"]

print(f"\nProcessing: {file_name}")

# ==========================================
# STEP 2: DOWNLOAD FROM DRIVE
# ==========================================

print("Downloading from Drive...")

request = drive_service.files().get_media(fileId=file_id)

with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
    tmp_path = tmp.name
    downloader = MediaIoBaseDownload(tmp, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"  Download progress: {int(status.progress() * 100)}%")

print(f"Downloaded to: {tmp_path}")

# ==========================================
# STEP 3: UPLOAD TO CLOUDINARY
# ==========================================

print("\nUploading to Cloudinary...")

upload_result = cloudinary.uploader.upload_large(
    tmp_path,
    resource_type="video"
)

video_url = upload_result["secure_url"]
print(f"Cloudinary URL:\n{video_url}")

os.remove(tmp_path)

# ==========================================
# STEP 4: CREATE INSTAGRAM REEL CONTAINER
# ==========================================

print("\nCreating Instagram Reel container...")

payload = {
    "media_type": "REELS",
    "video_url": video_url,
    "caption": """What starts as justice slowly turns into obsession… and that’s what makes Death Note one of the greatest psychological thriller anime of all time.

The battle between Light Yagami and L isn’t just about intelligence — it’s a war of ideology, ego, manipulation, and power. Every episode keeps raising the tension, every move feels like a chess match, and every scene reminds us why Death Note became a legendary anime worldwide.

This scene perfectly captures the dark atmosphere, genius writing, intense mind games, and iconic character development that made Death Note a masterpiece for anime fans.

🔥 Follow for more anime edits, viral anime moments, and legendary scenes.

#DeathNote #DeathNoteEdit #LightYagami #LLawliet #Kira #Ryuk #Anime #AnimeEdit #AnimeReels #AnimeScene #PsychologicalAnime #ThrillerAnime #AnimeFans #Otaku #Weeb #Manga #AnimeLover #AnimeCommunity #AnimeClips #AnimeMoments #JapaneseAnime #DarkAnime #MindGames #AnimeTrending #ViralAnime #AnimeAesthetic #AnimeShorts #AnimeVideo #AnimeContent #AnimeWorld""",
    "access_token": ACCESS_TOKEN
}

response = requests.post(
    f"https://graph.facebook.com/v20.0/{INSTAGRAM_ID}/media",
    data=payload
)
result = response.json()
print("Container Response:", result)

creation_id = result.get("id")
if not creation_id:
    print("Failed to create reel container. Aborting.")
    exit()

# ==========================================
# STEP 5: WAIT FOR INSTAGRAM PROCESSING
# ==========================================

print("\nWaiting 30s for Instagram to process the video...")
time.sleep(30)

# ==========================================
# STEP 6: PUBLISH REEL
# ==========================================

publish_response = requests.post(
    f"https://graph.facebook.com/v20.0/{INSTAGRAM_ID}/media_publish",
    data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}
)
publish_result = publish_response.json()
print("\nPublish Response:", publish_result)

# ==========================================
# STEP 7: TRASH ON DRIVE (only if published)
# ==========================================

if publish_result.get("id"):
    print(f"\n✅ Reel published! ID: {publish_result['id']}")

    # Trash on Drive
    drive_service.files().update(
        fileId=file_id,
        body={"trashed": True}
    ).execute()

    print(f"🗑️  '{file_name}' moved to Drive trash.")

    # Delete from Cloudinary
    public_id = upload_result.get("public_id")

    if public_id:
        cloudinary.uploader.destroy(
            public_id,
            resource_type="video"
        )

        print(f"☁️  Deleted '{public_id}' from Cloudinary.")

else:
    print("\n❌ Publish failed. File NOT trashed or deleted.")