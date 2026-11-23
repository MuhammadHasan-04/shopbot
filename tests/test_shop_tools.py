"""ShopBot tools tested directly: no LLM, no API key, no cost. A fresh in-memory store per test
(when deployed the same code runs on the Postgres store)."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langgraph.store.memory import InMemoryStore

from app import shop_tools as s


@pytest.fixture
def store():
    return InMemoryStore()


def rt(store, user_id="ali", role="customer"):
    """A stand-in for ToolRuntime: just the bits our tools read."""
    return SimpleNamespace(context=s.ShopContext(user_id=user_id, role=role), store=store)


def test_search_respects_budget_and_keywords(store):
    ids = [p["id"] for p in s.find_products(store, "wireless earbuds", max_price=5000)]
    assert ids[0] == "AUD-101" and "AUD-102" not in ids      # Rs 8,999 Pro is over budget


def test_out_of_stock_is_reported(store):
    assert "OUT OF STOCK" in s.get_product.func("AUD-105", rt(store))
    assert "out of stock" in s.add_to_cart.func("AUD-105", rt(store))


def test_cart_totals_and_delivery_fee(store):
    s.add_to_cart.func("AUD-104", rt(store))                  # Rs 3,499
    c = s.cart_summary(store, "ali")
    assert (c["subtotal"], c["shipping"], c["total"]) == (3499, 250, 3749)


def test_discount_codes(store):
    s.add_to_cart.func("AUD-102", rt(store))                  # Rs 8,999
    assert s.cart_summary(store, "ali", "WELCOME10")["discount"] == 900
    assert s.cart_summary(store, "ali", "TECH500")["discount"] == 500
    assert s.cart_summary(store, "ali", "FAKE")["discount"] == 0


def test_users_are_isolated(store):
    s.add_to_cart.func("CHG-201", rt(store, "ali"))
    assert "empty" in s.view_cart.func(rt(store, "sara"))
    assert "CHG-201" in s.view_cart.func(rt(store, "ali"))


def test_order_needs_human_yes(store):
    s.add_to_cart.func("AUD-104", rt(store))
    with patch.object(s, "interrupt", return_value="no"):
        assert "NOT placed" in s.place_order.func("House 5, Clifton, Karachi", rt(store))
    assert not s.list_orders(store)
    stock = s.get_item(store, "AUD-104")["stock"]
    with patch.object(s, "interrupt", return_value="yes"):
        assert "placed" in s.place_order.func("House 5, Clifton, Karachi", rt(store))
    orders = s.list_orders(store)
    assert len(orders) == 1 and orders[0]["user_id"] == "ali"
    assert s.get_item(store, "AUD-104")["stock"] == stock - 1
    assert "No orders" in s.my_orders.func(rt(store, "sara"))       # another user can't see it


def test_cancel_needs_yes_and_restocks(store):
    s.add_to_cart.func("CHG-203", rt(store))
    stock = s.get_item(store, "CHG-203")["stock"]
    with patch.object(s, "interrupt", return_value="yes"):
        s.place_order.func("House 5, Clifton, Karachi", rt(store))
        oid = s.list_orders(store, "ali")[0]["order_id"]
        assert "cancelled" in s.cancel_order.func(oid, rt(store))
    assert s.get_item(store, "CHG-203")["stock"] == stock
    assert "No order" in s.cancel_order.func(oid, rt(store, "sara"))  # can't touch someone else's order


def test_seller_report_is_seller_only(store):
    assert "Only the seller" in s.sales_report.func(rt(store, role="customer"))
    assert "Revenue" in s.sales_report.func(rt(store, role="seller"))


def test_long_term_memory_is_per_user(store):
    s.remember_preference.func("uses an iPhone 15", rt(store, "ali"))
    assert "iPhone 15" in s.recall_preferences.func(rt(store, "ali"))
    assert "Nothing" in s.recall_preferences.func(rt(store, "sara"))


def test_yes_detection():
    assert s.is_yes("yes") and s.is_yes("Haan") and s.is_yes("ok go ahead")
    assert not s.is_yes("no") and not s.is_yes("yes but not now") and not s.is_yes("wait")
