import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or update the initial super admin using environment variables instead of hard-coded credentials."

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get("SUPER_ADMIN_USERNAME", "ZOERDHUB")
        email = os.environ.get("SUPER_ADMIN_EMAIL", "zoerdhub@gmail.com")
        password = os.environ.get("SUPER_ADMIN_PASSWORD")

        if not password:
            raise CommandError("SUPER_ADMIN_PASSWORD must be set in the environment before creating the super admin.")

        user, created = User.objects.get_or_create(username=username, defaults={"email": email})
        if created:
            user.set_password(password)
            user.email = email
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created super admin '{username}'"))
            return

        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.email = email
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Updated super admin '{username}'"))
