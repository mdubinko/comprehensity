def compute_total(items):
    total = 0
    for item in items:
        total += item.price * item.quantity
    return total


def format_currency(amount):
    return f"${amount:.2f}"
