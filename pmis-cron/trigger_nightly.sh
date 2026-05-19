#!/bin/bash
# ── Config ───────────────────────────────────────────────────────
API_URL="http://10.1.131.199:8000/api/v3/YOUR_ENDPOINT_HERE"
AUTH_TOKEN="YOUR_BEARER_TOKEN_HERE"    # leave empty if no auth needed
LOG_FILE="$HOME/pmis-cron/logs/nightly_$(date +%Y%m%d).log"
TIMEOUT=30
# ─────────────────────────────────────────────────────────────────

mkdir -p "$(dirname "$LOG_FILE")"
echo "=============================" >> "$LOG_FILE"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

# Make the API call
if [ -n "$AUTH_TOKEN" ]; then
    RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
        --max-time "$TIMEOUT" \
        -X POST \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        -H "Content-Type: application/json" \
        "$API_URL" 2>&1)
else
    RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
        --max-time "$TIMEOUT" \
        -X POST \
        -H "Content-Type: application/json" \
        "$API_URL" 2>&1)
fi

# Parse response
HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS:")

echo "Status : $HTTP_STATUS" >> "$LOG_FILE"
echo "Response: $BODY"       >> "$LOG_FILE"
echo "Finished: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

# Exit with error if not 2xx
if [[ "$HTTP_STATUS" =~ ^2 ]]; then
    echo "SUCCESS" >> "$LOG_FILE"
    exit 0
else
    echo "FAILED — HTTP $HTTP_STATUS" >> "$LOG_FILE"
    exit 1
fi
