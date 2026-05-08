"""Delete an attachment (doc 35: alias for delete_comment).

After doc 35 the attachments table is gone — an "attachment row" is
just a comment row with NULL body. ``DELETE /attachments/{id}``
therefore resolves to ``DELETE /comments/{id}`` with the id treated
as a comment id (the FE has been carrying the comment row's id as
``attachment.id`` for at least one release for legacy reasons).

Same auth rule as the comments delete: author or admin.
"""
from sqlalchemy.orm import Session

from .....shared.service_result import ServiceResult

from ...comments.services import delete_comment


def delete_attachment(
    db: Session,
    *,
    attachment_id: str,
    actor_id: int,
    actor_is_admin: bool,
) -> ServiceResult[bool]:
    """Soft-delete the row whose id matches.

    The id may have been served either as a comment id (post-doc-34)
    or as a legacy attachment id. The legacy flow is gone — only
    comment ids resolve. Callers using a stale attachment id get a
    clean 404.
    """
    return delete_comment(
        db=db,
        comment_id=attachment_id,
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
    )
