from flask import session, redirect, url_for

def role_required(roles):

    def decorator(f):
        def decorated_function(*args, **kwargs):

            user_role = session.get("role")

            if user_role not in roles:
                return redirect(url_for("dashboard.dashboard"))

            return f(*args, **kwargs)

        decorated_function.__name__ = f.__name__
        return decorated_function

    return decorator
