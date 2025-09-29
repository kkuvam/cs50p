#!/usr/bin/env python3
import sqlite3

def check_database():
    conn = sqlite3.connect('instance/app.db')
    cursor = conn.cursor()

    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    print('Tables:', tables)

    # If individuals table exists, show its structure
    if 'individuals' in tables:
        cursor.execute('PRAGMA table_info(individuals)')
        print('\nindividuals table columns:')
        for row in cursor.fetchall():
            print(f'  {row[1]} ({row[2]})')

    # If tasks table exists, show its structure
    if 'tasks' in tables:
        cursor.execute('PRAGMA table_info(tasks)')
        print('\nTasks table columns:')
        for row in cursor.fetchall():
            print(f'  {row[1]} ({row[2]})')

    conn.close()

if __name__ == "__main__":
    check_database()
