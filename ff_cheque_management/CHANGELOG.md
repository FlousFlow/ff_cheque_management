# Changelog — ff_cheque_management

All notable changes to this module are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [18.0.1.2.1] — 2026-09-01

### Changed
- Author unified as **Flous Flow** (apps.odoo.com search groups all company
  modules under one author).
- Added store cover image (`static/description/cover.png`, 1200x630) shown on
  the module page and used as the apps store thumbnail.

## [18.0.1.2.0] — 2026-09-01

### Added
- **Cheque discounting (توريق)**: *Discount* button on Received/Deposited
  incoming cheques — posts `Dr Bank (net) + Dr fees / Cr cheques account`,
  reconciled; new *Discounted* status; fees account + amount captured.
- **Cheque endorsement (تظهير)**: settle a vendor with a received cheque —
  `Dr Vendor Payable / Cr cheques account`; new *Endorsed* status.
- **Bounce after settlement**: cleared / discounted / endorsed cheques can now
  be bounced — the wizard books a recourse entry (customer re-debited; bank
  take-back, fees reversal or vendor payable restored) and reconciles it with
  the original flow (no dangling items, both inbound and outbound).
- **Drawer partner link** for third-party cheques + *Cheques* smart button
  (with count) on the partner form.
- New search filters (Discounted / Endorsed), kanban badges and form groups.
- 8 new tests (discount flow + guards, endorsement flow + guards, recourse for
  cleared/discounted/outgoing, drawer link) — total 35, all green.

## [18.0.1.1.0] — 2026-08-31

### Added
- **Cheques Dashboard**: kanban grouped by cheque status (count per column)
  with graph and pivot views (`Accounting → Cheques → Cheques Dashboard`).
- **Due-date alerts**: dedicated `Cheque Due` activity type + daily cron that
  keeps one activity per outstanding cheque due within 7 days (or overdue),
  assigned to the company's Accounting Administrator; activities are removed
  automatically when the cheque is settled. Red (overdue) and amber (due
  today) alert banners on the payment form.
- **Cheque-aware creation**: the Received/Issued menus open a real cheque form
  (`default_payment_type`, `default_partner_type` and the cheque method line
  preselected), so issue date and due date are visible immediately.
- 3 new tests (menu defaults, alert lifecycle, overdue summary) — total 20.
- 2026-09-01: integration/conflict test round — 7 more tests (cheques mixed
  with manual payments, draft-invoice payments, full bank-statement linkage,
  split deposit banks, duplicate false-positive guard, cancel/reset/repost
  cycle, dashboard grouping) — total 27, all green.

### Fixed
- Cheques menu was invisible: Odoo 18 made `account.group_account_readonly` an
  independent settings toggle (not implied by the manager group). Menus now
  inherit the Accounting app visibility.
- Settings block relocated to the top of the accounting settings page (right
  after Fiscal Localization).

## [18.0.1.0.0] — 2026-08-30

### Added
- Initial release.
- Payment methods `Cheque - Incoming` / `Cheque - Outgoing` (code `ff_cheque`)
  auto-attached to bank journals; per-company outstanding accounts in Settings.
- Cheque details on `account.payment` (number, bank, dates, drawer, notes) with
  a duplicate warning; details frozen after confirmation.
- `cheque_status` lifecycle (Received/Issued/Deposited/Cleared/Bounced/
  Cancelled) driven by the standard `is_matched` bank-matching flag; due-date
  driven `date_maturity` on the liquidity journal item; live maturity status.
- *Mark as Deposited* wizard (tracking only, no accounting impact).
- *Mark as Bounced* wizard for unmatched cheques: full unreconciliation plus
  standard cancellation, manager-only, audit trail in chatter.
- Received/Issued menus with dedicated list views, search filters (Due Today /
  Next 7 & 30 Days / Overdue / statuses) and group-bys.
- Multi-company isolation and multi-currency support; uninstall safety hook.
- 17 automated tests (entries, clearing, partials, overdue, bounce, security,
  regression, company scoping).
