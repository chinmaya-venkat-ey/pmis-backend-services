-- PMIS Refactor — Cutover rollback (USE ONLY during the maintenance window
-- if the post-cutover smoke test fails).
--
-- Public.* tables are UNTOUCHED during the cutover sequence (01_copy_data
-- only reads from them); dropping the new schemas is sufficient to revert.
--
-- Operator runs (out of band) before this:
--   docker compose -f PMIS-refactor/docker-compose.yml down
--
-- Operator runs (out of band) after this:
--   cd C:\Programming\PMIS\PMIS-OpenProject && docker-compose up -d
--   Revert FE VITE_API_BASE_URL to point at the monolith host.

BEGIN;

DROP SCHEMA IF EXISTS users CASCADE;
DROP SCHEMA IF EXISTS project CASCADE;
DROP SCHEMA IF EXISTS notification CASCADE;
DROP SCHEMA IF EXISTS masters CASCADE;

COMMIT;
