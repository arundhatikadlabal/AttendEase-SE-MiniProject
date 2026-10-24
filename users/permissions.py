import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)


class HasAllowedRole(BasePermission):
    """Deny protected API access unless the view explicitly permits the user's role."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        roles_by_method = getattr(view, "roles_by_method", {})
        allowed_roles = roles_by_method.get(
            request.method, getattr(view, "allowed_roles", ())
        )
        permitted = user.role in allowed_roles
        if not permitted:
            logger.warning(
                "Role access denied: user_id=%s role=%s view=%s method=%s",
                user.pk,
                user.role,
                view.__class__.__name__,
                request.method,
            )
        return permitted
