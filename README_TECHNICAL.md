# Stock Inventory Audit - Technical Documentation

Technical reference for the `stock_inventory_audit` module (Odoo 19).

## 1. Overview

The module restores the document-based inventory audit workflow of older
Odoo versions. An audit is a document made of a header and detail lines.
It goes through the states `draft -> in_progress -> validated`
(or `cancelled`) and, on validation, posts stock moves through the
standard Odoo stock engine so quants stay consistent.

* Technical name: `stock_inventory_audit`
* Odoo version: 19.0
* Dependencies: `stock`, `product`
* License: LGPL-3

## 2. File tree

```
stock_inventory_audit/
├── __init__.py                     # imports the models package
├── __manifest__.py                 # module metadata, dependencies, data files
├── README.rst                      # module summary and installation
├── README_TECHNICAL.md             # this file
├── README_FUNCTIONAL.md            # user guide
├── models/
│   ├── __init__.py                 # imports the three model files
│   ├── inventory_audit.py          # audit header: fields, start/validate/cancel
│   ├── inventory_audit_line.py     # audit lines: counting, difference, protection
│   └── stock_move.py               # extends stock.move with a link to the audit
├── security/
│   └── ir.model.access.csv         # access rights per group
└── views/
    └── inventory_audit_views.xml   # form, list, search, action, menu
```

Load order in `__manifest__.py`: security first, then views.

## 3. Data flow

```
 Draft                Start Inventory              Validate Inventory
   |                        |                              |
   |  user sets scope       |  search stock.quant          |  for each line with
   |  (warehouse,           |  matching the scope          |  difference != 0
   |  category, products,   |          |                   |          |
   |  locations)            |          v                   |          v
   |                        |  create one audit line       |  create stock.move
   |                        |  per quant:                  |  (gain or loss) with
   |                        |  theoretical_qty = quant qty |  inventory_audit_id
   |                        |  counted_qty     = quant qty |          |
   |                        |          |                   |          v
   |                        |          v                   |  move._action_done()
   |                        |  state = in_progress         |  -> quants updated
   |                        |                              |          |
   |                        |  staff edit counted_qty      |          v
   |                        |  difference is recomputed    |  state = validated
```

Stock direction on validation:

| Difference | Source location | Destination location |
|---|---|---|
| > 0 (gain) | virtual inventory loss location | audited location |
| < 0 (loss) | audited location | virtual inventory loss location |

The virtual location is read from `product.property_stock_inventory`
of the audited product, for the audit company.

## 4. Data model

### 4.1 `inventory.audit` (header)

| Field | Type | Description |
|---|---|---|
| `name` | Char, required | Reference or title of the audit |
| `audit_date` | Datetime, required | Date of the count; also used as date of the posted moves |
| `user_id` | Many2one `res.users` | Responsible user (default: current user) |
| `company_id` | Many2one `res.company`, required | Company (default: current company) |
| `state` | Selection | `draft`, `in_progress`, `validated`, `cancelled` |
| `scope_type` | Selection, required | `warehouse`, `category`, `product`, `location` |
| `warehouse_id` | Many2one `stock.warehouse` | Used when scope is `warehouse` |
| `category_id` | Many2one `product.category` | Used when scope is `category` |
| `product_ids` | Many2many `product.product` | Used when scope is `product` |
| `location_ids` | Many2many `stock.location` | Used when scope is `location` (internal only) |
| `line_ids` | One2many `inventory.audit.line` | Detail lines |

### 4.2 `inventory.audit.line` (detail)

| Field | Type | Description |
|---|---|---|
| `audit_id` | Many2one `inventory.audit`, required | Parent audit (`ondelete='cascade'`) |
| `state` | Selection, related | Status of the parent audit |
| `product_id` | Many2one `product.product`, required | Audited product variant |
| `location_id` | Many2one `stock.location`, required | Audited location |
| `lot_id` | Many2one `stock.lot` | Lot or serial number (domain: lots of the product) |
| `theoretical_qty` | Float, readonly | System quantity captured at start |
| `counted_qty` | Float | Real quantity entered by warehouse staff |
| `difference_qty` | Float, computed, stored | `counted_qty - theoretical_qty` |

### 4.3 `stock.move` (extension)

| Field | Type | Description |
|---|---|---|
| `inventory_audit_id` | Many2one `inventory.audit`, readonly, indexed | Audit that generated the move (traceability) |

## 5. Key logic

All the logic is in `models/inventory_audit.py` unless stated otherwise.

### 5.1 `_get_quant_domain()`
Builds the search domain on `stock.quant` from the scope:
internal locations, audit company, `quantity != 0`, plus one filter:
warehouse (`child_of` the warehouse view location), category
(`child_of`), specific products (`in`), or specific locations
(`child_of`). Raises a `UserError` if the selected scope is empty.

### 5.2 `action_start()`
Button "Start Inventory". Allowed only in `draft`. Searches the quants,
raises "No stock found for the selected scope." if there are none,
deletes existing lines, creates one line per quant
(`theoretical_qty` and `counted_qty` both set to the quant quantity),
then sets `state = in_progress`.

### 5.3 `action_validate()`
Button "Validate Inventory". Allowed only in `in_progress`. For each line:
skips it if the difference is zero (compared with the unit of measure
rounding); requires a lot on the line for tracked products; calls
`_create_stock_move(line)`. Finally sets `state = validated`. Everything
runs in one transaction: on error nothing is posted and the audit stays
`in_progress`.

### 5.4 `_create_stock_move(line)`
Creates a `stock.move` with a `move_line_ids` entry (quantity and lot),
`is_inventory=True`, `picked=True`, `origin` set to the audit name and
`inventory_audit_id` set to the audit. Calls `move._action_done()`,
which updates the quants, then aligns the move and move line dates on
`audit_date`.

### 5.5 `action_cancel()`
Button "Cancel Inventory". Refused on a validated audit. Otherwise sets
`state = cancelled`. No stock move is created.

### 5.6 State protection (`models/inventory_audit_line.py`)
`create`, `write` and `unlink` on lines raise a `UserError` when the
parent audit is `validated` or `cancelled`. Lines are created by
`action_start` while the audit is still `draft`, so this does not block
the snapshot.

### 5.7 Difference computation
`_compute_difference_qty` depends on `counted_qty` and
`theoretical_qty`. It is stored, so it can be searched and displayed
without recomputation.

## 6. Views (`views/inventory_audit_views.xml`)

* Form view: status bar with the three action buttons (each visible only
  in the proper state), header fields, scope group (only the field
  matching `scope_type` is shown), and the editable lines list. Only
  `counted_qty` is editable, and only when the audit is `in_progress`.
  Lines cannot be created or deleted by hand.
* List view: reference, date, scope, responsible, status badge.
* Search view: search by reference, filters by status, group by status.
* Action `inventory_audit_action` and menu "Inventory Audits" under the
  Inventory application (`stock.menu_stock_root`).

## 7. Security

File: `security/ir.model.access.csv`.

| Group | Model | Read | Write | Create | Delete |
|---|---|---|---|---|---|
| Inventory / User (`stock.group_stock_user`) | `inventory.audit` | yes | yes | yes | no |
| Inventory / Administrator (`stock.group_stock_manager`) | `inventory.audit` | yes | yes | yes | yes |
| Inventory / User | `inventory.audit.line` | yes | yes | yes | no |
| Inventory / Administrator | `inventory.audit.line` | yes | yes | yes | yes |

The state protection described in 5.6 applies to every group.

## 8. Installation and update

```
python odoo-bin --addons-path=<odoo addons>,<path to the module folder parent> \
    -d <database> -i stock_inventory_audit
```

After changing Python code or the database schema, restart Odoo with
`-u stock_inventory_audit`.

## 9. Customization

* Add a scope type: add a value to `scope_type`, a field for its
  selection, a branch in `_get_quant_domain()`, and a field in the form
  view with an `invisible` condition on `scope_type`.
* Start counting from zero: in `action_start`, set `'counted_qty': 0.0`
  instead of the quant quantity. Lines left untouched will then be
  posted as full losses, so use it only if staff count every line.
* Automatic reference: add an `ir.sequence` and assign it in `create`.
* Discussion and change tracking: inherit `mail.thread` on
  `inventory.audit` and add `tracking=True` on the fields to follow.
* Multi-company isolation: add an `ir.rule` on `inventory.audit` and
  `inventory.audit.line` based on `company_id`.

## 10. Known limitations

* The audit takes a snapshot at start; stock moves made afterwards on the
  audited products are not reflected in `theoretical_qty`.
* Only quants with a non-zero quantity are included in the snapshot.
* Products tracked by lot or serial number need the lot set on the line
  at validation time.