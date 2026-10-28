#!/bin/bash
# Velocity tracker - runs continuously with caffeinate to prevent sleep

cd "$(dirname "$0")/.."
source venv312/bin/activate

echo "🚀 Starting velocity tracker (caffeinate enabled)"
echo "   Press Ctrl+C to stop"
echo ""

while true; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking for new videos..."
    python -m src.cli check-new-videos --max 100 2>/dev/null
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Collecting snapshots..."
    python -m src.cli collect-snapshots --max 500 2>/dev/null
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Sleeping 10 minutes..."
    echo ""
    sleep 600
done

