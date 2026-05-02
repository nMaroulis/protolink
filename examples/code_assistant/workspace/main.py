"""Main entry point for the calculator application."""

from config import APP_NAME, VERSION
from utils import add, multiply, subtract


def main():
    print(f"Welcome to {APP_NAME} v{VERSION}")
    print(f"2 + 3 = {add(2, 3)}")
    print(f"10 - 4 = {subtract(10, 4)}")
    print(f"5 * 6 = {multiply(5, 6)}")


if __name__ == "__main__":
    main()
