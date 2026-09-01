# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, tests

from .common import ChequeCommon


@tests.tagged('post_install', '-at_install')
class TestChequeIntegration(ChequeCommon):
    """Conflict scenarios: cheques mixed with standard payments, draft
    invoices, bank-statement linkage (دفاتر البنك), split deposit banks and
    duplicate-warning false positives."""

    def test_mixed_cheque_and_manual_payments_on_one_invoice(self):
        """Cheques and a plain manual payment coexist on the same invoice."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 30000.0)
        cheque1 = self._register_cheque(
            invoice, amount=10000.0, **self._cheque_vals('CHK-INT-1'))
        cheque2 = self._register_cheque(
            invoice, amount=10000.0, **self._cheque_vals('CHK-INT-2', due_in_days=15))
        receivable = invoice.line_ids.filtered(
            lambda line: line.account_type == 'asset_receivable')
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move.line',
            active_ids=receivable.ids,
        ).create({})
        wizard.action_create_payments()
        payments = invoice.reconciled_payment_ids
        manual = payments - cheque1 - cheque2
        self.assertEqual(len(manual), 1)
        self.assertFalse(manual.is_cheque_payment)
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        # Clearing both cheques nets the incoming account back to zero while
        # the manual payment keeps its own path untouched.
        self._match_with_bank_statement(cheque1, amount=10000.0)
        self._match_with_bank_statement(cheque2, amount=10000.0)
        balance = sum(self._account_move_lines(self.incoming_account).mapped('balance'))
        self.assertTrue(self.env.company.currency_id.is_zero(balance))

    def test_cheque_registered_on_draft_invoice(self):
        """Register Payment on a draft invoice.

        Vanilla Odoo 18: the payment is NOT auto-reconciled when the invoice
        is posted later; the module stays out of the way and a manual
        reconciliation settles the invoice normally.
        """
        invoice = self._create_invoice('out_invoice', self.partner_a, 5000.0, post=False)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-INT-DRAFT'))
        self.assertFalse(payment.is_reconciled)
        invoice.action_post()
        self.assertFalse(payment.is_reconciled)
        self.assertEqual(payment.cheque_status, 'received')

        receivable = invoice.line_ids.filtered(
            lambda line: line.account_type == 'asset_receivable')
        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == receivable.account_id)
        (receivable + payment_lines).reconcile()
        self.assertTrue(payment.is_reconciled)
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertEqual(payment.cheque_status, 'received')

    def test_bank_statement_linkage(self):
        """Full bank-statement chain (دفتر البنك): statement line ↔ payment."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 7000.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-INT-LINK'))
        bank_account = self.company_data['default_journal_bank'].default_account_id

        statement_line = self._match_with_bank_statement(payment, amount=7000.0)

        self.assertTrue(payment.is_matched)
        self.assertEqual(payment.cheque_status, 'cleared')
        # The payment points back at the statement line (stat button data).
        self.assertIn(statement_line, payment.reconciled_statement_line_ids)
        # The statement move itself: Dr Bank / Cr cheques, fully reconciled.
        statement_move = statement_line.move_id
        self.assertEqual(sum(statement_move.line_ids.filtered(
            lambda line: line.account_id == bank_account).mapped('debit')), 7000.0)
        self.assertEqual(sum(statement_move.line_ids.filtered(
            lambda line: line.account_id == self.incoming_account).mapped('credit')), 7000.0)
        self.assertTrue(statement_move.line_ids.mapped('full_reconcile_id'))

    def test_deposit_bank_differs_from_payment_bank(self):
        """Cheque received on Bank A, deposited and collected through Bank B."""
        bank_b = self.env['account.journal'].create({
            'name': 'Bank B INT',
            'code': 'BNKB2',
            'type': 'bank',
            'company_id': self.env.company.id,
        })
        invoice = self._create_invoice('out_invoice', self.partner_a, 4000.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-INT-B2'))
        self.env['cheque.deposit.wizard'].with_context(
            default_payment_id=payment.id,
        ).create({
            'deposit_date': fields.Date.today(),
            'deposit_journal_id': bank_b.id,
        }).action_mark_deposited()
        self.assertEqual(payment.cheque_status, 'deposited')

        # The statement arrives on Bank B: reconciliation still clears the
        # cheque and moves Bank B, not Bank A.
        self._match_with_bank_statement(payment, amount=4000.0, journal=bank_b)
        self.assertTrue(payment.is_matched)
        self.assertEqual(payment.cheque_status, 'cleared')
        bank_b_balance = sum(self._account_move_lines(
            bank_b.default_account_id).mapped('balance'))
        self.assertEqual(bank_b_balance, 4000.0)

    def test_same_number_different_banks_no_false_duplicate(self):
        """Same cheque number on different banks is NOT a duplicate."""
        bank2 = self.env['res.bank'].create({'name': 'Other Bank INT'})
        invoice = self._create_invoice('out_invoice', self.partner_a, 100.0)
        first = self._register_cheque(
            invoice, **self._cheque_vals('CHK-SAME-NUM', due_in_days=10))
        invoice2 = self._create_invoice('out_invoice', self.partner_b, 200.0)
        second = self._register_cheque(
            invoice2,
            cheque_number='CHK-SAME-NUM',
            cheque_bank_id=bank2.id,
            cheque_due_date=fields.Date.today() + timedelta(days=10),
        )
        self.assertFalse(second.cheque_duplicate_ids)

    def test_cancel_reset_repost_status_cycle(self):
        """Standard cancel / reset-to-draft / repost keeps the status sane."""
        payment = self.env['account.payment'].with_context(
            default_payment_type='inbound',
            default_partner_type='customer',
            ff_default_cheque=1,
        ).create({
            'partner_id': self.partner_a.id,
            'amount': 250.0,
            'journal_id': self.company_data['default_journal_bank'].id,
            **self._cheque_vals('CHK-INT-CYCLE'),
        })
        payment.action_post()
        self.assertEqual(payment.cheque_status, 'received')

        payment.action_cancel()
        self.assertEqual(payment.cheque_status, 'cancelled')
        payment.action_draft()
        self.assertEqual(payment.cheque_status, 'received')
        payment.action_post()
        self.assertEqual(payment.cheque_status, 'received')

    def test_dashboard_grouping_counts(self):
        """The dashboard grouping (cheque_status) returns real counts."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 300.0)
        self._register_cheque(invoice, **self._cheque_vals('CHK-INT-DASH'))
        groups = self.env['account.payment']._read_group(
            [('is_cheque_payment', '=', True)],
            ['cheque_status'],
            ['__count'],
        )
        counts = dict((status or False, count) for status, count in groups)
        self.assertGreaterEqual(counts.get('received', 0), 1)
