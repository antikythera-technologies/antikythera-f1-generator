"""Update YouTube video metadata and set to public."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.youtube_uploader import YouTubeUploader

VIDEO_ID = "J19A90QZ-2Q"

TITLE = "Melbourne Mayhem: When Mercedes Remembered How to Race | F1 2026 Round 1"

DESCRIPTION = """The 2026 Formula 1 season kicks off at Albert Park with an absolute shocker! Mercedes are back, Antonelli is on fire, and the paddock has completely lost it.

Satirical AI-generated F1 commentary covering the 2026 Australian Grand Prix. Every driver, every team, every dramatic moment — reimagined in caricature.

🏁 RACE HIGHLIGHTS:
• Kimi Antonelli stuns the grid at Albert Park
• Mercedes stage a dramatic comeback
• Verstappen and Red Bull face new challengers
• Rookie drama with Bortoleto scoring debut points
• Team principals lose their minds on the pit wall

🏆 2026 F1 Season | Round 1 — Australian Grand Prix
📍 Albert Park Circuit, Melbourne
📅 Season 2026

────────────────────────────────────────

⚠️ DISCLAIMER: This video is entirely AI-generated satire — all characters, voices, and commentary are fictional parodies created by AI. No real people were harmed in the making of this chaos.

Built with ❤️ by Antikythera Technologies
🌐 https://antikythera.co.za

#F1 #Formula1 #AustralianGP #AlbertPark #Melbourne #Racing #Motorsport #F12026 #Satire #AIGenerated #Comedy #Mercedes #RedBull #Ferrari #McLaren"""

TAGS = [
    "F1", "Formula 1", "Formula One", "Australian Grand Prix", "Albert Park",
    "Melbourne", "2026 F1", "F1 2026", "racing", "motorsport",
    "satire", "comedy", "AI generated", "caricature",
    "Mercedes", "Red Bull", "Ferrari", "McLaren", "Aston Martin",
    "Max Verstappen", "Lewis Hamilton", "Kimi Antonelli", "Lando Norris",
    "F1 highlights", "race recap", "post race", "F1 commentary",
    "Antikythera", "AI video", "animated F1",
]

uploader = YouTubeUploader()
yt = uploader.youtube

body = {
    "id": VIDEO_ID,
    "snippet": {
        "title": TITLE,
        "description": DESCRIPTION,
        "tags": TAGS,
        "categoryId": "17",
    },
    "status": {
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": False,
        "embeddable": True,
    },
}

response = yt.videos().update(
    part="snippet,status",
    body=body,
).execute()

vid = response["id"]
privacy = response["status"]["privacyStatus"]
print(f"Updated! https://www.youtube.com/watch?v={vid}")
print(f"Privacy: {privacy}")
print(f"Title: {response['snippet']['title']}")
