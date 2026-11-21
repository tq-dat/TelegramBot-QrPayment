"""Self-check for check_payments matching. Run: python -m tests.test_payment_match (needs .env)."""
from types import SimpleNamespace as O

from app.utils.payment import match_orders


def tx(tid, amount, desc, type_="IN"):
    return {"transactionID": tid, "amount": amount, "description": desc, "type": type_}


def run() -> None:
    a = O(order_code="VIPAAAA1111", amount=2000)
    b = O(order_code="VIPBBBB2222", amount=500000)
    c = O(order_code="VIPCCCC3333", amount=2000)
    txs = [
        tx("1", "2000", "MBVCB.1 123 user vipaaaa1111 CT tu"),   # a: code is case-insensitive
        tx("2", "500,000", "123 user VIPBBBB2222"),              # b: amount with thousands comma
        tx("3", "2000", "123 user VIPCCCC3333", type_="OUT"),     # c: outgoing, never counts
        tx("4", "1999", "123 user VIPCCCC3333"),                  # c: wrong amount
    ]
    got = {o.order_code: t["transactionID"] for o, t in match_orders([a, b, c], txs, set())}
    assert got == {"VIPAAAA1111": "1", "VIPBBBB2222": "2"}, got

    # A transaction already stored on another order is never reused.
    assert match_orders([a], txs, {"1"}) == []
    print("test_payment_match OK")


if __name__ == "__main__":
    run()
