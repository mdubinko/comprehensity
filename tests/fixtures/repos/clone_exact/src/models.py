class Item:
    def __init__(self, price, quantity):
        self.price = price
        self.quantity = quantity


def compute_total(items):
    total = 0
    for item in items:
        total += item.price * item.quantity
    return total
