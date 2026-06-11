import sqlite3
import threading
import time
import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.db")
db_lock = threading.Lock()

def get_connection():
    # check_same_thread=False allows us to share connections/cursors across threads,
    # but we will serialize writes/reads using our db_lock to prevent conflicts.
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    with db_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS member_stats (
                    guild_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    global_name TEXT,
                    avatar_url TEXT,
                    messages_count INTEGER DEFAULT 0,
                    voice_time INTEGER DEFAULT 0, -- in seconds
                    last_active INTEGER DEFAULT 0, -- unix timestamp
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            conn.commit()
            print("Database initialized successfully.")
        except Exception as e:
            print(f"Error initializing database: {e}")
        finally:
            conn.close()

def update_message_count(guild_id, user_id, username, global_name, avatar_url, increment=1):
    now = int(time.time())
    with db_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO member_stats (guild_id, user_id, username, global_name, avatar_url, messages_count, last_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    username = excluded.username,
                    global_name = excluded.global_name,
                    avatar_url = excluded.avatar_url,
                    messages_count = member_stats.messages_count + excluded.messages_count,
                    last_active = excluded.last_active
            """, (guild_id, user_id, username, global_name, avatar_url, increment, now))
            conn.commit()
        except Exception as e:
            print(f"Error updating message count for user {user_id} in guild {guild_id}: {e}")
        finally:
            conn.close()

def update_voice_time(guild_id, user_id, username, global_name, avatar_url, seconds):
    now = int(time.time())
    with db_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO member_stats (guild_id, user_id, username, global_name, avatar_url, voice_time, last_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    username = excluded.username,
                    global_name = excluded.global_name,
                    avatar_url = excluded.avatar_url,
                    voice_time = member_stats.voice_time + excluded.voice_time,
                    last_active = excluded.last_active
            """, (guild_id, user_id, username, global_name, avatar_url, seconds, now))
            conn.commit()
        except Exception as e:
            print(f"Error updating voice time for user {user_id} in guild {guild_id}: {e}")
        finally:
            conn.close()

def sync_member(guild_id, user_id, username, global_name, avatar_url):
    with db_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO member_stats (guild_id, user_id, username, global_name, avatar_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    username = excluded.username,
                    global_name = excluded.global_name,
                    avatar_url = excluded.avatar_url
            """, (guild_id, user_id, username, global_name, avatar_url))
            conn.commit()
        except Exception as e:
            print(f"Error syncing member {user_id} in guild {guild_id}: {e}")
        finally:
            conn.close()

def get_guild_stats(guild_id):
    with db_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            
            # Fetch server totals
            cursor.execute("""
                SELECT 
                    COUNT(user_id) as total_members,
                    SUM(messages_count) as total_messages,
                    SUM(voice_time) as total_voice_seconds
                FROM member_stats
                WHERE guild_id = ?
            """, (guild_id,))
            row = cursor.fetchone()
            
            total_members = row[0] if row and row[0] is not None else 0
            total_messages = row[1] if row and row[1] is not None else 0
            total_voice_seconds = row[2] if row and row[2] is not None else 0
            
            # Fetch leaderboard
            cursor.execute("""
                SELECT user_id, username, global_name, avatar_url, messages_count, voice_time, last_active
                FROM member_stats
                WHERE guild_id = ?
                ORDER BY (messages_count * 10 + voice_time / 6) DESC, messages_count DESC, voice_time DESC
            """, (guild_id,))
            
            leaderboard = []
            for r in cursor.fetchall():
                leaderboard.append({
                    "userId": str(r[0]),
                    "username": r[1] or f"User_{r[0]}",
                    "globalName": r[2] or r[1] or f"User_{r[0]}",
                    "avatarUrl": r[3] or "",
                    "messagesCount": r[4],
                    "voiceSeconds": r[5],
                    "lastActive": r[6]
                })
                
            return {
                "totalMembers": total_members,
                "totalMessages": total_messages,
                "totalVoiceSeconds": total_voice_seconds,
                "leaderboard": leaderboard
            }
        except Exception as e:
            print(f"Error fetching stats for guild {guild_id}: {e}")
            return {
                "totalMembers": 0,
                "totalMessages": 0,
                "totalVoiceSeconds": 0,
                "leaderboard": []
            }
        finally:
            conn.close()
