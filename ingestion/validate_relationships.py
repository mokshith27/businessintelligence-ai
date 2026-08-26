from pathlib import Path
import duckdb


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)


# ============================================================
# DATABASE
# ============================================================

def connect_database():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB database not found:\n{DB_PATH}\n"
            "Run load_and_build_kpis.py first."
        )

    return duckdb.connect(str(DB_PATH), read_only=True)


# ============================================================
# HELPER
# ============================================================

def print_check(name, value, expected=None):
    print(f"\n{name}")
    print("-" * 70)
    print(f"Result: {value}")

    if expected is not None:
        print(f"Expected/Reference: {expected}")


# ============================================================
# 1. ORDERS -> CUSTOMERS
# ============================================================

def validate_orders_customers(con):

    total_orders = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_orders_dataset
        """
    ).fetchone()[0]

    matched = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_orders_dataset o
        INNER JOIN olist_customers_dataset c
            ON o.customer_id = c.customer_id
        """
    ).fetchone()[0]

    unmatched = total_orders - matched

    print_check(
        "1. ORDERS -> CUSTOMERS",
        f"{matched:,} / {total_orders:,} orders matched",
        "Ideally almost/all orders match"
    )

    print(f"Unmatched orders: {unmatched:,}")


# ============================================================
# 2. ORDER ITEMS -> ORDERS
# ============================================================

def validate_items_orders(con):

    total_items = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_order_items_dataset
        """
    ).fetchone()[0]

    matched = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_order_items_dataset i
        INNER JOIN olist_orders_dataset o
            ON i.order_id = o.order_id
        """
    ).fetchone()[0]

    unmatched = total_items - matched

    print_check(
        "2. ORDER ITEMS -> ORDERS",
        f"{matched:,} / {total_items:,} items matched",
        "Ideally all order items match an order"
    )

    print(f"Unmatched items: {unmatched:,}")


# ============================================================
# 3. ORDER ITEMS -> PRODUCTS
# ============================================================

def validate_items_products(con):

    total_items = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_order_items_dataset
        """
    ).fetchone()[0]

    matched = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_order_items_dataset i
        INNER JOIN olist_products_dataset p
            ON i.product_id = p.product_id
        """
    ).fetchone()[0]

    unmatched = total_items - matched

    print_check(
        "3. ORDER ITEMS -> PRODUCTS",
        f"{matched:,} / {total_items:,} items matched",
        "Ideally all items match a product"
    )

    print(f"Unmatched items: {unmatched:,}")


# ============================================================
# 4. ORDER ITEMS -> SELLERS
# ============================================================

def validate_items_sellers(con):

    total_items = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_order_items_dataset
        """
    ).fetchone()[0]

    matched = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_order_items_dataset i
        INNER JOIN olist_sellers_dataset s
            ON i.seller_id = s.seller_id
        """
    ).fetchone()[0]

    unmatched = total_items - matched

    print_check(
        "4. ORDER ITEMS -> SELLERS",
        f"{matched:,} / {total_items:,} items matched",
        "Ideally all items match a seller"
    )

    print(f"Unmatched items: {unmatched:,}")


# ============================================================
# 5. ORDERS -> PAYMENTS
# ============================================================

def validate_orders_payments(con):

    total_orders = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_orders_dataset
        """
    ).fetchone()[0]

    matched_orders = con.execute(
        """
        SELECT COUNT(DISTINCT o.order_id)
        FROM olist_orders_dataset o
        INNER JOIN olist_order_payments_dataset p
            ON o.order_id = p.order_id
        """
    ).fetchone()[0]

    unmatched_orders = total_orders - matched_orders

    print_check(
        "5. ORDERS -> PAYMENTS",
        f"{matched_orders:,} / {total_orders:,} orders have payment records",
        "Most purchase orders should have payments"
    )

    print(f"Orders without payments: {unmatched_orders:,}")


# ============================================================
# 6. ORDERS -> REVIEWS
# ============================================================

def validate_orders_reviews(con):

    total_orders = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_orders_dataset
        """
    ).fetchone()[0]

    reviewed_orders = con.execute(
        """
        SELECT COUNT(DISTINCT o.order_id)
        FROM olist_orders_dataset o
        INNER JOIN olist_order_reviews_dataset r
            ON o.order_id = r.order_id
        """
    ).fetchone()[0]

    print_check(
        "6. ORDERS -> REVIEWS",
        f"{reviewed_orders:,} / {total_orders:,} orders have review records",
        "Not every order needs a review"
    )

    print(
        f"Orders without reviews: "
        f"{total_orders - reviewed_orders:,}"
    )


# ============================================================
# 7. PRODUCTS -> CATEGORY TRANSLATION
# ============================================================

def validate_product_categories(con):

    total_products_with_category = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_products_dataset
        WHERE product_category_name IS NOT NULL
        """
    ).fetchone()[0]

    translated = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_products_dataset p
        INNER JOIN product_category_name_translation t
            ON p.product_category_name =
               t.product_category_name
        WHERE p.product_category_name IS NOT NULL
        """
    ).fetchone()[0]

    unmatched = (
        total_products_with_category - translated
    )

    print_check(
        "7. PRODUCTS -> CATEGORY TRANSLATION",
        f"{translated:,} / {total_products_with_category:,} "
        f"categorized products translated",
        "Most should have translations"
    )

    print(f"Untranslated categorized products: {unmatched:,}")


# ============================================================
# 8. MQL -> CLOSED DEALS
# ============================================================

def validate_mql_closed_deals(con):

    total_deals = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_closed_deals_dataset
        """
    ).fetchone()[0]

    matched = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_closed_deals_dataset d
        INNER JOIN olist_marketing_qualified_leads_dataset m
            ON d.mql_id = m.mql_id
        """
    ).fetchone()[0]

    unmatched = total_deals - matched

    print_check(
        "8. MQL -> CLOSED DEALS",
        f"{matched:,} / {total_deals:,} closed deals matched to MQL",
        "Ideally all closed deals match an MQL"
    )

    print(f"Unmatched closed deals: {unmatched:,}")


# ============================================================
# 9. CLOSED DEALS -> SELLERS
# ============================================================

def validate_deals_sellers(con):

    total_deals = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_closed_deals_dataset
        """
    ).fetchone()[0]

    matched = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_closed_deals_dataset d
        INNER JOIN olist_sellers_dataset s
            ON d.seller_id = s.seller_id
        """
    ).fetchone()[0]

    unmatched = total_deals - matched

    print_check(
        "9. CLOSED DEALS -> SELLERS",
        f"{matched:,} / {total_deals:,} deals matched to sellers",
        "This is important for marketing -> seller -> orders linkage"
    )

    print(f"Unmatched deals: {unmatched:,}")


# ============================================================
# 10. SELLERS -> ORDER ACTIVITY
# ============================================================

def validate_seller_order_activity(con):

    sellers_with_orders = con.execute(
        """
        SELECT COUNT(DISTINCT i.seller_id)
        FROM olist_order_items_dataset i
        INNER JOIN olist_sellers_dataset s
            ON i.seller_id = s.seller_id
        """
    ).fetchone()[0]

    total_sellers = con.execute(
        """
        SELECT COUNT(*)
        FROM olist_sellers_dataset
        """
    ).fetchone()[0]

    print_check(
        "10. SELLERS -> ORDER ACTIVITY",
        f"{sellers_with_orders:,} / {total_sellers:,} sellers have order activity",
        "Useful for marketing funnel -> seller -> order analysis"
    )

    print(
        f"Sellers without order activity: "
        f"{total_sellers - sellers_with_orders:,}"
    )


# ============================================================
# 11. ORDER ITEM MULTIPLICITY
# ============================================================

def inspect_order_item_multiplicity(con):

    result = con.execute(
        """
        SELECT
            COUNT(*) AS total_orders,
            COUNT_IF(item_count = 1) AS one_item,
            COUNT_IF(item_count > 1) AS multi_item_orders,
            MAX(item_count) AS max_items
        FROM (
            SELECT
                order_id,
                COUNT(*) AS item_count
            FROM olist_order_items_dataset
            GROUP BY order_id
        );
        """
    ).fetchone()

    total_orders, one_item, multi_item, max_items = result

    print_check(
        "11. ORDER -> ITEM MULTIPLICITY",
        "",
        "Important because GMV is item-grain"
    )

    print(f"Orders represented by items : {total_orders:,}")
    print(f"Single-item orders          : {one_item:,}")
    print(f"Multi-item orders           : {multi_item:,}")
    print(f"Maximum items in one order : {max_items}")


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("RELATIONSHIP VALIDATION")
    print("=" * 80)

    con = connect_database()

    try:
        validate_orders_customers(con)
        validate_items_orders(con)
        validate_items_products(con)
        validate_items_sellers(con)
        validate_orders_payments(con)
        validate_orders_reviews(con)
        validate_product_categories(con)
        validate_mql_closed_deals(con)
        validate_deals_sellers(con)
        validate_seller_order_activity(con)
        inspect_order_item_multiplicity(con)

        print("\n" + "=" * 80)
        print("RELATIONSHIP VALIDATION COMPLETE")
        print("=" * 80)

    finally:
        con.close()


if __name__ == "__main__":
    main()