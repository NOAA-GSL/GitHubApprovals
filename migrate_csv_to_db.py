#!/usr/bin/env python3
"""Database migration script to add Information Owner tracking columns.

This script:
1. Adds new columns to user_agreements table (github_username, information_owner, etc.)
2. Migrates data from informationowners.csv into the database
3. Creates minimal UserAgreement records for CSV-only users
4. Is idempotent - safe to run multiple times

Usage:
    python migrate_csv_to_db.py [--dry-run]
"""

import os
import sys
import csv
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

def get_database_path():
    """Determine database path (production vs development)."""
    if os.path.exists("/data/agreement.db"):
        return "/data/agreement.db"
    elif os.path.exists("data/agreement.db"):
        return "data/agreement.db"
    else:
        return "agreement.db"

def get_csv_path():
    """Determine CSV path (production vs development)."""
    if os.path.exists("/data/informationowners.csv"):
        return "/data/informationowners.csv"
    elif os.path.exists("informationowners.csv"):
        return "informationowners.csv"
    elif os.path.exists("data/informationowners.csv"):
        return "data/informationowners.csv"
    else:
        raise FileNotFoundError("Could not find informationowners.csv")

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def add_columns_if_missing(conn, dry_run=False):
    """Add new columns to user_agreements table if they don't exist."""
    cursor = conn.cursor()
    
    columns_to_add = [
        ("github_username", "TEXT"),
        ("information_owner", "INTEGER DEFAULT 0"),
        ("welcome_email_sent", "INTEGER DEFAULT 0"),
        ("info_owner_date_added", "TEXT"),
    ]
    
    for column_name, column_type in columns_to_add:
        if not column_exists(cursor, "user_agreements", column_name):
            sql = f"ALTER TABLE user_agreements ADD COLUMN {column_name} {column_type}"
            print(f"  Adding column: {column_name} ({column_type})")
            if not dry_run:
                cursor.execute(sql)
                conn.commit()
            else:
                print(f"  [DRY RUN] Would execute: {sql}")
        else:
            print(f"  Column already exists: {column_name}")
    
    return True

def load_csv_data(csv_path, mark_welcomed=True):
    """Load Information Owners from CSV file.
    
    Args:
        csv_path: Path to informationowners.csv
        mark_welcomed: If True, mark all existing CSV users as already welcomed (default: True)
                      This prevents duplicate welcome emails to existing Information Owners.
    """
    info_owners = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                username = row.get('username', '').strip()
                email = row.get('email', '').strip()
                date_added = row.get('date_added', '').strip()
                
                # Check if CSV has welcome_sent column (for backward compatibility)
                # If not present, use mark_welcomed parameter
                if 'welcome_sent' in row:
                    welcome_sent = row.get('welcome_sent', '').strip().lower() == 'yes'
                else:
                    # CSV doesn't have welcome_sent column - use default
                    welcome_sent = mark_welcomed
                
                if username:  # Only include rows with username
                    info_owners.append({
                        'username': username,
                        'email': email if email else None,
                        'date_added': date_added if date_added else None,
                        'welcome_sent': welcome_sent
                    })
        
        welcomed_count = sum(1 for owner in info_owners if owner['welcome_sent'])
        print(f"  Loaded {len(info_owners)} Information Owners from CSV")
        print(f"  - {welcomed_count} marked as 'already welcomed' (won't receive welcome emails)")
        print(f"  - {len(info_owners) - welcomed_count} marked as 'not welcomed' (will receive welcome emails)")
        return info_owners
    except FileNotFoundError:
        print(f"  ERROR: CSV file not found at {csv_path}")
        return []
    except Exception as e:
        print(f"  ERROR loading CSV: {e}")
        return []

def migrate_csv_to_database(conn, info_owners, dry_run=False):
    """Migrate CSV data to database."""
    cursor = conn.cursor()
    
    updated_count = 0
    created_count = 0
    skipped_count = 0
    
    for owner in info_owners:
        username = owner['username']
        email = owner['email']
        date_added = owner['date_added']
        welcome_sent = owner['welcome_sent']
        
        # Check if user exists by email (if email is provided)
        user_exists = False
        if email:
            cursor.execute("SELECT id, email FROM user_agreements WHERE email = ?", (email,))
            existing_user = cursor.fetchone()
            if existing_user:
                user_exists = True
                # Update existing user
                sql = """UPDATE user_agreements 
                         SET github_username = ?, 
                             information_owner = 1, 
                             welcome_email_sent = ?,
                             info_owner_date_added = ?
                         WHERE email = ?"""
                
                date_str = date_added if date_added else datetime.now().strftime("%Y-%m-%d")
                
                if not dry_run:
                    cursor.execute(sql, (username, 1 if welcome_sent else 0, date_str, email))
                    conn.commit()
                    print(f"  ✓ Updated: {email} → {username}")
                else:
                    print(f"  [DRY RUN] Would update: {email} → {username}")
                updated_count += 1
        
        # If user doesn't exist and they have an email, create minimal record
        if not user_exists and email:
            sql = """INSERT INTO user_agreements 
                     (email, first_name, last_name, github_username, esrl_lab, role, 
                      agreed, sponsor, information_owner, welcome_email_sent, 
                      info_owner_date_added, timestamp)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            
            date_str = date_added if date_added else datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().isoformat()
            
            if not dry_run:
                try:
                    cursor.execute(sql, (
                        email,
                        "",  # first_name (minimal record)
                        "",  # last_name (minimal record)
                        username,
                        "Unknown",  # esrl_lab
                        "Information Owner",  # role
                        False,  # agreed
                        "N/A",  # sponsor
                        True,  # information_owner
                        welcome_sent,  # welcome_email_sent
                        date_str,  # info_owner_date_added
                        timestamp
                    ))
                    conn.commit()
                    print(f"  + Created: {email} → {username}")
                    created_count += 1
                except sqlite3.IntegrityError as e:
                    print(f"  ! Skipped (duplicate): {email} - {e}")
                    skipped_count += 1
            else:
                print(f"  [DRY RUN] Would create: {email} → {username}")
                created_count += 1
        
        # If no email provided, skip (can't create or update without email)
        if not email:
            print(f"  ⚠ Skipped (no email): {username}")
            skipped_count += 1
    
    return updated_count, created_count, skipped_count

def main():
    parser = argparse.ArgumentParser(description="Migrate Information Owner data from CSV to database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--mark-existing-welcomed", action="store_true", default=True, 
                       help="Mark all existing CSV users as already welcomed (prevents duplicate emails). Default: True")
    parser.add_argument("--no-mark-existing-welcomed", dest="mark_existing_welcomed", action="store_false", 
                       help="Do NOT mark existing CSV users as welcomed (will send welcome emails after migration)")
    args = parser.parse_args()
    
    print("="*80)
    print("Database Migration: Information Owner Tracking")
    print("="*80)
    
    # Get paths
    db_path = get_database_path()
    print(f"\n📁 Database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"❌ ERROR: Database not found at {db_path}")
        print("   Please ensure the database exists before running migration.")
        return 1
    
    try:
        csv_path = get_csv_path()
        print(f"📁 CSV File: {csv_path}")
    except FileNotFoundError as e:
        print(f"❌ ERROR: {e}")
        return 1
    
    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made\n")
    
    # Display welcome email policy
    if args.mark_existing_welcomed:
        print("✉️  WELCOME EMAIL POLICY: Existing CSV users will be marked as 'already welcomed'")
        print("   This prevents sending duplicate welcome emails to your existing Information Owners.")
    else:
        print("⚠️  WARNING: Existing CSV users will be marked as 'not welcomed'")
        print("   Welcome emails WILL be sent to all users with email addresses after migration!")
    print()
    
    # Connect to database
    print(f"\n🔌 Connecting to database...")
    conn = sqlite3.connect(db_path)
    
    try:
        # Step 1: Add columns
        print(f"\n📋 Step 1: Adding new columns to user_agreements table...")
        add_columns_if_missing(conn, dry_run=args.dry_run)
        
        # Step 2: Load CSV
        print(f"\n📋 Step 2: Loading CSV data...")
        info_owners = load_csv_data(csv_path, mark_welcomed=args.mark_existing_welcomed)
        
        if not info_owners:
            print("  No data to migrate!")
            return 1
        
        # Step 3: Migrate data
        print(f"\n📋 Step 3: Migrating data to database...")
        updated, created, skipped = migrate_csv_to_database(conn, info_owners, dry_run=args.dry_run)
        
        # Summary
        print("\n" + "="*80)
        print("Migration Summary")
        print("="*80)
        print(f"  Records updated:  {updated}")
        print(f"  Records created:  {created}")
        print(f"  Records skipped:  {skipped}")
        print(f"  Total processed:  {len(info_owners)}")
        
        if args.dry_run:
            print("\n✓ Dry run complete - no changes made")
        else:
            print("\n✓ Migration complete!")
            print(f"\n💡 Next steps:")
            print(f"   1. Verify data at: https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/browse_agreements")
            print(f"   2. Update dependabotalerts.py to query database instead of CSV")
            print(f"   3. Test dependabotalerts.py runs without errors")
            print(f"   4. Backup and archive informationowners.csv")
    
    finally:
        conn.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
