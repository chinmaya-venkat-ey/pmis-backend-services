#!/bin/bash
# ================================================================
# PMIS — Daily Digest Notification Cron Job
# Triggers: POST /api/v1/notifications/cron/daily-digest
# Runs: Every night at 11:00 PM
# ================================================================

CRON_SECRET="b4fe2096cc229772c0ccf27f298653708c8f36e3811120e5"
API_URL="http://10.1.131.199:8002/api/v1/notifications/cron/daily-digest"
LOG_FILE="$HOME/pmis-cron/logs/daily_digest_$(date +%Y%m%d).log"
TIMEOUT=90

mkdir -p "$(dirname "$LOG_FILE")"

echo "========================================" >> "$LOG_FILE"
echo "Triggered : $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

RESPONSE=$(curl -fsS -w "\nHTTP_STATUS:%{http_code}" \
    --max-time "$TIMEOUT" \
    -X POST \
    -H "X-Cron-Secret: $CRON_SECRET" \
    -H "Content-Type: application/json" \
    -d '{}' \
    "$API_URL" 2>&1)

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS:")

echo "HTTP Status : $HTTP_STATUS"              >> "$LOG_FILE"
echo "Response    : $BODY"                     >> "$LOG_FILE"
echo "Finished    : $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

if [[ "$HTTP_STATUS" =~ ^2 ]]; then
    echo "Result      : SUCCESS "            >> "$LOG_FILE"
    exit 0
else
    echo "Result      : FAILED  (HTTP $HTTP_STATUS)" >> "$LOG_FILE"
    exit 1
fi
