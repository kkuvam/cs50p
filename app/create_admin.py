#!/usr/bin/env python3
"""Create an admin user for the Flask app.

Reads ADMIN_EMAIL / ADMIN_PASSWORD from the environment, otherwise prompts.
"""

import os
import sys
from getpass import getpass

sys.path.append('.')

from main import app, db
from models import User
from werkzeug.security import generate_password_hash

MIN_PASSWORD_LENGTH = 12


def create_admin_user():
    email = (os.environ.get("ADMIN_EMAIL") or input("Admin email: ")).strip().lower()
    password = os.environ.get("ADMIN_PASSWORD")
    if password is None:
        password = getpass("Admin password: ")
        if getpass("Repeat password: ") != password:
            sys.exit("Passwords do not match.")
    name = "System Admin"

    if not email:
        sys.exit("Email is required.")
    if len(password) < MIN_PASSWORD_LENGTH or password == "admin123":
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    with app.app_context():
        # Create all tables
        db.create_all()

        # Check if admin already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print(f"User with email {email} already exists!")
            print(f"Admin status: {'Yes' if existing_user.is_admin else 'No'}")
            return

        # Create new admin user
        admin_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            full_name=name,
            is_active=True,
            is_admin=True
        )

        db.session.add(admin_user)
        db.session.commit()

        print("Admin user created successfully!")
        print(f"Email: {email}")
        print(f"Name: {name}")

if __name__ == "__main__":
    create_admin_user()
