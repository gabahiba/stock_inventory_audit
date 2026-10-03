=====================
Stock Inventory Audit
=====================

Document-based inventory audit workflow for Odoo 19.

This module restores the structured inventory counting process of older
Odoo versions (such as Odoo 14): a manager creates an audit document,
starts it to freeze the current stock, warehouse staff enter the real
counted quantities, and the manager validates the document to post the
stock adjustments.

Key Features
============

* Audit document (header + lines) with a clear status flow:
  Draft -> In Progress -> Validated (or Cancelled).
* Flexible audit scope: a whole warehouse, a product category,
  specific products, or specific locations.
* "Start Inventory" locks the scope and takes a snapshot of the current
  on-hand quantities as audit lines (theoretical quantity).
* Warehouse staff enter the real counted quantity on each line;
  the difference (counted - theoretical) is computed automatically.
* "Validate Inventory" processes only the lines with a difference:

  * gain: stock is added from the virtual inventory loss location;
  * loss: stock is removed to the virtual inventory loss location.

* Every stock move keeps a link to the audit that created it.
* Lines cannot be added, modified or deleted once the audit is
  Validated or Cancelled.
* Access rights for Inventory Users and Inventory Managers.

Installation
============

1. Copy the ``stock_inventory_audit`` folder into a directory listed in
   the ``addons_path`` of your Odoo configuration.
2. Restart the Odoo server.
3. Activate the developer mode, open the Apps menu and click
   "Update Apps List".
4. Search for "Stock Inventory Audit" and click Install.

The module depends on the ``stock`` and ``product`` modules, which are
installed automatically.

Usage
=====

Open the Inventory application, then the "Inventory Audits" menu.
Create a new audit, choose its scope, click "Start Inventory", enter the
counted quantities, and click "Validate Inventory".

Documentation
=============

* ``README_TECHNICAL.md``: architecture, data model, logic and security.
* ``README_FUNCTIONAL.md``: user guide, use cases, FAQ and troubleshooting.

License
=======

LGPL-3