from flask import Flask, redirect, session, request, render_template, url_for, jsonify
from spotipy.oauth2 import SpotifyOAuth
import os
from datetime import datetime
import spotipy
import logging
import requests
from dotenv import load_dotenv
from helpers import init_db, save_spotify_data, parse_datetime, get_spotify_client
from urllib.parse import urlencode
import sqlite3


load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)



# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('flaskapp')

# Configuration
DB_PATH = "spotify_stats.db"
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:5001/callback"
SCOPE = "user-top-read user-read-playback-state user-read-currently-playing user-modify-playback-state app-remote-control streaming"


# Routes
@app.route("/")
def index():
    session.clear()
    logger.debug("Session cleared on index route")
    return render_template("login.html")

@app.route("/login")
def login():
    session.clear()
    logger.debug("Session cleared on login route")
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": "http://127.0.0.1:5001/callback",
        "scope": SCOPE,
        "show_dialog": "true"
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urlencode(params)
    return redirect(auth_url)

sp = None

@app.route('/<path:path>')
def static_file(path):
    return app.send_static_file(path)
@app.route("/callback")
def callback():
    try:
        logger.debug("Session cleared at callback start")

        # Verify we have a code parameter
        code = request.args.get('code')
        if not code:
            logger.error("Missing code parameter in callback")
            return redirect(url_for('index'))

        logger.debug(f"Received authorization code: {code}")

        # Get tokens using authorization code
        token_url = "https://accounts.spotify.com/api/token"
        payload = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(token_url, data=payload, headers=headers)
        token_info = response.json()

        # Debug log the response
        logger.debug(f"Token response: {token_info}")

        # Check for errors
        if 'access_token' not in token_info:
            logger.error(f"Failed to get access token: {token_info}")
            return redirect(url_for('index'))

        # Get user info directly from Spotify API
        headers = {'Authorization': f'Bearer {token_info["access_token"]}'}
        user_response = requests.get('https://api.spotify.com/v1/me', headers=headers)
        user_data = user_response.json()

        # Debug log user data
        logger.debug(f"User data from Spotify: {user_data}")

        if 'id' not in user_data:
            logger.error("Failed to get user ID from Spotify")
            return redirect(url_for('index'))

        user_id = user_data['id']
        display_name = user_data.get('display_name', 'Unknown User')

        logger.info(f"New user login: {user_id} - {display_name}")

        # Store user data
        try:
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?)
                """, (
                    user_id,
                    display_name,
                    token_info["access_token"],
                    token_info["refresh_token"],
                    datetime.fromtimestamp(datetime.now().timestamp() + token_info["expires_in"])
                ))
                conn.commit()
                logger.info(f"Saved user to DB: {user_id}")
        except sqlite3.Error as e:
            logger.error(f"User save error: {e}")

        # Set NEW session
        session["user_id"] = user_id
        session["display_name"] = display_name
        logger.info(f"Session set for user: {user_id}")


        # Save Spotify data
        try:
            sp = spotipy.Spotify(auth=token_info["access_token"])
            save_spotify_data(sp, user_id)
        except Exception as e:
            logger.error(f"Data save error: {e}")

        return redirect(url_for("dashboard"))
    except Exception as e:
        logger.exception(f"Callback error: {e}")
        return redirect(url_for("index"))
@app.route("/dashboard")
def dashboard():
    sp = get_spotify_client(session)
    if "user_id" not in session:
        logger.warning("Dashboard accessed without user session")
        return redirect("/login")

    user_id = session["user_id"]
    logger.info(f"Dashboard for user: {user_id}")
    try:

        if not sp:
            return redirect("/login")

        current_playback = sp.current_playback()
        current_track = None
        if current_playback and current_playback.get("item"):
            item = current_playback["item"]
            current_track = {
                "name": item["name"] + (" (Explicit)" if item["explicit"] else ""),
                "artist": ", ".join([a["name"] for a in item["artists"]]),
                "image_url": item["album"]["images"][0]["url"] if item["album"]["images"] else "",
                "link": item["external_urls"]["spotify"]
            }
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()

            # Verify user exists
            c.execute("SELECT display_name FROM users WHERE user_id = ?", (user_id,))
            user = c.fetchone()
            if not user:
                logger.error(f"User {user_id} not found in database")
                return redirect("/login")

            # Get tracks - ensure we're using session user_id
            c.execute("""
                SELECT track_name, artists, rank, date, image_url, linkto, release
                FROM top_tracks
                WHERE user_id = ?
                ORDER BY date DESC, rank ASC
                LIMIT 40
            """, (user_id,))
            tracks = c.fetchall()
            c.execute("""
                SELECT artist_name, rank, date, image_url, linkto
                FROM artist_top
                WHERE user_id = ?
                ORDER BY date DESC, rank ASC
                LIMIT 40
            """, (user_id,))
            artists = c.fetchall()
        return render_template("dashboard.html",
                             tracks=tracks,
                             artists=artists,
                             user=user[0], current_track=current_track)
    except Exception as e:
        logger.exception(f"Dashboard error: {e}")
        return "Error loading dashboard", 500

@app.route("/other")
def dashboardother():
    if "user_id" not in session:
        logger.warning("Dashboard accessed without user session")
        return redirect("/login")

    user_id = session["user_id"]
    logger.info(f"Dashboard for user: {user_id}")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()

            # Verify user exists
            c.execute("SELECT display_name FROM users WHERE user_id = ?", (user_id,))
            user = c.fetchone()
            if not user:
                logger.error(f"User {user_id} not found in database")
                return redirect("/login")

            # Get tracks - ensure we're using session user_id
            c.execute("""
                SELECT artist_name, rank, date, image_url, linkto
                FROM artist_top
                WHERE user_id = ?
                ORDER BY date DESC, rank ASC
                LIMIT 40
            """, (user_id,))
            tracks = c.fetchall()

        return render_template("other.html",
                             tracks=tracks,
                             user=user[0])
    except Exception as e:
        logger.exception(f"Dashboard error: {e}")
        return "Error loading dashboard", 500

@app.route("/logout")
def logout():
    sp = get_spotify_client(session)
    session.clear()
    logger.info("User logged out")
    return redirect("/")

@app.route('/play', methods=['POST'])
def play():
    sp = get_spotify_client(session)
    sp.start_playback()
    return ('', 204)

@app.route('/pause', methods=['POST'])
def pause():
    sp = get_spotify_client(session)
    sp.pause_playback()
    return ('', 204)

@app.route('/next', methods=['POST'])
def next_track():
    sp = get_spotify_client(session)
    sp.next_track()
    return ('', 204)

@app.route('/previous', methods=['POST'])
def prev_track():
    sp = get_spotify_client(session)
    sp.previous_track()
    return ('', 204)

@app.route('/seek', methods=['POST'])
def seek():
    sp = get_spotify_client(session)
    current_playback = sp.current_playback()

    if not current_playback or not current_playback['is_playing']:
        return ('No active playback', 404)

    track_duration = current_playback['item']['duration_ms']

    # Check if percentage is provided (0-100)
    if 'percentage' in request.json:
        percentage = float(request.json['percentage'])
        # Ensure percentage is between 0 and 100
        percentage = max(0, min(100, percentage))
        pos = int(track_duration * (percentage / 100))
    else:
        # Fall back to direct position in ms if percentage not provided
        pos = request.json.get('position_ms', 0)

    sp.seek_track(pos)
    return ('', 204)
@app.route('/volume', methods=['POST'])
def volume():
    sp = get_spotify_client(session)
    # expects JSON { volume_percent: <int 0-100> }
    vol = request.json.get('volume_percent', 50)
    sp.volume(vol)
    return ('', 204)
@app.route('/current', methods=['GET'])
def current():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    sp = get_spotify_client(session)
    if not sp:
        return jsonify({"error": "Spotify client unavailable"}), 401

    try:
        playback = sp.current_playback()
        if not playback or "item" not in playback:
            return jsonify({"error": "Nothing playing"}), 404

        item = playback['item']
        mikudayoo = playback['progress_ms'] / item['duration_ms'] * 100

        return jsonify({
            'is_playing': playback['is_playing'],
            'progress_ms': playback['progress_ms'],
            'duration_ms': item['duration_ms'],
            'percentage': mikudayoo,
            'vol': playback["device"]["volume_percent"],
            'item': {
                'name': item['name'],
                'artists': [a['name'] for a in item['artists']],
                'album_art': item['album']['images'][0]['url'],
                'external_url': item['external_urls']['spotify']
            }
        })
    except Exception as e:
        logger.exception("Error in /current")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5001)  # Use a specific port
