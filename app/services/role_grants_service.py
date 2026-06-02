"""RoleGrantsService — static matrix of "which roles can role X grant".

Doc-42b/round-5 conventions, simplified. Returned by
GET /user/role-grants/{role_name}/matrix and consumed by the FE to render
the "Add role" picker (showing only roles the caller is allowed to grant).

This is static-data; lives in code so a server restart isn't needed to
adjust the matrix in dev. For runtime flexibility, move into a config table.
"""
from __future__ import annotations

from typing import Dict, List

from app.core.permissions import (
    ADMIN_ROLE,
    DIVISION_MEMBER_ROLE,
    ORG_ADMIN_ROLE,
    PROJECT_ADMIN_ROLE,
    PROJECT_MEMBER_ROLE,
    SUPER_ADMIN_ROLE,
)
from app.schemas.role_grants import GrantableRole, RoleGrantsMatrixResponse


_MATRIX: Dict[str, List[GrantableRole]] = {
    SUPER_ADMIN_ROLE: [
        GrantableRole(name=SUPER_ADMIN_ROLE, scope="global", notes="only super_admin can grant super_admin"),
        GrantableRole(name=ADMIN_ROLE, scope="global", notes="round-8 H3: only super_admin can grant admin"),
        GrantableRole(name=ORG_ADMIN_ROLE, scope="org"),
        GrantableRole(name=PROJECT_ADMIN_ROLE, scope="project"),
        GrantableRole(name=PROJECT_MEMBER_ROLE, scope="project"),
        GrantableRole(name=DIVISION_MEMBER_ROLE, scope="org"),
    ],
    # Round-8 H3 (monolith parity, PMIS-user-management/.../role_assignments/services.py:188-194):
    # admin can NOT grant admin to anyone. Only super_admin promotes to admin.
    ADMIN_ROLE: [
        GrantableRole(name=ORG_ADMIN_ROLE, scope="org"),
        GrantableRole(name=PROJECT_ADMIN_ROLE, scope="project"),
        GrantableRole(name=PROJECT_MEMBER_ROLE, scope="project"),
        GrantableRole(name=DIVISION_MEMBER_ROLE, scope="org"),
    ],
    ORG_ADMIN_ROLE: [
        GrantableRole(
            name=PROJECT_ADMIN_ROLE, scope="project",
            notes="only on projects in caller's own vendor",
        ),
        GrantableRole(
            name=PROJECT_MEMBER_ROLE, scope="project",
            notes="only on projects in caller's own vendor",
        ),
        GrantableRole(
            name=DIVISION_MEMBER_ROLE, scope="org",
            notes="caller's own vendor only",
        ),
    ],
    PROJECT_ADMIN_ROLE: [
        GrantableRole(
            name=PROJECT_MEMBER_ROLE, scope="project",
            notes="only on projects the caller is assigned to",
        ),
    ],
    PROJECT_MEMBER_ROLE: [],
    DIVISION_MEMBER_ROLE: [],
}


# Round-8 C4/H3 server-side enforcement helper. Used by
# RoleAssignmentService._assert_caller_can_grant to consult the SAME matrix
# the FE picker uses. Keeps server + UI in lock-step.
def grantable_role_names_for(caller_role_names: set[str]) -> set[str]:
    """Union of role names every role in `caller_role_names` may grant."""
    out: set[str] = set()
    for role in caller_role_names:
        out.update(g.name for g in _MATRIX.get(role, []))
    return out


def is_grant_allowed(
    *,
    caller_role_names: set[str],
    target_role_name: str,
    scope_kind: str,
) -> bool:
    """True iff some role the caller holds permits granting `target_role_name`
    at `scope_kind` ('global' / 'org' / 'project'). `caller_role_names` is
    the set of role names the caller actually holds via either tier."""
    for role in caller_role_names:
        for g in _MATRIX.get(role, []):
            if g.name == target_role_name and g.scope == scope_kind:
                return True
    return False


class RoleGrantsService:
    def get_matrix_for(self, role_name: str) -> RoleGrantsMatrixResponse:
        return RoleGrantsMatrixResponse(
            role_name=role_name,
            grantable_roles=_MATRIX.get(role_name, []),
        )
