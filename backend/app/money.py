"""Money helpers. Money is integer paise everywhere; Decimal rupees only at the edges."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAISE_PER_RUPEE = 100


def to_decimal(value) -> Decimal:
    """Convert Excel/JSON input to Decimal without float artefacts (1193.8 -> Decimal('1193.8'))."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("boolean is not a number")
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, int):
        return Decimal(value)
    text = str(value).strip().replace(",", "").replace("₹", "")
    return Decimal(text)


def rupees_to_paise(value) -> int:
    return int((to_decimal(value) * PAISE_PER_RUPEE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paise_to_rupees(paise: int) -> Decimal:
    return (Decimal(paise) / PAISE_PER_RUPEE).quantize(Decimal("0.01"))


def round_paise(value: Decimal) -> int:
    """Round a Decimal amount already expressed in paise to an integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def value_paise(quantity: Decimal, unit_price: Decimal) -> int:
    """quantity x price (rupees) -> paise, rounded half-up."""
    return round_paise(quantity * unit_price * PAISE_PER_RUPEE)


def group_indian(digits: str) -> str:
    """'1234567' -> '12,34,567' (last 3 digits, then groups of 2)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def format_inr(paise: int, symbol: bool = True, decimals: bool = True) -> str:
    """Format paise as INR with Indian digit grouping: 12345600 -> '₹1,23,456.00'."""
    negative = paise < 0
    paise = abs(paise)
    if decimals:
        rupees, rem = divmod(paise, 100)
        body = f"{group_indian(str(rupees))}.{rem:02d}"
    else:
        rupees = (paise + 50) // 100
        body = group_indian(str(rupees))
    return f"{'-' if negative else ''}{'₹' if symbol else ''}{body}"


def format_pct(fraction: Decimal | None, places: int = 1) -> str:
    if fraction is None:
        return "N/A"
    q = Decimal(1).scaleb(-places)
    return f"{(fraction * 100).quantize(q, rounding=ROUND_HALF_UP)}%"
