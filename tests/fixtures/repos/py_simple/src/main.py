from utils import greet
from models import User


def run():
    u = User(name="Alice")
    print(greet(u.name))
