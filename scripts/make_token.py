import sys
import uuid

from core.security import create_access_token
from models.enums import UserRole


def main() -> None:
    roles = [role.value for role in UserRole]
    if len(sys.argv) != 3 or sys.argv[2] not in roles:
        print("Usage: python -m scripts.make_token <user_id> <" + "|".join(roles) + ">")
        raise SystemExit(1)
    user_id = uuid.UUID(sys.argv[1])
    print(create_access_token(user_id, UserRole(sys.argv[2]), expires_minutes=1440))


if __name__ == "__main__":
    main()
