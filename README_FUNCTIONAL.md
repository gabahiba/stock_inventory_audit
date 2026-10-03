# Stock Inventory Audit - User Guide

Operational guide for warehouse staff, warehouse managers and accountants.

## 1. What this feature does

An inventory audit is a document used to check the real quantities in
the warehouse against the quantities recorded in Odoo. The manager
creates and starts the audit, warehouse staff enter what they count on
the shelves, and the manager validates the document. On validation,
Odoo adjusts the stock automatically to match the physical reality.

## 2. Where to find it

Open the **Inventory** application, then click **Inventory Audits** in
the top menu.

## 3. The life of an audit

| Status | Meaning | Who does what |
|---|---|---|
| Draft | The audit is being prepared | The manager sets the title, the date and the scope |
| In Progress | The stock is frozen as a snapshot and the count is running | Warehouse staff enter the counted quantities |
| Validated | Stock adjustments are posted; the document is locked | The manager validated the audit |
| Cancelled | The audit was abandoned; no stock was changed | The manager cancelled the audit |

### Step by step

1. **Create the audit.** Click **New**, enter a title (for example
   "Year-End Stock Audit 2026") and check the audit date.
2. **Choose the scope** (see section 4).
3. **Click Start Inventory.** The system takes a snapshot of the current
   stock and creates one line per product and location. The scope can no
   longer be changed.
4. **Count.** Walk through the warehouse and enter the real quantity in
   the **Counted Quantity** column of each line.
5. **Review.** Check the **Difference** column: green lines are gains,
   red lines are losses.
6. **Click Validate Inventory** and confirm. The stock is adjusted and
   the audit becomes Validated.

## 4. Scope options

The field **Audit Scope** decides which products and locations are
included when you click Start Inventory. Only the field matching the
chosen scope is shown.

| Scope | What you select | What is included |
|---|---|---|
| Warehouse | A warehouse | All products in that warehouse and its sub-locations |
| Product Category | A category | All products of that category and its sub-categories |
| Specific Products | One or more products | Only those products, in all internal locations |
| Specific Locations | One or more locations | All products in those locations and their sub-locations |

Only internal locations are audited. Products with a zero quantity are
not included in the snapshot.

## 5. Columns of the audit lines

| Column | Description | Editable |
|---|---|---|
| Product | The product variant being audited | No |
| Location | The storage location being audited | No |
| Lot/Serial Number | Lot or serial number, for tracked products | No |
| Theoretical Quantity | Quantity recorded in Odoo when the audit was started | No |
| Counted Quantity | Real quantity counted on the shelf | Yes, only while the audit is In Progress |
| Difference | Counted Quantity minus Theoretical Quantity: positive = gain, negative = loss | No (automatic) |

The Counted Quantity is pre-filled with the theoretical quantity. You
only need to change the lines where the count is different.

## 6. Search and filters

In the audit list:

* Search by **Reference** (the title of the audit).
* Filters: **Draft**, **In Progress**, **Validated**.
* Group by: **Status**.

The list shows a colored status badge on each audit.

## 7. What happens on validation

Only the lines with a difference are processed. Lines where the counted
quantity equals the theoretical quantity create no stock move.

* **Gain** (counted > theoretical): the stock is added to the audited
  location, coming from the virtual inventory adjustment location.
* **Loss** (counted < theoretical): the stock is removed from the audited
  location, going to the virtual inventory adjustment location.

Every stock move keeps the title of the audit as its origin and a direct
link to the audit. To review them, open **Reporting** and the stock
moves history, and search for the audit title. The available stock of
each product is updated immediately.

Once the audit is Validated or Cancelled, its lines cannot be added,
modified or deleted.

## 8. Roles

| Role | Can do |
|---|---|
| Inventory / User (warehouse staff) | Create and edit audits, enter counted quantities. Cannot delete audits |
| Inventory / Administrator (manager) | Everything, including deleting audits |

## 9. Common use cases

**Year-end full count.** Scope: Warehouse. Start the audit, split the
lines among the teams, validate when every line is counted.

**Counting one shelf or aisle.** Scope: Specific Locations, select the
location. Only the products stored there are listed.

**Checking one product family.** Scope: Product Category.

**Investigating a suspicious product.** Scope: Specific Products, select
the product to check its quantity in every internal location.

**Abandoning a count.** Click Cancel Inventory before validation. No
stock is changed.

## 10. FAQ

**Can I change the scope after starting the audit?**
No. The scope is locked when the audit is started. Cancel the audit and
create a new one.

**What if the stock moves while the team is counting?**
The theoretical quantity is a snapshot taken at the start. Moves made
after that are not reflected in it, so try to avoid stock movements on
the audited items during the count.

**Can I cancel a validated audit?**
No. The stock has already been adjusted. Create a new audit to correct
a mistake.

**Can I restart a cancelled audit?**
No. Create a new audit.

**What if I do not change a Counted Quantity?**
The line keeps a difference of zero and no stock move is created for it.

**Where do the gains and losses come from?**
From the virtual inventory adjustment location, as in the standard
Odoo inventory adjustments.

## 11. Troubleshooting

| Message or problem | Cause | Solution |
|---|---|---|
| "No stock found for the selected scope." | No product with a non-zero quantity matches the scope | Check the scope, or check that the stock exists in an internal location |
| "Please select a warehouse." (or category, products, locations) | The chosen scope has no value selected | Fill in the field shown under Scope |
| "Only a draft audit can be started." | The audit was already started, validated or cancelled | Create a new audit |
| "Only an audit in progress can be validated." | The audit is still in Draft, or already Validated | Start the audit first |
| "A validated audit cannot be cancelled." | The stock was already adjusted | Create a new audit for the correction |
| "You cannot add or modify lines of a validated or cancelled audit." | The audit is locked | Create a new audit |
| "Please set a Lot/Serial Number on the line of ..." | A tracked product has a difference but no lot on its line | Cancel the audit, fix the lot on the stock record of the product, and create a new audit |
| Counted Quantity cannot be edited | The audit is not In Progress | Click Start Inventory first |
| The Inventory Audits menu is not visible | The user has no Inventory access right | Ask an administrator to give the Inventory User or Administrator role |
| The product quantity did not change after validation | The line had no difference | Check the Difference column in the audit |