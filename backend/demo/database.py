"""Find a user in the demo database."""
import sqlite3


def find_user(connection: sqlite3.Connection, name: str):
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users WHERE name = ?", (name,))
    return cursor.fetchone()
