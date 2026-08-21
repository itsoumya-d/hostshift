"""One-time builder for tasks/reference_specs/filter-*.json.

These are hand-authored fixtures, not criteria-derived stubs: each one is a
real UI (selects, toggles, buttons, navigation) whose actions can drive the
task goal, verified afterwards by scripts/verify_filter_specs.py which solves
each spec end-to-end through the reference interpreter and asserts every
criterion passes.

filter-011 is deliberately absent: multi-select row checkboxes with a computed
selected-count require row-scoped mutable state and aggregation, which UISpec
0.2 cannot express. Leaving it out keeps the coverage classifier's verdict on
that task honest instead of manufacturing a spec that trivially restates its
own criteria.
"""

import json
import pathlib

OUT = pathlib.Path("tasks/reference_specs")


def person(name, dept, start):
    return {"name": name, "department": dept, "startDate": start}


def spec_filter_001():
    employees = [
        person(n, d, s) for n, d, s in [
            ("Ava Chen", "Engineering", "2021-03-15"),
            ("Ben Ode", "Sales", "2020-07-01"),
            ("Carla Diaz", "Engineering", "2019-11-04"),
            ("Dan Wu", "Marketing", "2022-01-20"),
            ("Eli Roy", "Engineering", "2018-05-30"),
            ("Fay Kim", "Sales", "2023-02-14"),
            ("Gus Ali", "Sales", "2020-09-09"),
            ("Hana Lee", "Finance", "2021-12-01"),
            ("Ivan Petrov", "Marketing", "2019-06-18"),
            ("June Park", "Finance", "2022-08-08"),
            ("Kai Tan", "Sales", "2018-10-25"),
            ("Lena Braun", "Engineering", "2023-04-02"),
        ]
    ]
    return {
        "version": "0.2",
        "title": "Employee directory",
        "entry": "directory",
        "state": {
            "filter": {"type": "object", "default": {"department": "All"}},
            "sort": {"type": "object", "default": {"field": "", "direction": "asc"}},
        },
        "collections": {
            "employees": {
                "fields": {
                    "name": {"type": "string"},
                    "department": {"type": "string"},
                    "startDate": {"type": "string"},
                },
                "seed": employees,
            }
        },
        "screens": [{
            "id": "directory",
            "title": "Employees",
            "children": [
                {"kind": "heading", "id": "title", "label": "Employee directory"},
                {"kind": "select", "id": "deptFilter", "label": "Department",
                 "bind": "filter.department"},
                {"kind": "select", "id": "sortField", "label": "Sort by",
                 "bind": "sort.field"},
                {"kind": "select", "id": "sortDir", "label": "Direction",
                 "bind": "sort.direction"},
                {"kind": "list", "id": "employeeList", "of": "employees",
                 "rowLabel": "name",
                 "rowAction": {"op": "submit", "target": "picked"},
                 "filterWhen": {"op": "or", "clauses": [
                     {"op": "eq", "left": "$row.department", "right": "$state.filter.department"},
                     {"op": "eq", "left": "$state.filter.department", "right": "All"},
                 ]}},
            ],
        }],
    }


def country(name):
    return {"name": name}


def spec_filter_002():
    countries = [country(n) for n in [
        "Argentina", "Brazil", "Canada", "Denmark", "Egypt", "France",
        "Germany", "Hungary", "India", "Japan", "Kenya", "Portugal",
    ]]
    return {
        "version": "0.2",
        "title": "Country finder",
        "entry": "search",
        "state": {"query": {"type": "string", "default": ""}},
        "collections": {
            "countries": {"fields": {"name": {"type": "string"}}, "seed": countries}
        },
        "screens": [{
            "id": "search",
            "title": "Countries",
            "children": [
                {"kind": "heading", "id": "title", "label": "Countries"},
                {"kind": "field", "id": "searchBox", "label": "Search", "bind": "query"},
                {"kind": "list", "id": "countryList", "of": "countries",
                 "filterWhen": {"op": "matches", "left": "$row.name", "right": "$state.query"}},
            ],
        }],
    }


def order(oid, status):
    return {"id": oid, "status": status}


def spec_filter_003():
    orders = [order(f"ORD-{i:03d}", s) for i, s in enumerate([
        "Pending", "Shipped", "Cancelled", "Pending", "Shipped",
        "Shipped", "Pending", "Cancelled",
    ], start=1001)]
    return {
        "version": "0.2",
        "title": "Order tracker",
        "entry": "orders",
        "state": {"filter": {"type": "object", "default": {"status": "All"}}},
        "collections": {
            "orders": {"fields": {
                "id": {"type": "string"}, "status": {"type": "string"}},
                "seed": orders}
        },
        "screens": [{
            "id": "orders",
            "title": "Orders",
            "children": [
                {"kind": "heading", "id": "title", "label": "Orders"},
                {"kind": "select", "id": "statusFilter", "label": "Status",
                 "bind": "filter.status"},
                {"kind": "list", "id": "orderList", "of": "orders",
                 "rowLabel": "id",
                 "filterWhen": {"op": "or", "clauses": [
                     {"op": "eq", "left": "$row.status", "right": "$state.filter.status"},
                     {"op": "eq", "left": "$state.filter.status", "right": "All"},
                 ]}},
            ],
        }],
    }


def txn(tid, ttype, amount):
    return {"id": tid, "type": ttype, "amount": amount}


def spec_filter_004():
    txns = [txn(f"T{i:03d}", t, a) for i, (t, a) in enumerate([
        ("Debit", 120), ("Credit", 40), ("Debit", 60), ("Credit", 250),
        ("Debit", 300), ("Debit", 90), ("Credit", 130), ("Debit", 175),
        ("Credit", 80), ("Debit", 210), ("Credit", 500), ("Debit", 45),
        ("Credit", 95), ("Credit", 150), ("Credit", 60),
    ], start=1)]
    # Exactly four Debits at or above 100: T001, T005, T008, T010.
    return {
        "version": "0.2",
        "title": "Transactions",
        "entry": "ledger",
        "state": {
            "filter": {"type": "object", "default": {"type": "All", "minAmount": 0}},
        },
        "collections": {
            "transactions": {"fields": {
                "id": {"type": "string"}, "type": {"type": "string"},
                "amount": {"type": "number"}},
                "seed": txns}
        },
        "screens": [{
            "id": "ledger",
            "title": "Transactions",
            "children": [
                {"kind": "heading", "id": "title", "label": "Transactions"},
                {"kind": "select", "id": "typeFilter", "label": "Type",
                 "bind": "filter.type"},
                {"kind": "field", "id": "minAmount", "label": "Minimum amount",
                 "bind": "filter.minAmount"},
                {"kind": "list", "id": "txnList", "of": "transactions",
                 "rowLabel": "id",
                 "filterWhen": {"op": "and", "clauses": [
                     {"op": "or", "clauses": [
                         {"op": "eq", "left": "$row.type", "right": "$state.filter.type"},
                         {"op": "eq", "left": "$state.filter.type", "right": "All"},
                     ]},
                     {"op": "gte", "left": "$row.amount", "right": "$state.filter.minAmount"},
                 ]}},
            ],
        }],
    }


def book(title, author, year):
    return {"title": title, "author": author, "year": year}


def spec_filter_005():
    books = [book(t, a, y) for t, a, y in [
        ("Anchor", "R. Hale", 2011), ("Bridget", "M. Osei", 1998),
        ("Cypress", "T. Nara", 2020), ("Driftwood", "A. Kaur", 2005),
        ("Ember", "L. Moreau", 2015), ("Fathom", "J. Cole", 1987),
        ("Gale", "P. Novak", 2001), ("Harbor", "S. Ito", 1993),
    ]]
    return {
        "version": "0.2",
        "title": "Library",
        "entry": "shelf",
        "state": {
            "sort": {"type": "object", "default": {"field": "", "direction": "asc"}},
        },
        "collections": {
            "books": {"fields": {
                "title": {"type": "string"}, "author": {"type": "string"},
                "year": {"type": "number"}},
                "seed": books}
        },
        "screens": [{
            "id": "shelf",
            "title": "Books",
            "children": [
                {"kind": "heading", "id": "title", "label": "Library"},
                {"kind": "button", "id": "sortByTitle", "label": "Sort by title",
                 "action": [{"op": "set", "target": "sort.field", "value": "title"}]},
                {"kind": "button", "id": "toggleDesc", "label": "Descending",
                 "action": [{"op": "set", "target": "sort.direction", "value": "desc"}]},
                {"kind": "list", "id": "bookList", "of": "books", "rowLabel": "title"},
            ],
        }],
    }


def staff_member(name, dept):
    return {"name": name, "department": dept}


def spec_filter_006():
    staff = [staff_member(n, d) for n, d in [
        ("Ada", "Support"), ("Bo", "Eng"), ("Cy", "Support"), ("Dee", "Eng"),
        ("Elmo", "Design"), ("Fern", "Support"), ("Gil", "Eng"),
        ("Hal", "Design"), ("Ivy", "Support"), ("Jo", "Eng"),
    ]]
    return {
        "version": "0.2",
        "title": "Staff roster",
        "entry": "roster",
        "state": {
            "filter": {"type": "object", "default": {"department": "All"}},
            "sort": {"type": "object", "default": {"field": None}},
        },
        "collections": {
            "staff": {"fields": {
                "name": {"type": "string"}, "department": {"type": "string"}},
                "seed": staff}
        },
        "screens": [{
            "id": "roster",
            "title": "Staff",
            "children": [
                {"kind": "heading", "id": "title", "label": "Staff roster"},
                {"kind": "select", "id": "deptFilter", "label": "Department",
                 "bind": "filter.department"},
                {"kind": "button", "id": "clearAll", "label": "Clear all filters",
                 "action": [
                     {"op": "set", "target": "filter.department", "value": "All"},
                     {"op": "clear", "target": "sort.field"},
                 ]},
                {"kind": "list", "id": "staffList", "of": "staff", "rowLabel": "name",
                 "filterWhen": {"op": "or", "clauses": [
                     {"op": "eq", "left": "$row.department", "right": "$state.filter.department"},
                     {"op": "eq", "left": "$state.filter.department", "right": "All"},
                 ]}},
            ],
        }],
    }


def device(did, maker):
    return {"id": did, "manufacturer": maker}


def spec_filter_007():
    devices = [device(f"DVT-{i}", m) for i, m in enumerate([
        "Acme", "Bolt", "Acme", "Cirrus", "Bolt",
        "Cirrus", "Acme", "Bolt", "Cirrus", "Acme",
    ], start=1)]
    return {
        "version": "0.2",
        "title": "Device inventory",
        "entry": "inventory",
        "state": {"filter": {"type": "object", "default": {"manufacturer": "All"}}},
        "collections": {
            "devices": {"fields": {
                "id": {"type": "string"}, "manufacturer": {"type": "string"}},
                "seed": devices}
        },
        "screens": [{
            "id": "inventory",
            "title": "Devices",
            "children": [
                {"kind": "heading", "id": "title", "label": "Device inventory"},
                {"kind": "select", "id": "makerFilter", "label": "Manufacturer",
                 "bind": "filter.manufacturer"},
                {"kind": "banner", "id": "emptyNote", "tone": "empty",
                 "label": "No devices match this filter",
                 "visibleWhen": {"op": "eq", "left": "filter.manufacturer",
                                 "right": "Nonesuch"}},
                {"kind": "list", "id": "deviceList", "of": "devices",
                 "rowLabel": "id",
                 "filterWhen": {"op": "or", "clauses": [
                     {"op": "eq", "left": "$row.manufacturer", "right": "$state.filter.manufacturer"},
                     {"op": "eq", "left": "$state.filter.manufacturer", "right": "All"},
                 ]}},
            ],
        }],
    }


def record(rid, page):
    return {"id": rid, "_page": page}


def spec_filter_008():
    records = [record(f"REC-{i:03d}", (i // 8) + 1) for i in range(24)]
    return {
        "version": "0.2",
        "title": "Records",
        "entry": "table",
        "state": {"page": {"type": "number", "default": 1}},
        "collections": {
            "records": {"fields": {
                "id": {"type": "string"}, "_page": {"type": "number"}},
                "seed": records}
        },
        "screens": [{
            "id": "table",
            "title": "Records",
            "children": [
                {"kind": "heading", "id": "title", "label": "Records"},
                {"kind": "button", "id": "page1", "label": "Page 1",
                 "action": [{"op": "set", "target": "page", "value": 1}]},
                {"kind": "button", "id": "page2", "label": "Page 2",
                 "action": [{"op": "set", "target": "page", "value": 2}]},
                {"kind": "button", "id": "page3", "label": "Page 3",
                 "action": [{"op": "set", "target": "page", "value": 3}]},
                {"kind": "list", "id": "recordList", "of": "records",
                 "rowLabel": "id",
                 "filterWhen": {"op": "eq", "left": "$row._page", "right": "$state.page"}},
            ],
        }],
    }


def invoice(iid, status):
    return {"id": iid, "status": status}


def spec_filter_009():
    invoices = [invoice(f"INV-{i:03d}", s) for i, s in enumerate([
        "Overdue", "Paid", "Sent", "Overdue", "Paid",
        "Sent", "Overdue", "Paid", "Sent",
    ], start=501)]
    return {
        "version": "0.2",
        "title": "Invoices",
        "entry": "table",
        "state": {"filter": {"type": "object", "default": {"status": "All"}}},
        "collections": {
            "invoices": {"fields": {
                "id": {"type": "string"}, "status": {"type": "string"}},
                "seed": invoices}
        },
        "screens": [
            {
                "id": "table",
                "title": "Invoices",
                "children": [
                    {"kind": "heading", "id": "title", "label": "Invoices"},
                    {"kind": "select", "id": "statusFilter", "label": "Status",
                     "bind": "filter.status"},
                    {"kind": "list", "id": "invoiceList", "of": "invoices",
                     "rowLabel": "id",
                     "rowAction": {"op": "navigate", "target": "detail"},
                     "filterWhen": {"op": "or", "clauses": [
                         {"op": "eq", "left": "$row.status", "right": "$state.filter.status"},
                         {"op": "eq", "left": "$state.filter.status", "right": "All"},
                     ]}},
                ],
            },
            {
                "id": "detail",
                "title": "Invoice detail",
                "children": [
                    {"kind": "heading", "id": "detailTitle", "label": "Invoice"},
                    {"kind": "button", "id": "back", "label": "Back",
                     "action": [{"op": "navigate", "target": "table"}]},
                ],
            },
        ],
    }


def item(name, active):
    return {"name": name, "active": active}


def spec_filter_010():
    items = [item(n, a) for n, a in [
        ("Anvil", True), ("Barrel", False), ("Chisel", True), ("Dowel", True),
        ("Emery", False), ("File", True), ("Gauge", False), ("Hammer", True),
        ("Ingot", True),
    ]]
    return {
        "version": "0.2",
        "title": "Workshop items",
        "entry": "items",
        "state": {"hideInactive": {"type": "boolean", "default": False}},
        "collections": {
            "items": {"fields": {
                "name": {"type": "string"}, "active": {"type": "boolean"}},
                "seed": items}
        },
        "screens": [{
            "id": "items",
            "title": "Items",
            "children": [
                {"kind": "heading", "id": "title", "label": "Workshop items"},
                {"kind": "toggle", "id": "hideToggle", "label": "Hide inactive",
                 "bind": "hideInactive"},
                {"kind": "list", "id": "itemList", "of": "items", "rowLabel": "name",
                 "filterWhen": {"op": "or", "clauses": [
                     {"op": "falsy", "left": "$state.hideInactive"},
                     {"op": "eq", "left": "$row.active", "right": True},
                 ]}},
            ],
        }],
    }


def task_record(rid, page, status):
    return {"id": rid, "_page": page, "status": status}


def spec_filter_012():
    statuses = ["Active", "Done", "Active", "Done", "Active", "Done",
                "Active", "Done", "Active", "Done", "Active", "Done"]
    recs = [task_record(f"TSK-{i:03d}", (i // 4) + 1, s)
            for i, s in enumerate(statuses, start=1)]
    return {
        "version": "0.2",
        "title": "Tasks",
        "entry": "board",
        "state": {
            "page": {"type": "number", "default": 1},
            "filter": {"type": "object", "default": {"status": "All"}},
        },
        "collections": {
            "records": {"fields": {
                "id": {"type": "string"}, "_page": {"type": "number"},
                "status": {"type": "string"}},
                "seed": recs}
        },
        "screens": [{
            "id": "board",
            "title": "Task board",
            "children": [
                {"kind": "heading", "id": "title", "label": "Tasks"},
                {"kind": "select", "id": "statusFilter", "label": "Status",
                 "bind": "filter.status",
                 "action": [{"op": "set", "target": "page", "value": 1}]},
                {"kind": "button", "id": "nextPage", "label": "Next page",
                 "guardWhen": {"op": "lt", "left": "page", "right": 3},
                 "action": [{"op": "set", "target": "page", "value": 2}]},
                {"kind": "button", "id": "lastPage", "label": "Page 3",
                 "action": [{"op": "set", "target": "page", "value": 3}]},
                {"kind": "list", "id": "taskList", "of": "records",
                 "rowLabel": "id",
                 "filterWhen": {"op": "and", "clauses": [
                     {"op": "eq", "left": "$row._page", "right": "$state.page"},
                     {"op": "or", "clauses": [
                         {"op": "eq", "left": "$row.status", "right": "$state.filter.status"},
                         {"op": "eq", "left": "$state.filter.status", "right": "All"},
                     ]},
                 ]}},
            ],
        }],
    }


BUILDERS = {
    "filter-001": spec_filter_001,
    "filter-002": spec_filter_002,
    "filter-003": spec_filter_003,
    "filter-004": spec_filter_004,
    "filter-005": spec_filter_005,
    "filter-006": spec_filter_006,
    "filter-007": spec_filter_007,
    "filter-008": spec_filter_008,
    "filter-009": spec_filter_009,
    "filter-010": spec_filter_010,
    # filter-011 intentionally absent -- see module docstring.
    "filter-012": spec_filter_012,
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    orphan = OUT / "filterable-001.json"
    if orphan.exists():
        orphan.unlink()
        print(f"removed orphan {orphan.name}")
    for tid, build in BUILDERS.items():
        path = OUT / f"{tid}.json"
        path.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {path}")
