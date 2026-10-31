from .models import User


def register_user(*, name, email, password, role, usn=None):
    """Create a student or faculty account with a hashed password."""
    if role not in (User.Role.STUDENT, User.Role.FACULTY):
        raise ValueError("Public registration cannot create administrators")
    return User.objects.create_user(
        name=name,
        email=email,
        password=password,
        role=role,
        usn=usn,
    )
