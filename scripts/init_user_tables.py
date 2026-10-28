#!/usr/bin/env python3
"""
Initialize user-related database tables.

Run this once to create the User, YouTubeConnection, and UserVideoAnalysis tables.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect
from src.database.connection import get_engine, init_db
from src.database.models import User, YouTubeConnection, UserVideoAnalysis


def main():
    """Create new user tables."""
    engine = get_engine()
    inspector = inspect(engine)
    
    existing_tables = inspector.get_table_names()
    
    new_tables = [
        ('users', User),
        ('youtube_connections', YouTubeConnection),
        ('user_video_analyses', UserVideoAnalysis),
    ]
    
    print("=" * 60)
    print("INITIALIZING USER TABLES")
    print("=" * 60)
    
    for table_name, model in new_tables:
        if table_name in existing_tables:
            print(f"✓ {table_name} already exists")
        else:
            print(f"Creating {table_name}...")
            model.__table__.create(engine)
            print(f"✓ {table_name} created")
    
    print()
    print("=" * 60)
    print("USER TABLES READY")
    print("=" * 60)
    print()
    print("Tables available:")
    for table_name, _ in new_tables:
        print(f"  - {table_name}")
    print()
    print("Next steps:")
    print("  1. Set up Google OAuth credentials")
    print("  2. Run the API: uvicorn src.api.main:app --reload")
    print("  3. Connect YouTube at /auth/youtube")


if __name__ == "__main__":
    main()

