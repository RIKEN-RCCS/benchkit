from flask import session

from utils.user_store import get_user_store


def get_session_user_context():
    """Return the current session authentication state and resolved affiliations."""
    authenticated = session.get("authenticated", False)
    email = session.get("user_email")
    affiliations = []
    if authenticated and email:
        affiliations = get_user_store().get_affiliations(email)
    return {
        "authenticated": authenticated,
        "email": email,
        "affiliations": affiliations,
    }
