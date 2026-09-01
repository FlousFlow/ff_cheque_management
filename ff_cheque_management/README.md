# Egyptian Cheque Management (`ff_cheque_management`)

Manage **incoming and outgoing cheques** for Egypt inside the standard Odoo 18
payment flow — no parallel accounting, no core modifications.

One cheque is always **one real `account.payment`**, parked on a configurable
**outstanding account**, tracked to its **due date**, and cleared only through
the standard **Bank Reconciliation**.

- Version: `18.0.1.0.0` — targets Odoo 18.0 Community (works on Enterprise)
- Depends on: `account` only
- License: LGPL-3
- Repository: <https://github.com/FlousFlow/ff-egyptian-cheque-management#18.0>

---

## 1. Features

| Area | What you get |
|---|---|
| Payment methods | `Cheque - Incoming` / `Cheque - Outgoing` (technical code `ff_cheque`) auto-added to every **bank** journal |
| Cheque details | Number, bank (`res.bank`), cheque date, **due date**, drawer, notes — on the payment and in *Register Payment* |
| Due date | Drives the `date_maturity` of the cheque account journal item; maturity status (*Not Due / Due Today / Overdue / Settled*) computed live |
| Lifecycle | Received/Issued → Deposited → **Cleared** (only via bank reconciliation `is_matched`) / Bounced / Cancelled |
| Mark as Deposited | Operational tracking only (date + bank journal) — **no journal entry** |
| Mark as Bounced | Accounting-sound: removes all reconciliations (`_all_reconciled_lines`) and cancels through the standard mechanism; refuses bank-matched cheques |
| Dashboard | Kanban grouped by cheque status (**count per column**) + Graph + Pivot |
| Alerts | Daily cron creates a *Cheque Due* activity for the Accounting Administrator on cheques due within 7 days or overdue (auto-removed when settled); red/amber banners on the form |
| Safety | Duplicate-cheque warning with link; cheque details frozen after confirmation; non-reconcilable/receivable/payable/journal accounts rejected |
| Multi company | Per-company cheque accounts and payment method lines; strict company checks |
| Multi currency | Cheque amount = payment amount; Odoo handles conversion and exchange differences |

## 2. Setup

1. Install **Egyptian Cheque Management** (Apps).
2. Go to **Accounting → Configuration → Settings → Cheque Management** (top of
   the page, right after *Fiscal Localization*) and set per company:
   - **Incoming Cheques Account** — e.g. *Cheques Under Collection*
   - **Outgoing Cheques Account** — e.g. *Issued Cheques*
   - Rules enforced: not receivable/payable, not deprecated, **must be
     reconcilable**, and not the default account of a bank/cash journal.
3. Every **bank journal** automatically receives the two cheque methods with
   your accounts as `payment_account_id`. Cash journals never do.

> Tip: type `cheque` in the settings search box to jump to the section.

## 3. Accounting flows (actual entries)

### Incoming cheque (customer pays 50,000 by post-dated cheque)

| Step | Entry | Cheque status |
|---|---|---|
| Register payment (method *Cheque - Incoming*, due 30 days) | `Dr Cheques Under Collection 50,000 (maturity = due date)` / `Cr Accounts Receivable 50,000` | **Received** |
| Mark as Deposited | *(no entry — tracking only)* | **Deposited** |
| Bank reconciliation against the bank statement line | `Dr Bank 50,000` / `Cr Cheques Under Collection 50,000` | **Cleared** |

The bank is never touched at receipt time, and the incoming-cheques account
nets back to zero exactly when the money arrives.

### Outgoing cheque (vendor is paid 30,000 by cheque)

| Step | Entry | Cheque status |
|---|---|---|
| Register payment (method *Cheque - Outgoing*) | `Dr Accounts Payable 30,000` / `Cr Issued Cheques 30,000 (maturity = due date)` | **Issued** |
| Bank reconciliation (bank statement line −30,000) | `Dr Issued Cheques 30,000` / `Cr Bank 30,000` | **Cleared** |

### Discounting (خصم الشيكات)

*Accounting → open a Received/Deposited cheque → **Discount** button*

`Dr Bank 9,800 + Dr Bank Fees 200 / Cr Cheques Under Collection 10,000`
(entry posted and reconciled — the cheque account frees immediately,
status becomes **Discounted**). If the bank later returns the cheque,
*Mark as Bounced* books the recourse: `Dr Receivable 10,000 / Cr Bank
9,800 / Cr Fees 200`.

### Endorsement (تظهير الشيك)

*Cheque → **Endorse** button → pick the vendor*

`Dr Vendor Payable 10,000 / Cr Cheques Under Collection 10,000`
— the vendor is settled with your customer's cheque (status **Endorsed**).
Bouncing it afterwards re-debits the customer and restores the vendor payable.

### Bounce (before bank matching)

Accounting Administrator only. The wizard removes every reconciliation of the
payment (`_all_reconciled_lines().remove_move_reconcile()`), cancels the
payment with the **standard** cancellation (journal entry cancelled / partner
balance restored), records date + reason and logs everything in the chatter.
A cheque already matched with a bank transaction is refused — unreconcile the
statement line first.

### Partial payment with several cheques

Invoice 30,000 + three cheques of 10,000 → **three independent payments**
(the wizard refuses to spread one cheque over several documents), each with
its own due date, lifecycle and bank matching.

## 4. Menus

**Accounting → Cheques**

- **Cheques Dashboard** — kanban by status (counts per column), graph, pivot
- **Received Cheques** — inbound cheques
- **Issued Cheques** — outbound cheques

Search filters: Due Today / Next 7 & 30 Days / Overdue / status filters.
Group by: Bank, Partner, Due Month, Journal, Cheque Status, Payment Type.

## 5. FAQ

**The payment *state* shows *Paid* but the cheque is not cleared — bug?**
No. In Odoo 18 community, `state` follows the invoice settlement. The cheque
lifecycle is tracked separately: `is_matched` / *Cheque Status* stay
*Received/Issued* until the bank reconciliation really matches it.

**Can I edit the cheque number after confirming?** No — cheque details are
frozen once the payment is confirmed so the journal entry maturity cannot
diverge. Cancel and register a new cheque instead.

**Why don't cash journals offer cheque?** Cheques only make sense on bank
journals; the module never creates cheque lines there.

**Duplicate warning blocks me?** Never — it only warns with a link to the
existing payment (cheque books from different partners often reuse numbers).

**Uninstalling** removes methods, views and data columns. A method line still
referenced by historical payments is kept (standard Odoo behaviour) so old
payments stay readable.

## 6. Testing

```bash
odoo -d <db> -u ff_cheque_management --test-enable \
  --test-tags /ff_cheque_management --stop-after-init --http-port=18069 \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons \
  --db_host=db --db_user=odoo --db_password=odoo
```

35 tests cover: incoming/outgoing entries and maturity, clearing (both
sides), partial multi-cheques, overdue, deposit (no entries), duplicate
warning, bounce (allowed/refused/permissions), non-cheque regression, account
validation, company scoping, new-journal handling, wizard guards, the
due-date alert lifecycle, **and integration/conflict scenarios**: cheques
mixed with a manual payment on one invoice, payments on draft invoices
(vanilla non-auto-reconcile), full bank-statement linkage (statement line ↔
payment ↔ bank move), deposit bank different from payment bank, same number
on different banks (no false duplicate), and cancel/reset/repost cycles.

دليل الاستخدام بالعربية: [README.ar.md](README.ar.md)
