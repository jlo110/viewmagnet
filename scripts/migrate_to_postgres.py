#!/usr/bin/env python3
"""
Migrate data from SQLite to Supabase PostgreSQL.

This script:
1. Connects to the source SQLite database
2. Creates tables in PostgreSQL
3. Migrates all data in batches

Usage:
    python scripts/migrate_to_postgres.py --sqlite-path ./ViewMagnet.db
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.database.models import Base


def migrate_table(source_session, dest_session, table_name: str, model_class, batch_size: int = 1000):
    """Migrate data from one table."""
    print(f"\nMigrating {table_name}...")
    
    try:
        total = source_session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
    except Exception as e:
        print(f"  Table {table_name} doesn't exist in source: {e}")
        return 0
    
    if total == 0:
        print(f"  No data in {table_name}")
        return 0
    
    print(f"  Found {total} rows")
    
    offset = 0
    migrated = 0
    
    while offset < total:
        rows = source_session.execute(
            text(f"SELECT * FROM {table_name} LIMIT {batch_size} OFFSET {offset}")
        ).fetchall()
        
        if not rows:
            break
        
        column_names = rows[0]._fields if rows else []
        
        for row in rows:
            row_dict = dict(zip(column_names, row))
            
            for key, value in row_dict.items():
                if isinstance(value, str) and value.startswith("datetime"):
                    try:
                        row_dict[key] = datetime.fromisoformat(value.replace("datetime.", ""))
                    except:
                        pass
            
            try:
                obj = model_class(**row_dict)
                dest_session.merge(obj)
                migrated += 1
            except Exception as e:
                print(f"  Warning: Failed to migrate row: {e}")
        
        dest_session.commit()
        offset += batch_size
        print(f"  Migrated {min(offset, total)}/{total}")
    
    print(f"  Completed: {migrated} rows migrated")
    return migrated


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument(
        "--sqlite-path",
        default="./ViewMagnet.db",
        help="Path to SQLite database file"
    )
    parser.add_argument(
        "--create-tables-only",
        action="store_true",
        help="Only create tables, don't migrate data"
    )
    args = parser.parse_args()
    
    settings = get_settings()
    
    print("=" * 60)
    print("ViewMagnet Database Migration")
    print("=" * 60)
    print(f"\nTarget: PostgreSQL (Supabase)")
    print(f"Source: {args.sqlite_path}")
    
    print("\nCreating PostgreSQL tables...")
    dest_engine = create_engine(settings.database_url, pool_pre_ping=True)
    Base.metadata.create_all(bind=dest_engine)
    print("Tables created successfully!")
    
    if args.create_tables_only:
        print("\n--create-tables-only specified, skipping data migration")
        return
    
    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        print(f"\nSQLite database not found at {args.sqlite_path}")
        print("No data to migrate. Tables have been created in PostgreSQL.")
        return
    
    print("\nConnecting to databases...")
    source_engine = create_engine(f"sqlite:///{args.sqlite_path}")
    SourceSession = sessionmaker(bind=source_engine)
    DestSession = sessionmaker(bind=dest_engine)
    
    source_session = SourceSession()
    dest_session = DestSession()
    
    from src.database.models import (
        User, YouTubeConnection, UserVideoAnalysis,
        Channel, ChannelSnapshot, DiscoveryProgress,
        Video, APIKeyUsage, VideoFeatures,
        TrackedChannel, TrackedVideo, VideoSnapshot,
        Niche, VideoContentAnalysis
    )
    
    tables = [
        ("users", User),
        ("youtube_connections", YouTubeConnection),
        ("user_video_analyses", UserVideoAnalysis),
        ("channels", Channel),
        ("channel_snapshots", ChannelSnapshot),
        ("discovery_progress", DiscoveryProgress),
        ("videos", Video),
        ("api_key_usage", APIKeyUsage),
        ("video_features", VideoFeatures),
        ("tracked_channels", TrackedChannel),
        ("tracked_videos", TrackedVideo),
        ("video_snapshots", VideoSnapshot),
        ("niches", Niche),
        ("video_content_analysis", VideoContentAnalysis),
    ]
    
    total_migrated = 0
    for table_name, model_class in tables:
        count = migrate_table(source_session, dest_session, table_name, model_class)
        total_migrated += count
    
    source_session.close()
    dest_session.close()
    
    print("\n" + "=" * 60)
    print(f"Migration complete! Total rows migrated: {total_migrated}")
    print("=" * 60)


if __name__ == "__main__":
    main()




