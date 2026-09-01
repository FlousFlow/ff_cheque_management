# -*- coding: utf-8 -*-
from odoo import tests
from odoo.exceptions import AccessError, UserError

from .common import ChequeCommon


@tests.tagged('post_install', '-at_install')
class TestChequeReconciliation(ChequeCommon):

    def test_incoming_cheque_clearing(self):
        """Bank reconciliation clears the cheque: Dr Bank / Cr Incoming Cheques."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 10000.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-3001'))
        bank_account = self.company_data['default_journal_bank'].default_account_id

        self._match_with_bank_statement(payment, amount=10000.0)

        self.assertTrue(payment.is_matched)
        self.assertEqual(payment.cheque_status, 'cleared')
        self.assertEqual(payment.state, 'paid')

        # The incoming cheques account no longer carries the cheque amount.
        incoming_balance = sum(self._account_move_lines(self.incoming_account).mapped('balance'))
        self.assertTrue(self.env.company.currency_id.is_zero(incoming_balance))

        # The bank received the money through the statement line.
        bank_balance = sum(self._account_move_lines(bank_account).mapped('balance'))
        self.assertEqual(bank_balance, 10000.0)

    def test_outgoing_cheque_clearing(self):
        """Bank reconciliation cashes the cheque: Dr Outgoing Cheques / Cr Bank."""
        bill = self._create_invoice('in_invoice', self.partner_a, 10000.0)
        payment = self._register_cheque(
            bill, payment_type='outbound', **self._cheque_vals('CHK-3002'))
        bank_account = self.company_data['default_journal_bank'].default_account_id

        self._match_with_bank_statement(payment, amount=-10000.0)

        self.assertTrue(payment.is_matched)
        self.assertEqual(payment.cheque_status, 'cleared')

        outgoing_balance = sum(self._account_move_lines(self.outgoing_account).mapped('balance'))
        self.assertTrue(self.env.company.currency_id.is_zero(outgoing_balance))
        bank_balance = sum(self._account_move_lines(bank_account).mapped('balance'))
        self.assertEqual(bank_balance, -10000.0)

    def test_multiple_cheques_partial_payment(self):
        """One cheque = one payment: 3 cheques of 10k settle a 30k invoice."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 30000.0)
        payments = self.env['account.payment']
        for i in range(3):
            payments += self._register_cheque(
                invoice,
                amount=10000.0,
                **self._cheque_vals(f'CHK-400{i + 1}', due_in_days=10 * (i + 1)),
            )

        self.assertEqual(len(payments), 3)
        self.assertEqual(len(payments.move_id), 3)
        self.assertEqual({p.cheque_status for p in payments}, {'received'})
        # Independent due dates on the liquidity lines.
        maturities = {
            line.date_maturity
            for payment in payments
            for line in payment._seek_for_lines()[0]
        }
        self.assertEqual(len(maturities), 3)
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))

    def test_bounce_before_bank_matching(self):
        """Bounce uses the standard cancellation and restores the balance."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 5000.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-5001'))
        self.assertTrue(invoice.line_ids.filtered(
            lambda line: line.account_type == 'asset_receivable').reconciled)

        bounce_wizard = self.env['cheque.bounce.wizard'].with_context(
            default_payment_id=payment.id,
            active_id=payment.id,
        ).create({
            'bounce_date': payment.date,
            'reason': 'Insufficient funds (test)',
        })
        bounce_wizard.action_mark_bounced()

        self.assertEqual(payment.state, 'canceled')
        self.assertTrue(payment.cheque_bounced)
        self.assertEqual(payment.cheque_status, 'bounced')
        self.assertFalse(payment.move_id.line_ids.mapped('matched_debit_ids'))
        self.assertFalse(payment.move_id.line_ids.mapped('matched_credit_ids'))
        # The customer balance is due again.
        self.assertEqual(invoice.payment_state, 'not_paid')

    def test_bounce_cleared_cheque_with_recourse(self):
        """Since v1.2.0 a bank-matched (cleared) cheque CAN be bounced: the
        wizard books the recourse entry (Dr Receivable / Cr Bank) instead of
        refusing."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 5000.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-5002'))
        self._match_with_bank_statement(payment, amount=5000.0)
        self.assertTrue(payment.is_matched)

        self.env['cheque.bounce.wizard'].with_context(
            default_payment_id=payment.id).create({
            'bounce_date': payment.date,
            'reason': 'Returned by bank after collection',
        }).action_mark_bounced()
        self.assertTrue(payment.cheque_bounced)
        self.assertEqual(payment.cheque_status, 'bounced')
        self.assertTrue(payment.cheque_bounce_move_id)

    def test_bounce_requires_account_manager(self):
        """Only Accounting Administrators may bounce a cheque.

        The ACL on the wizard already refuses creation for billing users, and
        the action itself re-checks the manager group.
        """
        invoice = self._create_invoice('out_invoice', self.partner_a, 5000.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-5003'))
        invoice_user = self.env['res.users'].create({
            'name': 'Billing User',
            'login': 'billing_user_chk',
            'email': 'billing@example.com',
            'groups_id': [(6, 0, self.env.ref('account.group_account_invoice').ids)],
        })
        with self.assertRaisesRegex(AccessError, 'not allowed'):
            self.env['cheque.bounce.wizard'].with_user(invoice_user).with_context(
                default_payment_id=payment.id).create({
                'bounce_date': payment.date,
                'reason': 'test',
            })
