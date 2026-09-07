def parse_pattern(s):
    """Comma/semicolon separated values."""
    values = []
    try:
        for tok in (x.strip() for x in s.replace(";", ",").split(",")):
            if not tok:
                continue
            values.append(float(tok))
    except ValueError:
        return []
    return values


def sweep_total(pattern, length):
    return length + len(pattern)


def sweep_values(pattern, length, identity, index_in, mirror):
    """Shift-register slide: pattern's values enter one at a time from the front of a
    length-long array of identity, pushing earlier ones right. Returns (values, total, k)
    where k is index_in clamped into [0, total)."""
    pat = pattern[::-1] if mirror else pattern
    total = sweep_total(pat, length)
    k = max(0, min(index_in, total - 1))
    values = [pat[k - p - 1] if 0 <= k - p - 1 < len(pat) else identity for p in range(length)]
    return values, total, k
