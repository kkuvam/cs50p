#!/bin/bash

# Monitor Exomiser Analysis Memory Usage
# Usage: ./monitor_analysis.sh [analysis_id]

ANALYSIS_ID=${1:-""}
CONTAINER_NAME="exomiser-ui"

echo "=== Exomiser Analysis Memory Monitor ==="
echo "Container: $CONTAINER_NAME"
if [ ! -z "$ANALYSIS_ID" ]; then
    echo "Analysis ID: $ANALYSIS_ID"
fi
echo "Started at: $(date)"
echo "========================================="

# Function to get container stats
get_stats() {
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" $CONTAINER_NAME 2>/dev/null
}

# Function to check analysis status
check_analysis() {
    if [ ! -z "$ANALYSIS_ID" ]; then
        curl -s "http://localhost:8000/analysis/$ANALYSIS_ID/status" | grep -o '"status":"[^"]*"' | cut -d'"' -f4
    fi
}

# Monitor loop
while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    STATS=$(get_stats)

    if [ ! -z "$STATS" ]; then
        echo "[$TIMESTAMP] $STATS"

        # Check if analysis is complete
        if [ ! -z "$ANALYSIS_ID" ]; then
            STATUS=$(check_analysis)
            if [ "$STATUS" = "COMPLETED" ] || [ "$STATUS" = "FAILED" ]; then
                echo "[$TIMESTAMP] Analysis $STATUS - stopping monitor"
                break
            fi
        fi
    else
        echo "[$TIMESTAMP] Container not running"
        break
    fi

    sleep 5
done

echo "========================================="
echo "Monitoring completed at: $(date)"
