import sqlite3
from datetime import datetime
import spotipy
import requests
DB_PATH = "spotify_stats.db"
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

# Get Spotify client with token refresh
def get_spotify_client(session):
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
