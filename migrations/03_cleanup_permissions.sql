-- PMIS Refactor — Step 4 of cutover.
-- Cleans up permission codes for excluded modules (Q25) and drops the
-- already-unified project_members table (Q12).
-- Run AFTER 01_copy_data.sql.

BEGIN;

-- =========================================================================
-- Drop role_permissions FIRST (FKs to permissions.code), then user_permissions,
-- then permissions themselves.
-- =========================================================================
DELETE FROM users.role_permissions
WHERE permission_code LIKE 'meetings:%'
   OR permission_code LIKE 'work_packages:%'
   OR permission_code LIKE 'work_package_types:%';

DELETE FROM users.user_permissions
WHERE permission_code LIKE 'meetings:%'
   OR permission_code LIKE 'work_packages:%'
   OR permission_code LIKE 'work_package_types:%';

DELETE FROM users.permissions
WHERE code LIKE 'meetings:%'
   OR code LIKE 'work_packages:%'
   OR code LIKE 'work_package_types:%';

-- =========================================================================
-- Drop the dormant project_members table (Q12).
-- The monolith alembic rev `baddc1146b85_unify_project_membership_into_user_*`
-- unified membership into user_role_assignments; the legacy table may still
-- sit empty in some environments.
-- =========================================================================
DROP TABLE IF EXISTS public.project_members CASCADE;

COMMIT;
