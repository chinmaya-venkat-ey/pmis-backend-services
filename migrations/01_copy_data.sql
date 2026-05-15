-- PMIS Refactor — Step 3 of cutover (after each service's alembic creates empty tables).
-- Copies row data from public.* to <schema>.<table> with deferred FK constraints.
-- Run against the SAME Postgres instance as the prod DB during the maintenance window.

BEGIN;

SET CONSTRAINTS ALL DEFERRED;

-- =========================================================================
-- users.* (RBAC, auth, notification audit log)
-- =========================================================================
INSERT INTO users.users                   SELECT * FROM public.users;
INSERT INTO users.roles                   SELECT * FROM public.roles;
INSERT INTO users.permissions             SELECT * FROM public.permissions;
INSERT INTO users.user_roles              SELECT * FROM public.user_roles;
INSERT INTO users.role_permissions        SELECT * FROM public.role_permissions;
INSERT INTO users.user_permissions        SELECT * FROM public.user_permissions;
INSERT INTO users.user_role_assignments   SELECT * FROM public.user_role_assignments;
INSERT INTO users.revoked_tokens          SELECT * FROM public.revoked_tokens;
INSERT INTO users.password_reset_tokens   SELECT * FROM public.password_reset_tokens;
INSERT INTO users.otp_codes               SELECT * FROM public.otp_codes;
INSERT INTO users.notification_log        SELECT * FROM public.notification_log;

-- =========================================================================
-- masters.* (catalogs + notification templates per Q3)
-- =========================================================================
INSERT INTO masters.divisions                  SELECT * FROM public.divisions;
INSERT INTO masters.vendors                    SELECT * FROM public.vendors;
INSERT INTO masters.resource_types             SELECT * FROM public.resource_types;
INSERT INTO masters.project_categories         SELECT * FROM public.project_categories;
INSERT INTO masters.activity_types             SELECT * FROM public.activity_types;
INSERT INTO masters.activity_statuses          SELECT * FROM public.activity_statuses;
INSERT INTO masters.milestone_statuses         SELECT * FROM public.milestone_statuses;
INSERT INTO masters.project_status_transitions SELECT * FROM public.project_status_transitions;
INSERT INTO masters.priorities                 SELECT * FROM public.priorities;
INSERT INTO masters.notification_templates     SELECT * FROM public.notification_templates;

-- =========================================================================
-- project.* (projects + M/A/T/S + dependencies + resources + comments + audit)
-- =========================================================================
INSERT INTO project.projects                SELECT * FROM public.projects;
INSERT INTO project.project_audit_logs      SELECT * FROM public.project_audit_logs;
INSERT INTO project.project_vendors         SELECT * FROM public.project_vendors;
INSERT INTO project.milestones              SELECT * FROM public.milestones;
INSERT INTO project.milestone_dependencies  SELECT * FROM public.milestone_dependencies;
INSERT INTO project.milestone_vendors       SELECT * FROM public.milestone_vendors;
INSERT INTO project.activities              SELECT * FROM public.activities;
INSERT INTO project.activity_dependencies   SELECT * FROM public.activity_dependencies;
INSERT INTO project.activity_resources      SELECT * FROM public.activity_resources;
INSERT INTO project.tasks                   SELECT * FROM public.tasks;
INSERT INTO project.task_dependencies       SELECT * FROM public.task_dependencies;
INSERT INTO project.task_resources          SELECT * FROM public.task_resources;
INSERT INTO project.subtasks                SELECT * FROM public.subtasks;
INSERT INTO project.subtask_dependencies    SELECT * FROM public.subtask_dependencies;
INSERT INTO project.subtask_resources       SELECT * FROM public.subtask_resources;
INSERT INTO project.comments                SELECT * FROM public.comments;

-- =========================================================================
-- Sync autoincrement sequences for integer-PK tables.
-- =========================================================================
SELECT setval(pg_get_serial_sequence('users.roles', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM users.roles));
SELECT setval(pg_get_serial_sequence('users.user_role_assignments', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM users.user_role_assignments));
SELECT setval(pg_get_serial_sequence('users.password_reset_tokens', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM users.password_reset_tokens));
SELECT setval(pg_get_serial_sequence('users.otp_codes', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM users.otp_codes));
SELECT setval(pg_get_serial_sequence('users.notification_log', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM users.notification_log));
SELECT setval(pg_get_serial_sequence('masters.divisions', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM masters.divisions));
SELECT setval(pg_get_serial_sequence('masters.project_categories', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM masters.project_categories));
SELECT setval(pg_get_serial_sequence('masters.activity_types', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM masters.activity_types));
SELECT setval(pg_get_serial_sequence('masters.activity_statuses', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM masters.activity_statuses));
SELECT setval(pg_get_serial_sequence('masters.milestone_statuses', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM masters.milestone_statuses));
SELECT setval(pg_get_serial_sequence('masters.project_status_transitions', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM masters.project_status_transitions));
SELECT setval(pg_get_serial_sequence('masters.notification_templates', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM masters.notification_templates));
SELECT setval(pg_get_serial_sequence('project.project_audit_logs', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM project.project_audit_logs));

COMMIT;
