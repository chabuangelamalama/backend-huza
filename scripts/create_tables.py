from core.database import engine
from models import Base


def main() -> None:
    Base.metadata.create_all(engine)
    print("Tables created")


if __name__ == "__main__":
    main()
