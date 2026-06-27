"""
Store HQ backend — the retail/storefront vertical on the shared AccGenie engine.

Owns its OWN database (`<company>_store.db`, tables `store_*`), separate from the
accounts `.db` (module-data-boundary, separate-DB-files decision). Couples to the
books ONLY by posting vouchers to the accounts VoucherEngine against the
Stock-in-Trade / COGS / supplier ledgers — no cross-DB foreign keys.

v1: inventory (items, movements, perpetual avg-cost + COGS) + purchasing
(suppliers, purchase orders, goods receipt). POS / CRM / UI are later waves.
See eclipse-workspace/STOREHQ_SCOPE.md.
"""
from core.store.models import StoreDB, STORE_SCHEMA
from core.store.engine import StoreEngine
from core.store.sales import StoreSales

__all__ = ["StoreDB", "STORE_SCHEMA", "StoreEngine", "StoreSales"]
