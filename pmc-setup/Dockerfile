# PMC project setup — self-contained image.
# Builds the "Project Management Consultants (PMC)" project end-to-end via the
# PMIS REST APIs: creates the project + 11 milestones + activities (D9 = 4
# quarterly + D10 = 20 quarterly resource activities, D1-D3 marked completed),
# cost items, payment terms; replicates team owners/approvers from a source
# project; and OPTIONALLY overrides the D9/D10 resource cost values to the
# resource-alignment sheet.
#
#   docker build -t pmis-pmc-setup .
#
#   # create on the remote server (default), server-computed costs:
#   docker run --rm pmis-pmc-setup --name "Project Management Consultants (PMC) - copy 2"
#
#   # create AND override the D9/D10 costs to the sheet (needs DB access):
#   docker run --rm -e COST_OVERRIDE=true \
#     pmis-pmc-setup --name "Project Management Consultants (PMC) - copy 3"
#
# Parameters (all env vars; flags after the image name pass to setup-pmc.sh):
#   COST_OVERRIDE   false (default) = use the server/API-computed resource costs;
#                   true = overwrite D9/D10 resource costs to the sheet values.
#   TEAM_SOURCE_PID source project to copy owners/approvers from
#                   (default = PMC-copy acabf366-...); "none" to skip.
#   PMIS_ENV        remote (default) | local ; plus PMIS_PROJECT_NAME,
#                   PMIS_USER_BASE / PMIS_PROJ_BASE, PMIS_LOGIN_USER/PASS, PMIS_OTP.
#   DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME  (only used when COST_OVERRIDE=true;
#                   default to the remote Postgres).
#
# NOTE: the container must reach the PMIS server (and, for COST_OVERRIDE, its
# Postgres) — both sit on the EY VPN. On Linux use `--network host`; on Docker
# Desktop ensure the VPN route is shared with the Docker VM.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl bash ca-certificates postgresql-client \
 && rm -rf /var/lib/apt/lists/*

# openpyxl not needed at run time (the rate xlsx is prebuilt + bundled).
WORKDIR /app
COPY setup-pmc.sh docker-entrypoint.sh replicate-teams.py gen-ratefix-sql.py \
     pmc-fixture.json pmc-designation-rates.xlsx d9-d10-rate-fix.json ./
RUN chmod +x setup-pmc.sh docker-entrypoint.sh replicate-teams.py

# defaults: real server, non-interactive, no cost override, teams from PMC-copy.
ENV PMIS_ENV=remote \
    COST_OVERRIDE=false \
    TEAM_SOURCE_PID=acabf366-6a30-485d-80de-bb90e4cf9f1d
ENTRYPOINT ["bash", "/app/docker-entrypoint.sh"]
CMD []
