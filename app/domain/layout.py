"""Pure dashboard packing rules."""
WIDGET_SIZES = ((1, 1), (2, 1), (2, 2), (4, 1), (4, 2))

def pack_widgets(sizes: list[tuple[int, int]], columns: int) -> list[tuple[int, int, int, int]]:
    """First-fit packing; narrow windows clamp width without changing saved sizes."""
    occupied: set[tuple[int, int]] = set()
    result = []
    for width, height in sizes:
        width = min(width, columns)
        row = 0
        while True:
            position = next((col for col in range(columns - width + 1)
                             if all((r, c) not in occupied for r in range(row, row + height)
                                    for c in range(col, col + width))), None)
            if position is not None:
                break
            row += 1
        occupied.update((r, c) for r in range(row, row + height) for c in range(position, position + width))
        result.append((row, position, width, height))
    return result
