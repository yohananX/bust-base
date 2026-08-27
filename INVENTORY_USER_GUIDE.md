# Inventory & Fee Management System — User Guide

## Table of Contents

1. [Overview](#overview)
2. [Field Definitions & Terminology](#field-definitions--terminology)
3. [Accessing the Inventory Module](#accessing-the-inventory-module)
4. [Inventory Item Management](#inventory-item-management)
   - [Adding a New Item](#adding-a-new-item)
   - [Editing an Existing Item](#editing-an-existing-item)
   - [Deactivating an Item](#deactivating-an-item)
   - [Filtering and Searching](#filtering-and-searching)
5. [Stock Tracking](#stock-tracking)
   - [Understanding Stock Levels](#understanding-stock-levels)
   - [Recording Procurement](#recording-procurement)
   - [Recording Stock Removal](#recording-stock-removal)
   - [Viewing Transactions](#viewing-transactions)
   - [Low Stock Alerts](#low-stock-alerts)
6. [Fee Category Integration](#fee-category-integration)
   - [Linking Items to Fee Categories](#linking-items-to-fee-categories)
   - [How Students See Items](#how-students-see-items)
7. [Payment Recording](#payment-recording)
   - [Recording Invoice Payments](#recording-invoice-payments)
   - [Recording Book Purchases](#recording-book-purchases)
   - [Recording Miscellaneous Payments](#recording-miscellaneous-payments)
8. [Student Book Catalog (Phase 3)](#student-book-catalog-phase-3)
9. [Best Practices](#best-practices)
10. [FAQ](#faq)

---

## Overview

The Inventory & Fee Management module helps schools track physical assets (books, notebooks, uniforms, equipment) and manage payments in one place. It is divided into two main parts:

- **Inventory Management**: Track items, record stock movements, and maintain an audit trail.
- **Fee & Payment Management**: Record payments for tuition, books, and other fees with full context.

### Important Rules

1. **Book purchases never create debt.** Book purchases use standalone payments with `invoice=None`. They do not appear in invoice balances or outstanding fees calculations.
2. **Stock is deducted only on confirmed payment.** If a payment fails or is refunded, stock is restored automatically.
3. **Items are hidden from students unless assigned to their class.** An item without a `school_class` is admin-only.
4. **No term binding on items.** Books are not tied to specific academic terms. They span terms until stock runs out.
5. **All monetary values use Naira (₦) with 2 decimal places.** No floating-point math is used.

---

## Field Definitions & Terminology

Use this section as a reference when filling out forms or reading reports. Every term is explained in the context of this application.

### Inventory Item Fields

| Field | What it means | What our application does with it |
|-------|---------------|----------------------------------|
| **Name** | The display name of the item, e.g., "Mathematics Textbook" or "Blue Pen". | Used everywhere: item lists, student catalogs, receipts, transaction logs. Must be unique within a class. |
| **Category** | The type of item: Book/Textbook, Notebook/Lesson Note, Pen/Pencil/Writing Material, Uniform, Equipment, or Other. | Filters the item list, groups items in the student catalog, and helps with reporting. |
| **School Class** | The class this item is assigned to, e.g., JSS1A. Leave blank for admin-only or teacher-use items. | Determines which students can see and buy the item. Items without a class are admin-only and never appear in student catalogs. Useful for general supplies like pens, computers, or lesson notes distributed by teachers. |
| **SKU** | Stock Keeping Unit — a short code you create to identify the item, e.g., `MTB-JSS1` for Mathematics Textbook JSS1. | Used for quick reference, searching, and import/export. Optional but recommended for bulk operations. |
| **Unit** | The measurement unit for the item, e.g., "piece", "pack", "box". | Displayed on receipts and procurement forms. Defaults to "piece". |
| **Total Stock** | The total quantity of this item currently on hand. | Updated automatically when you record procurement, sales, refunds, or adjustments. Never edit this directly. |
| **Available Stock** | The quantity available for new purchases. Calculated as `total_stock - reserved`. | Shown in the item list and student catalog. If this reaches 0, students cannot buy the item. |
| **Min Stock Threshold** | The minimum stock level before the system flags the item as low. | When `available_stock` falls to or below this number, the item appears on the Low Stock page and gets a red `(LOW)` badge. |
| **Unit Price (₦)** | The selling price per single unit in Naira. | Used to calculate totals on receipts and in the student catalog. |
| **Initial Stock** | The starting quantity when you first create the item. | Only used on creation. Sets the initial `total_stock` and creates a `PROCUREMENT` transaction automatically. |

### Stock & Movement Terms

| Term | What it means | What our application does with it |
|------|---------------|----------------------------------|
| **Procurement** | The act of receiving new stock from a supplier or donor. | Increases `total_stock` atomically and creates an immutable `PROCUREMENT` transaction. |
| **Transaction** | An immutable record of a stock movement. | Every change to stock is logged here: what changed, when, by whom, and the resulting balance. Used for audit trails. |
| **Transaction Type** | The kind of movement: `PROCUREMENT`, `SALE`, `REFUND`, or `ADJUSTMENT`. | Determines how the quantity change is interpreted and displayed. |
| **Quantity Change** | The amount added or removed in this transaction. Positive for additions, negative for deductions. | Added to `total_stock` to produce the new `balance_after`. |
| **Balance After** | The stock level immediately after this transaction. | Stored for historical accuracy. Even if `total_stock` changes later, this record remains correct for that point in time. |
| **Reference** | A link to another record, e.g., `payment:123` or `refund:456`. | Lets you trace a stock change back to its source: which payment caused it, or which refund restored it. |
| **Created By** | The admin user who recorded this transaction. | Provides accountability. System actions show as "System" or the user who triggered the flow. |
| **Notes** | Free-text context for the transaction. | Used for explanations like "Damaged in transit" or "Bulk order for First Term". |

### Payment & Fee Terms

| Term | What it means | What our application does with it |
|------|---------------|----------------------------------|
| **Fee Category** | A grouping for fees, e.g., "Tuition", "Books", "Sports". | Used to organize invoices, pricing, and inventory items. Does NOT automatically charge students. |
| **Invoice** | A bill for fees, tied to a specific student and term. | Shows what a student owes. Balance is computed from confirmed payments only. Book purchases do NOT create invoices. |
| **Invoice Line Item** | A single fee on an invoice, e.g., "Tuition: ₦50,000" or "Sports Fee: ₦10,000". | Itemizes the invoice total. Receipts display these as line items. |
| **Payment** | A confirmed financial transaction. | Can be linked to an invoice (tuition/fees) or stand alone (book purchases, miscellaneous). Status must be `CONFIRMED` to count toward balances or deduct stock. |
| **Payment Method** | How the payment was made: Cash, Bank Transfer, Paystack, POS, etc. | Recorded on the receipt and in the audit log. |
| **Reference** | A unique identifier for the payment, often from Paystack or a bank. | Used to prevent duplicate processing and to trace payments. |
| **Book Purchase** | A record linking a payment to the specific items a student bought. | Created when a student buys books. Used to deduct stock and itemize receipts. Each line item gets its own `BookPurchase` record. |
| **Receipt** | A document proving payment, issued lazily when viewed. | Shows the school header, amount paid, and an itemized list of what was purchased (fees, books, or other). |

### System Terms

| Term | What it means | What our application does with it |
|------|---------------|----------------------------------|
| **Tenant** | A school. All data is scoped to a school. | Every query filters by `school`. You only see data for your own school. |
| **Admin** | A user with the `ADMIN` role. | Can access all inventory and fee management features. |
| **Student** | A user with the `STUDENT` role and a student profile. | Can view their own book catalog and payment history (Phase 3). |
| **Parent** | A user with the `PARENT` role linked to one or more students. | Can view their children's book catalogs and payment history (Phase 3). |
| **School Class** | A stable class entity, e.g., JSS1A, independent of academic year. | Used to group students and items. Determines which inventory items a student can see. |
| **Low Stock** | When `available_stock <= min_stock_threshold`. | Triggers the Low Stock alert page and red badges in the item list. |
| **Soft Delete** | Marking a record as inactive instead of deleting it. | Deactivated items disappear from catalogs but remain in transaction history for audit integrity. |

---

## Accessing the Inventory Module

1. Log in to the **School Admin** portal.
2. Look for the **Inventory** section in the sidebar.
3. The section contains four pages:

| Page | URL | Purpose |
|------|-----|---------|
| Items | `/school-admin/inventory/items/` | List, create, edit, and deactivate items |
| Procurement | `/school-admin/inventory/procurement/` | Record stock arrivals |
| Stock Removal | `/school-admin/inventory/stock-removal/` | Record stock withdrawals, damage, or loss |
| Transactions | `/school-admin/inventory/transactions/` | Full audit log |
| Low Stock | `/school-admin/inventory/low-stock/` | Items below threshold |

---

## Inventory Item Management

### Adding a New Item

**Example 1:** Add "Mathematics Textbook" for JSS1A.

1. Go to **Inventory → Items**.
2. Click **Add Item**.
3. Fill in the form:

| Field | Value | Required? |
|-------|-------|-----------|
| Name | Mathematics Textbook | Yes |
| Category | Book / Textbook | Yes |
| School Class | JSS1A | No (optional) |
| SKU | MTB-JSS1 | No |
| Unit | piece | Yes |
| Unit Price (₦) | 2500.00 | Yes |
| Min Stock Threshold | 5 | Yes |
| Initial Stock | 50 | No (only on creation) |

4. Click **Create Item**.

**Example 2:** Add "Blue Pen" for general teacher use (no class).

1. Go to **Inventory → Items**.
2. Click **Add Item**.
3. Fill in the form:

| Field | Value | Required? |
|-------|-------|-----------|
| Name | Blue Pen | Yes |
| Category | Pen / Pencil / Writing Material | Yes |
| School Class | — No class (admin/teacher use only) — | No (leave blank) |
| SKU | PEN-BLUE | No |
| Unit | piece | Yes |
| Unit Price (₦) | 200.00 | Yes |
| Min Stock Threshold | 50 | Yes |
| Initial Stock | 200 | No (only on creation) |

4. Click **Create Item**.

**What happens behind the scenes:**
- The item is created and linked to your school.
- If you selected a class, the item is visible to students in that class.
- If you left class blank, the item is admin-only and never appears in student catalogs.
- If you entered an initial stock > 0, a `PROCUREMENT` transaction is logged automatically.
- The item is now visible to students in JSS1A in their book catalog.

### Editing an Existing Item

1. Go to **Inventory → Items**.
2. Find the item in the list.
3. Click the **Edit** (pencil) icon.
4. Update the fields you need. You can change:
   - Name
   - Category
   - School Class
   - SKU
   - Unit
   - Unit Price
   - Min Stock Threshold
5. Click **Update Item**.

**Note:** You cannot edit `total_stock` directly from the item form. To add or remove stock, use the **Procurement** page.

### Deactivating an Item

1. Go to **Inventory → Items**.
2. Find the item.
3. Click the **Deactivate** (trash) icon.
4. Confirm the action.

**What happens:**
- The item is marked `is_active=False`.
- It disappears from the student book catalog.
- All historical transactions and procurement records remain intact.
- You cannot permanently delete items to preserve audit history.

### Filtering and Searching

The Items page supports:

| Filter | Purpose |
|--------|---------|
| Search | Search by item name or SKU |
| Category | Filter by type: Book, Notebook, Writing, Uniform, Equipment, Other |
| School Class | Filter by class |
| Stock Status | Show only Low Stock or Out of Stock items |

Click **Filter** to apply, or **Clear** to reset.

---

## Stock Tracking

### Understanding Stock Levels

Every item shows two numbers:

| Column | Meaning |
|--------|---------|
| **Stock** | `available_stock` — what students can still purchase |
| **Min Stock Threshold** | The reorder point |

If `available_stock <= min_stock_threshold`, the stock number turns red with a `(LOW)` badge.

**Example:**
- Total Stock: 10
- Min Threshold: 5
- Available: 10 (no reservations)
- If 3 students reserve 2 books each during checkout, `available_stock` effectively becomes 4.

### Recording Procurement

Use Procurement to add stock when you receive new deliveries.

**Example:** Restock Mathematics Textbook with 100 new units.

1. Go to **Inventory → Procurement**.
2. Select the item: "Mathematics Textbook".
3. Enter quantity: `100`.
4. Enter unit cost (₦): `2000.00`.
5. Select procurement date: today's date.
6. Optional: Enter supplier name, reference number, and notes.
7. Click **Record Procurement**.

**What happens:**
- `total_stock` increases by 100 atomically.
- A `PROCUREMENT` transaction is logged.
- A procurement record is created for future reference.

### Recording Stock Removal

Use Stock Removal to log when items leave inventory without a sale. Common reasons: damaged goods, lost items, teacher distribution, or office use.

**Example:** 10 Blue Pens were distributed to teachers. Record the removal.

1. Go to **Inventory → Stock Removal**.
2. Select the item: "Blue Pen".
3. Enter quantity to remove: `10`.
4. Select reason: **Teacher Distribution**.
5. Enter notes: "Distributed to JSS1 teachers on 15 Oct".
6. Click **Record Removal**.

**What happens:**
- `total_stock` decreases by 10 atomically.
- An `ADJUSTMENT` transaction is logged with the reason and notes.
- The transaction cannot be edited or deleted. If you make a mistake, record another adjustment with an explanation.

**Important:** You cannot remove more stock than is currently available. The system will show an error if you try.

### Viewing Transactions

1. Go to **Inventory → Transactions**.
2. Use filters to narrow down:
   - **Item**: Show transactions for a specific item.
   - **Type**: Filter by PROCUREMENT, SALE, REFUND, or ADJUSTMENT.

The table shows:

| Column | Meaning |
|--------|---------|
| Date | When the transaction occurred |
| Item | The inventory item |
| Type | Procurement / Sale / Refund / Adjustment |
| Change | Quantity change (+ or -) |
| Balance | Stock level after the change |
| Reference | Linked payment ID, refund ID, or note |
| Created By | Admin user or system |

**Transaction Types Explained:**

| Type | When It Happens | Quantity Change |
|------|----------------|-----------------|
| **PROCUREMENT** | Admin records new stock arrival | +positive |
| **SALE** | Student buys items and payment is confirmed | -positive |
| **REFUND** | Payment is refunded, stock is returned | +positive |
| **ADJUSTMENT** | Admin corrects stock manually (damaged, lost, etc.) | -positive or +positive |

### Low Stock Alerts

1. Go to **Inventory → Low Stock**.
2. This page shows all items where `available_stock <= min_stock_threshold`.
3. Click **Add Stock** next to any item to quickly record procurement.

**Best practice:** Check Low Stock at least weekly, or set up a scheduled report.

---

## Fee Category Integration

### Linking Items to Fee Categories

You can organize inventory items under fee categories for reporting and display purposes. This does **not** create automatic billing.

**Example:** Link "Mathematics Textbook" and "English Textbook" to the "Books" fee category.

1. Go to **Fees → Categories** in the admin portal.
2. Click **Edit** on the "Books" category.
3. Scroll to **Attached inventory items**.
4. Click **Add item** and select "Mathematics Textbook".
5. Click **Add item** again and select "English Textbook".
6. Click **Update Category**.

**What this does:**
- Creates a `FeeCategoryInventoryItem` link.
- Allows the student book catalog to group items by category.
- Does NOT create invoices or charge students automatically.

### How Students See Items

In Phase 3, students will see items in their book catalog grouped by fee category. For example:

```
Books for JSS1A
├── Books
│   ├── Mathematics Textbook — ₦2,500.00
│   ├── English Textbook — ₦3,000.00
│   └── Science Workbook — ₦1,500.00
└── Notebooks
    └── Exercise Book — ₦500.00
```

Only items assigned to the student's current class are visible.

---

## Payment Recording

### Recording Invoice Payments

Use this for tuition and other fee payments that are linked to an existing invoice.

1. Go to the **Student Detail** page.
2. Find the student's outstanding invoice.
3. Click **Record Payment**.
4. Fill in:
   - Payment type: **Invoice**
   - Student: [pre-filled]
   - Invoice: Select the invoice
   - Amount: Enter payment amount
   - Method: Cash, Bank Transfer, Paystack, etc.
5. Click **Record Payment**.

**What happens:**
- Payment is created with `status=CONFIRMED`.
- Invoice balance is reduced automatically.
- Receipt is issued lazily when viewed.

### Recording Book Purchases

Use this when a student buys books or other inventory items in person (e.g., at the school shop).

**Example:** Student buys 2 Mathematics Textbooks and 1 English Textbook.

1. Go to **Fees → Manual Payment** (or Student Detail → Record Payment).
2. Fill in:
   - Payment type: **Book Purchase**
   - Student: Select the student
   - Item: Mathematics Textbook
   - Quantity: 2
   - Method: Cash / Paystack / etc.
3. Click **Add Item** to add more books:
   - Item: English Textbook
   - Quantity: 1
4. Review the total amount.
5. Click **Record Payment**.

**What happens:**
- A `Payment` is created with `invoice=None` (no debt created).
- `BookPurchase` records are created for each item.
- Stock is deducted immediately for each item.
- A `SALE` transaction is logged for each item.
- A receipt is issued with itemized books.

**Critical:** If stock is insufficient at the time of recording, the payment is rejected with an error message.

### Recording Miscellaneous Payments

Use this for one-off payments not tied to invoices or books (e.g., event fees, donations).

1. Go to **Fees → Manual Payment**.
2. Fill in:
   - Payment type: **Miscellaneous**
   - Student: Select the student
   - Description: e.g., "Science Fair Fee"
   - Amount: Enter amount
   - Method: Select payment method
3. Click **Record Payment**.

**What happens:**
- A `Payment` is created with `invoice=None`.
- No stock is affected.
- Receipt shows the description as the line item.

---

## Student Book Catalog (Phase 3)

> **Note:** This feature is not yet available in Phase 1. It will be implemented in Phase 3.

### Planned Functionality

- Students and parents browse items assigned to their class.
- Add items to cart and pay via Paystack.
- Stock is deducted automatically on payment confirmation.
- Partial purchases are allowed (buy 2 of 3 books) without creating debt.
- Receipts show exactly which books were purchased.

### How It Will Work

1. Student logs in → goes to **Pay Fees** or **Books**.
2. Sees items for their current class only.
3. Selects items and quantities.
4. Proceeds to Paystack checkout.
5. On confirmation: stock deducted, receipt itemized.
6. On refund: stock restored automatically.

---

## Best Practices

### 1. Naming Conventions

- Use consistent, descriptive names: "Mathematics Textbook" not "Math Book".
- Include class level in the name only if the same book is used across multiple classes with different editions.
- Use SKUs for easy reference: `MTB-JSS1` = Mathematics Textbook, JSS1.

### 2. Stock Thresholds

- Set `min_stock_threshold` based on consumption rate.
- For fast-moving items (pens, notebooks), set a higher threshold (e.g., 50).
- For slow-moving items (textbooks), set a lower threshold (e.g., 5).
- Review thresholds every term and adjust based on actual sales.

### 3. Procurement Records

- Always fill in `supplier_name` and `reference` for external purchases.
- Use the `notes` field for context: "Bulk order for First Term", "Emergency restock", etc.
- Record procurement on the day stock arrives, not later.

### 4. Class Assignments

- Assign every item to a class if students should see it.
- Leave `school_class` blank only for admin-only items (e.g., office supplies).
- When a student changes class, they automatically see items for their new class.

### 5. Payment Recording

- Always verify stock before recording a book purchase manually.
- Use descriptive `description` fields for miscellaneous payments.
- For cash payments, ensure the `recorded_by` admin is logged in so the audit trail is accurate.

### 6. Audit Trail

- Never edit or delete `InventoryTransaction` records. They are append-only.
- If a correction is needed, create a new `ADJUSTMENT` transaction with a note explaining the correction.
- Review the Transactions page regularly for anomalies.

### 7. Cross-School Data

- Each school's inventory is completely isolated.
- You cannot link an item from School A to a fee category in School B.
- If you manage multiple schools, switch context before recording transactions.

---

## FAQ

**Q: Can a student buy books from a different class?**
A: No. The book catalog only shows items assigned to the student's current class.

**Q: What happens if stock runs out during checkout?**
A: If stock is sufficient at checkout but insufficient at payment confirmation (e.g., another student bought the last item), the payment is marked as FAILED and the student is notified. Paystack will refund the payment.

**Q: Can I edit the stock level directly?**
A: No. Stock can only be changed through Procurement (add) or Sales/Refunds/Adjustments (deduct/restore). This ensures every change is logged.

**Q: What if I need to correct a transaction?**
A: Create a new `ADJUSTMENT` transaction with a note explaining the correction. Do not edit or delete existing transactions.

**Q: Do book purchases affect a student's outstanding fees?**
A: No. Book purchases use standalone payments with `invoice=None`. They never appear in invoice balances or outstanding fees calculations.

**Q: Can I link one item to multiple fee categories?**
A: Yes. An item can be linked to as many fee categories as needed.

**Q: Can I import items in bulk?**
A: Yes. Use the **Import** feature under **System → Import** in Phase 6.

**Q: What happens when a payment is refunded?**
A: Stock is automatically restored, a `REFUND` transaction is logged, and the admin is notified.

**Q: Can a parent buy books for their child?**
A: Yes. In Phase 3, parents will be able to purchase books for any linked child.

**Q: Do all items need to be assigned to a class?**
A: No. Leave the School Class blank for items that are for admin or teacher use only, such as pens, computers, or lesson notes. These items are hidden from students and can only be managed by admins.

**Q: How do I record stock that was given to teachers or lost?**
A: Use **Inventory → Stock Removal**. Select the item, enter the quantity, choose a reason (Damaged, Lost, Teacher Distribution, etc.), and add notes. This creates an ADJUSTMENT transaction and reduces stock.

**Q: Can I undo a stock removal?**
A: You cannot delete transactions. If you made a mistake, record another adjustment with the opposite quantity and explain the correction in the notes. For example, if you accidentally removed 5 pens, record a new adjustment adding 5 pens with note "Correction: accidental removal on 15 Oct".

**Q: What is the difference between Procurement and Stock Removal?**
A: Procurement adds stock (e.g., new delivery from supplier). Stock Removal deducts stock for non-sale reasons (e.g., damage, teacher distribution, loss). Both create immutable transactions.

**Q: Are items without a class included in the student book catalog?**
A: No. Only items assigned to a student's current class appear in the catalog. Items without a class are admin-only.

**Q: Are inventory items visible to teachers?**
A: No. Only admins can access the inventory management module.

**Q: What is a SKU and do I need one?**
A: SKU stands for Stock Keeping Unit. It is an optional short code you create to identify items quickly. It is useful for searching and bulk imports but not required.

**Q: What is the difference between Total Stock and Available Stock?**
A: Total Stock is the physical count on hand. Available Stock is what is left for new purchases after accounting for any reservations. In Phase 1, reservations are not exposed to students, but the field exists for future cart locking.

**Q: What happens if I deactivate an item that has transaction history?**
A: The item is hidden from all lists and student catalogs, but all historical transactions and procurement records remain intact. You cannot permanently delete items to preserve audit history.

**Q: Can I change the unit price after creating an item?**
A: Yes. Edit the item and update the Unit Price. This changes the selling price going forward. Past transactions retain the price at the time of sale.

**Q: What is the Min Stock Threshold?**
A: It is the reorder point. When Available Stock falls to or below this number, the system flags the item as low stock so you can reorder. Set it based on how quickly the item sells.

---

## Glossary

| Term | Definition |
|------|------------|
| **Tenant** | A school. All data is scoped to a school. |
| **SKU** | Stock Keeping Unit — a short code you assign to identify an item quickly. Used for searching and bulk import/export. |
| **Unit** | The measurement unit for an item, e.g., "piece", "pack", "box". Displayed on receipts and procurement forms. |
| **Total Stock** | The total physical quantity of an item currently on hand. Updated only through procurement, sales, refunds, and adjustments. |
| **Available Stock** | The quantity available for new purchases. Calculated as `total_stock - reserved`. Shown in item lists and student catalogs. |
| **Min Stock Threshold** | The minimum stock level before the system flags an item as low. When `available_stock` reaches this number, the item appears on the Low Stock page. |
| **Procurement** | The act of receiving new stock. Increases `total_stock` and creates a `PROCUREMENT` transaction. |
| **Transaction** | An immutable record of a stock movement. Every addition or deduction is logged with type, quantity, balance, reference, and creator. |
| **Transaction Type** | The kind of movement: `PROCUREMENT` (add), `SALE` (deduct), `REFUND` (restore), or `ADJUSTMENT` (manual correction). |
| **Quantity Change** | The amount added or removed in a transaction. Positive for additions, negative for deductions. |
| **Balance After** | The stock level immediately after a transaction. Stored for historical accuracy. |
| **Reference** | A link to another record, e.g., `payment:123` or `refund:456`. Lets you trace a stock change back to its source. |
| **Created By** | The admin user or system action that recorded the transaction. Provides accountability. |
| **Notes** | Free-text context for a transaction, e.g., "Damaged in transit" or "Bulk order for First Term". |
| **Fee Category** | A grouping for fees, e.g., "Tuition", "Books", "Sports". Used to organize invoices and inventory items. Does NOT automatically charge students. |
| **FeeCategoryInventoryItem** | A link between a FeeCategory and an InventoryItem. Organizational only — does not create invoices or charges. |
| **Invoice** | A bill for fees tied to a specific student and term. Balance is computed from confirmed payments only. Book purchases do NOT create invoices. |
| **Invoice Line Item** | A single fee on an invoice, e.g., "Tuition: ₦50,000". Itemizes the invoice total and appears on receipts. |
| **Payment** | A confirmed financial transaction. Can be linked to an invoice (tuition/fees) or stand alone (book purchases, miscellaneous). |
| **Payment Method** | How the payment was made: Cash, Bank Transfer, Paystack, POS, etc. Recorded on receipts and in audit logs. |
| **BookPurchase** | A record linking a payment to the specific items a student bought. Created on purchase, used to deduct stock and itemize receipts. |
| **Receipt** | A document proving payment. Issued lazily when viewed. Shows school header, amount paid, and itemized list of what was purchased. |
| **Low Stock** | A status when `available_stock <= min_stock_threshold`. Triggers alerts and red badges in the UI. |
| **Soft Delete** | Marking a record as inactive instead of deleting it. Deactivated items disappear from catalogs but remain in transaction history. |

---

## Support

For technical issues or feature requests, contact the system administrator or refer to the project documentation.
