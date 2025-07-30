# 🎧 OpenStats


**OpenStats** is a web app that shows your **Spotify top tracks and artists**, current playback, and lets you control playback — all with ✨ local storage ✨ and a clean UI. Built with Flask + Spotipy.

> "I wanted stats. I made stats. Now you get stats." — *Kurena, CEO of Silly.*

---

## 🚀 Features

- 🎵 View your top tracks & artists
- 📈 Data updates automatically (stored in SQLite)
- 🎛️ Playback controls: Play, pause, skip, volume, seek
- 🧠 Local DB = no server or cloud needed
- 💅 Dashboard UI with track images & links
- 🐍 Easy to run, modify, and fork

---

## 🛠️ Setup Instructions

### 1. Clone it
```bash
git clone https://github.com/yourusername/OpenStats.git
cd OpenStats
```
### 2. Install dependencies
```bash
pip install -r requirements.txt
```

Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app
Set your Redirect URI to:
```
http://127.0.0.1:5001/callback
```
### 4. Add your .env

Create a .env file and fill it in:
```bash
CLIENT_ID=your_spotify_client_id
CLIENT_SECRET=your_spotify_client_secret
SECRET_KEY=your_flask_session_key
```

### 5. Run it
```bash
python openstats.py
```
Then visit:
http://127.0.0.1:5001 in your browser
