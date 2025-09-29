#!/usr/bin/env python3
"""
Database inspection script for Exomiser web application.
Checks database structure and sample data for individuals and analyses (tasks).

Updated to reflect:
- individual_id column renamed to identity
- tasks table represents analyses in the application
"""
import sqlite3

def check_database():
    """Inspect the database structure and display sample data"""
    conn = sqlite3.connect('instance/app.db')
    cursor = conn.cursor()

    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    print('Tables:', tables)

    # If individuals table exists, show its structure
    if 'individuals' in tables:
        cursor.execute('PRAGMA table_info(individuals)')
        print('\nIndividuals table columns:')
        for row in cursor.fetchall():
            print(f'  {row[1]} ({row[2]})')

    # If tasks table exists, show its structure
    if 'tasks' in tables:
        cursor.execute('PRAGMA table_info(tasks)')
        print('\nTasks table columns (analyses):')
        for row in cursor.fetchall():
            print(f'  {row[1]} ({row[2]})')

    # Check for sample data in individuals table
    if 'individuals' in tables:
        cursor.execute('SELECT COUNT(*) FROM individuals')
        count = cursor.fetchone()[0]
        print(f'\nIndividuals table has {count} records')

        if count > 0:
            cursor.execute('SELECT identity, full_name FROM individuals LIMIT 5')
            print('Sample individuals:')
            for row in cursor.fetchall():
                print(f'  {row[0]} - {row[1]}')

    # Check for sample data in tasks table
    if 'tasks' in tables:
        cursor.execute('SELECT COUNT(*) FROM tasks')
        count = cursor.fetchone()[0]
        print(f'\nTasks table (analyses) has {count} records')

        if count > 0:
            cursor.execute('SELECT name, status FROM tasks LIMIT 5')
            print('Sample analyses:')
            for row in cursor.fetchall():
                print(f'  {row[0]} - {row[1]}')

    conn.close()

def verify_migration():
    """Verify that the individual_id to identity column migration was successful"""
    conn = sqlite3.connect('instance/app.db')
    cursor = conn.cursor()

    try:
        # Check if individuals table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='individuals';")
        if not cursor.fetchone():
            print("❌ Individuals table not found")
            return False

        # Get column information
        cursor.execute('PRAGMA table_info(individuals)')
        columns = [row[1] for row in cursor.fetchall()]

        # Check for the new identity column
        if 'identity' in columns:
            print("✅ 'identity' column found in individuals table")
        else:
            print("❌ 'identity' column not found in individuals table")
            return False

        # Check that old individual_id column is gone
        if 'individual_id' not in columns:
            print("✅ Old 'individual_id' column successfully removed")
        else:
            print("⚠️  Warning: Old 'individual_id' column still exists")

        # Check for data in identity column
        cursor.execute('SELECT COUNT(*) FROM individuals WHERE identity IS NOT NULL AND identity != ""')
        identity_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM individuals')
        total_count = cursor.fetchone()[0]

        if identity_count == total_count and total_count > 0:
            print(f"✅ All {total_count} individuals have valid identity values")
        elif total_count == 0:
            print("ℹ️  No individuals in database (empty table)")
        else:
            print(f"❌ {total_count - identity_count} individuals missing identity values")
            return False

        print("✅ Migration verification successful!")
        return True

    except Exception as e:
        print(f"❌ Error during verification: {str(e)}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("=== Database Structure Check ===")
    check_database()

    print("\n=== Migration Verification ===")
    verify_migration()
