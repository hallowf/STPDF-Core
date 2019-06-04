
def while_generator(limit=500, count=50):
    i = 0
    while i <= limit:
        yield i
        i += count
