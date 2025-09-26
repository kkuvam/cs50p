#!/usr/bin/env python3
"""Create an admin user for the Flask app"""

import sys
import os
sys.path.append('.')

from main import app, db
from models import User
from werkzeug.security import generate_password_hash

def create_admin_user():
    email = "admin@example.com"
    password = "admin123"
    name = "System Admin"

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

        print(f"Admin user created successfully!")
        print(f"Email: {email}")
        print(f"Password: {password}")
        print(f"Name: {name}")

if __name__ == "__main__":
    create_admin_user()
