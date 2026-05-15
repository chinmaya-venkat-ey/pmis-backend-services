-- PMIS Refactor — Step 6 of cutover (POST BURN-IN, 7+ days clean).
-- Drops every legacy `public.*` table after the new app has run cleanly.
-- DO NOT RUN UNTIL BURN-IN COMPLETES (operator-gated; see CUTOVER_RUNBOOK.md).
--
-- Order: drop legacy-exclude tables (meetings, work_packages) first since
-- they have FK chains within themselves; then drop migrated tables.

BEGIN;

-- =========================================================================
-- LEGACY-EXCLUDE tables (user-flagged at Phase 0; removed entirely)
-- FK chain: meeting_agenda_items.work_package_id → work_packages.id
-- Drop participants and agenda_items first, then meetings, then work_packages,
-- then work_package_types.
-- =========================================================================
DROP TABLE IF EXISTS public.meeting_participants    CASCADE;
DROP TABLE IF EXISTS public.meeting_agenda_items    CASCADE;
DROP TABLE IF EXISTS public.meetings                CASCADE;
DROP TABLE IF EXISTS public.work_packages           CASCADE;
DROP TABLE IF EXISTS public.work_package_types      CASCADE;

-- =========================================================================
-- MIGRATED tables — data lives in users.* / project.* / masters.* now.
-- =========================================================================
DROP TABLE IF EXISTS public.users                     CASCADE;
DROP TABLE IF EXISTS public.roles                     CASCADE;
DROP TABLE IF EXISTS public.permissions               CASCADE;
DROP TABLE IF EXISTS public.user_roles                CASCADE;
DROP TABLE IF EXISTS public.role_permissions          CASCADE;
DROP TABLE IF EXISTS public.user_permissions          CASCADE;
DROP TABLE IF EXISTS public.user_role_assignments     CASCADE;
DROP TABLE IF EXISTS public.revoked_tokens            CASCADE;
DROP TABLE IF EXISTS public.password_reset_tokens     CASCADE;
DROP TABLE IF EXISTS public.otp_codes                 CASCADE;
DROP TABLE IF EXISTS public.notification_log          CASCADE;

DROP TABLE IF EXISTS public.divisions                  CASCADE;
DROP TABLE IF EXISTS public.vendors                    CASCADE;
DROP TABLE IF EXISTS public.resource_types             CASCADE;
DROP TABLE IF EXISTS public.project_categories         CASCADE;
DROP TABLE IF EXISTS public.activity_types             CASCADE;
DROP TABLE IF EXISTS public.activity_statuses          CASCADE;
DROP TABLE IF EXISTS public.milestone_statuses         CASCADE;
DROP TABLE IF EXISTS public.project_status_transitions CASCADE;
DROP TABLE IF EXISTS public.priorities                 CASCADE;
DROP TABLE IF EXISTS public.notification_templates     CASCADE;

DROP TABLE IF EXISTS public.projects                CASCADE;
DROP TABLE IF EXISTS public.project_audit_logs      CASCADE;
DROP TABLE IF EXISTS public.project_vendors         CASCADE;
DROP TABLE IF EXISTS public.milestones              CASCADE;
DROP TABLE IF EXISTS public.milestone_dependencies  CASCADE;
DROP TABLE IF EXISTS public.milestone_vendors       CASCADE;
DROP TABLE IF EXISTS public.activities              CASCADE;
DROP TABLE IF EXISTS public.activity_dependencies   CASCADE;
DROP TABLE IF EXISTS public.activity_resources      CASCADE;
DROP TABLE IF EXISTS public.tasks                   CASCADE;
DROP TABLE IF EXISTS public.task_dependencies       CASCADE;
DROP TABLE IF EXISTS public.task_resources          CASCADE;
DROP TABLE IF EXISTS public.subtasks                CASCADE;
DROP TABLE IF EXISTS public.subtask_dependencies    CASCADE;
DROP TABLE IF EXISTS public.subtask_resources       CASCADE;
DROP TABLE IF EXISTS public.comments                CASCADE;

-- alembic version tables of the old monolith chain
DROP TABLE IF EXISTS public.alembic_version            CASCADE;
DROP TABLE IF EXISTS public.alembic_version_user_svc   CASCADE;
DROP TABLE IF EXISTS public.alembic_version_project_svc CASCADE;

COMMIT;
