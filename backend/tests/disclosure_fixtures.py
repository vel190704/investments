"""Small synthetic AMC disclosure files built in code (no real downloads)."""

import io

import openpyxl

LT, RIL, HDFCB, TBILL = "INE018A01030", "INE002A01018", "INE040A01034", "IN002026X123"


def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def hdfc() -> bytes:
    mid = [
        ["HDFC Mutual Fund"],
        ["HDFC Mid Cap Fund (An open ended equity scheme predominantly investing in mid cap stocks)"],
        ["Portfolio as on September 30, 2026"],
        [],
        ["Name of the Instrument", "ISIN", "Industry+ /Rating", "Quantity", "Market/ Fair Value (Rs. in Lacs.)", "% to NAV"],
        ["EQUITY & EQUITY RELATED"],
        ["(a) Listed / awaiting listing on Stock Exchanges"],
        ["Larsen and Toubro Ltd.", LT, "Construction", 1000, 3693.4, 6.50],
        ["Reliance Industries Ltd.", RIL, "Petroleum Products", 1000, 1167.7, 3.25],
        ["Sub Total", None, None, None, 4861.1, 9.75],
        ["Treasury Bill 91 Days", TBILL, "Sovereign", 100, 99.1, 1.20],
        ["TREPS - Tri-party Repo", None, None, None, 500, 89.05],
        ["Grand Total", None, None, None, 9999, 100.00],
        ["Footnote row after the total", "INE999Z01011", "x", 1, 1, 50],
    ]
    other = [["HDFC Mutual Fund"], ["HDFC Flexi Cap Fund"], ["Portfolio as on September 30, 2026"],
             ["Name of the Instrument", "ISIN", "Industry+ /Rating", "Quantity", "Market Value", "% to NAV"],
             ["HDFC Bank Ltd.", HDFCB, "Banks", 1, 1, 9.0]]
    return _xlsx({"MIDCAP": mid, "FLEXICAP": other})


def icici() -> bytes:
    rows = [
        ["ICICI Prudential Mutual Fund"],
        ["ICICI Prudential Nifty 50 Index Fund"],
        ["Portfolio as on Sep 30,2026"],
        ["Company/Issuer/Instrument Name", "ISIN", "Coupon", "Industry/Rating", "Quantity",
         "Exposure/Market Value(Rs.Lakh)", "% to Nav", "Yield of the instrument"],
        ["Equity & Equity Related Instruments"],
        ["HDFC Bank Ltd.", HDFCB, None, "Banks", 10, 100, 0.1250, None],
        ["Reliance Industries Ltd.", RIL, None, "Petroleum Products", 10, 80, 0.0900, None],
        ["Larsen & Toubro Ltd.", LT, None, "Construction", 10, 40, 0.0400, None],
        ["Net Current Assets", None, None, None, None, 1, 0.7450, None],
        ["Total Net Assets", None, None, None, None, 221, 1.0000, None],
    ]
    return _xlsx({"Nifty50 Index": rows})


def kotak() -> bytes:
    rows = [
        ["Kotak Mahindra Mutual Fund"],
        ["Kotak Nifty Next 50 Index Fund"],
        ["Portfolio as on 30-Sep-2026"],
        ["Name of Instrument", "ISIN Code", "Industry", "Rating", "Quantity", "Market Value (Rs. in Lacs)",
         "% to Net Assets"],
        ["Equity & Equity related"],
        ["Bharat Electronics Ltd.", "INE263A01024", "Aerospace & Defense", None, 10, 10, "4.10%"],
        ["Tata Power Co Ltd.", "INE245A01021", "Power", None, 10, 10, "3.00%"],
        ["Triparty Repo", None, None, None, None, 10, "92.90%"],
    ]
    return _xlsx({"KOTAK NN50": rows})


def index_weights_csv() -> bytes:
    return (f"ISIN,Company Name,Weightage %,Industry\n{HDFCB},HDFC Bank Ltd.,12.5,Financial Services\n"
            f"{RIL},Reliance Industries Ltd.,9.0,Oil Gas & Consumable Fuels\n{LT},Larsen & Toubro Ltd.,4.0,Construction\n"
            f"INE009A01021,Infosys Ltd.,74.5,Information Technology\n").encode()


def unknown_layout() -> bytes:
    return _xlsx({"Sheet1": [["Some Other AMC"], ["Security", "Code", "Pct"], ["X", "INE018A01030", 5]]})
