from flask import Flask, redirect, session, request, render_template, url_for, jsonify
from spotipy.oauth2 import SpotifyOAuth
import sqlite3
import os
from datetime import datetime
import spotipy
import logging
import requests

app = Flask(__name__)
app.secret_key = os.urandom(24)

def parse_datetime(dt_str):
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        # Try ISO format first
        return datetime.fromisoformat(dt_str)
    except ValueError:
        try:
            # Try SQLite format if ISO fails
            return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            # Try without microseconds
            return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('flaskapp')

# Configuration
DB_PATH = "spotify_stats.db"
CLIENT_ID = ""
CLIENT_SECRET = ""
REDIRECT_URI = ""
SCOPE = "user-top-read user-read-playback-state user-read-currently-playing user-modify-playback-state app-remote-control streaming"

# Initialize database
def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            # Users table
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    access_token TEXT,
                    refresh_token TEXT,
                    token_expires_at TIMESTAMP
                )
            """)
            # Tracks table
            c.execute("""
                CREATE TABLE IF NOT EXISTS top_tracks (
                    user_id TEXT,
                    date TEXT,
                    track_id TEXT,
                    track_name TEXT,
                    artists TEXT,
                    rank INTEGER,
                    time_range TEXT,
                    image_url TEXT,
                    linkto TEXT,
                    release TEXT,
                    PRIMARY KEY (user_id, date, track_id)
                )
            """)
            # Artists table
            c.execute("""
                CREATE TABLE IF NOT EXISTS artist_top (
                    user_id TEXT,
                    date TEXT,
                    artist_name TEXT,
                    rank INTEGER,
                    image_url TEXT,
                    linkto TEXT,
                    PRIMARY KEY (user_id, date, artist_name)
                )
            """)
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")

# Get Spotify client with token refresh
def get_spotify_client():
    if "user_id" not in session:
        return None

    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT access_token, refresh_token, token_expires_at
                FROM users WHERE user_id = ?
            """, (session["user_id"],))
            user_data = c.fetchone()

        if not user_data:
            return None

        access_token, refresh_token, expires_at = user_data

        # Refresh token if expired
        if datetime.now() > parse_datetime(expires_at):
            logger.info("Token expired, refreshing...")
            token_url = "https://accounts.spotify.com/api/token"
            payload = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET
            }
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            response = requests.post(token_url, data=payload, headers=headers)
            token_info = response.json()

            # Debug log the response
            logger.debug(f"Token refresh response: {token_info}")

            if 'access_token' in token_info:
                new_access_token = token_info['access_token']
                new_expires_at = datetime.now().timestamp() + token_info['expires_in']

                # Update the database
                with sqlite3.connect(DB_PATH) as conn:
                    c = conn.cursor()
                    c.execute("""
                        UPDATE users SET
                        access_token = ?,
                        token_expires_at = ?
                        WHERE user_id = ?
                    """, (
                        new_access_token,
                        datetime.fromtimestamp(new_expires_at),
                        session["user_id"]
                    ))
                    conn.commit()

                logger.info("Token refreshed successfully")
                access_token = new_access_token
            else:
                logger.error("Failed to refresh token")
                return None

        return spotipy.Spotify(auth=access_token)
    except Exception as e:
        logger.error(f"Spotify client error: {e}")
        return None

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

    sp_oauth = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        show_dialog=True  # Force user to select account
    )
    auth_url = sp_oauth.get_authorize_url()
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

def save_spotify_data(sp, user_id):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        logger.debug(f"Saving data for user: {user_id} on {today}")

        # Get top tracks and artists
        top_tracks = sp.current_user_top_tracks(limit=40, time_range="short_term")
        top_artists = sp.current_user_top_artists(limit=40, time_range="short_term")

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()

            # Remove old entries forever
            c.execute("DELETE FROM top_tracks WHERE user_id = ?", (user_id,))
            c.execute("DELETE FROM artist_top WHERE user_id = ?", (user_id,))

            # Save tracks
            for rank, track in enumerate(top_tracks["items"], start=1):
                c.execute("""
                    INSERT INTO top_tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    today,
                    track["id"],
                    track["name"] + (" (Explicit)" if track["explicit"] else ""),
                    ", ".join([a["name"] for a in track["artists"]]),
                    rank,
                    "short_term",
                    track["album"]["images"][0]["url"] if track["album"]["images"] else None,
                    track["external_urls"]["spotify"],
                    track["album"]["release_date"]
                ))

            # Save artists
            for rank, artist in enumerate(top_artists["items"], start=1):
                c.execute("""
                    INSERT INTO artist_top VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    today,
                    artist["name"],
                    rank,
                    artist["images"][0]["url"] if artist["images"] else None,
                    artist["external_urls"]["spotify"]
                ))

            conn.commit()
            logger.info(f"Saved {len(top_tracks['items'])} tracks and {len(top_artists['items'])} artists for user {user_id}")
    except Exception as e:
        logger.exception(f"Spotify data save failed: {e}")
        raise

@app.route("/dashboard")
def dashboard():
    sp = get_spotify_client()
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
    sp = get_spotify_client()
    session.clear()
    logger.info("User logged out")
    return redirect("/")

@app.route('/play', methods=['POST'])
def play():
    sp = get_spotify_client()
    sp.start_playback()
    return ('', 204)

@app.route('/pause', methods=['POST'])
def pause():
    sp = get_spotify_client()
    sp.pause_playback()
    return ('', 204)

@app.route('/next', methods=['POST'])
def next_track():
    sp = get_spotify_client()
    sp.next_track()
    return ('', 204)

@app.route('/previous', methods=['POST'])
def prev_track():
    sp = get_spotify_client()
    sp.previous_track()
    return ('', 204)

@app.route('/seek', methods=['POST'])
def seek():
    sp = get_spotify_client()
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
    sp = get_spotify_client()
    # expects JSON { volume_percent: <int 0-100> }
    vol = request.json.get('volume_percent', 50)
    sp.volume(vol)
    return ('', 204)
@app.route('/current', methods=['GET'])
def current():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    sp = get_spotify_client()
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
