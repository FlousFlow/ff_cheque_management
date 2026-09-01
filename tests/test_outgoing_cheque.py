# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, tests

from .common import ChequeCommon


@tests.tagged('post_install', '-at_install')
class TestOutgoingCheque(ChequeCommon):

    def test_outgoing_cheque_payment_flow(self):
        """Register an outgoing cheque and check the whole accounting flow."""
        bill = self._create_invoice('in_invoice', self.partner_a, 10000.0)
        due_date = fields.Date.today() + timedelta(days=45)
        payment = self._register_cheque(
            bill,
            payment_type='outbound',
            cheque_number='CHK-2001',
            cheque_bank_id=self.cheque_bank.id,
            cheque_due_date=due_date,
        )

        self.assertTrue(payment.is_cheque_payment)
        self.assertEqual(payment.cheque_status, 'issued')
        # In Odoo 18 community the payment state follows the invoice
        # settlement; bank matching is tracked by is_matched/cheque_status.
        self.assertIn(payment.state, ('in_process', 'paid'))
        self.assertFalse(payment.is_matched)
        self.assertTrue(payment.is_reconciled)

        # Journal entry: Dr Payable / Cr Outgoing Cheques. Bank untouched.
        liquidity_lines = payment._seek_for_lines()[0]
        counterpart_lines = payment._seek_for_lines()[1]
        self.assertEqual(liquidity_lines.account_id, self.outgoing_account)
        self.assertEqual(liquidity_lines.credit, 10000.0)
        self.assertEqual(liquidity_lines.date_maturity, due_date)
        self.assertEqual(counterpart_lines.account_id.account_type, 'liability_payable')
        self.assertEqual(counterpart_lines.debit, 10000.0)
        self.assertFalse(payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.company_data['default_journal_bank'].default_account_id))

        self.assertIn(bill.payment_state, ('paid', 'in_payment'))
