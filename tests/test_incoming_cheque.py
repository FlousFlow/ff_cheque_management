# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, tests
from odoo.exceptions import ValidationError

from .common import ChequeCommon


@tests.tagged('post_install', '-at_install')
class TestIncomingCheque(ChequeCommon):

    def test_incoming_cheque_payment_flow(self):
        """Register an incoming cheque and check the whole accounting flow."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 10000.0)
        due_date = fields.Date.today() + timedelta(days=30)
        payment = self._register_cheque(
            invoice,
            cheque_number='CHK-1001',
            cheque_bank_id=self.cheque_bank.id,
            cheque_due_date=due_date,
        )

        self.assertTrue(payment.is_cheque_payment)
        self.assertEqual(payment.cheque_status, 'received')
        # In Odoo 18 community the payment state follows the invoice
        # settlement; bank matching is tracked by is_matched/cheque_status.
        self.assertIn(payment.state, ('in_process', 'paid'))
        self.assertFalse(payment.is_matched)
        self.assertTrue(payment.is_reconciled)

        # Invoice is settled, the bank is untouched.
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertFalse(payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.company_data['default_journal_bank'].default_account_id))

        # Liquidity line: parked on the incoming cheques account with the
        # cheque due date as date maturity.
        liquidity_lines = payment._seek_for_lines()[0]
        self.assertEqual(len(liquidity_lines), 1)
        self.assertEqual(liquidity_lines.account_id, self.incoming_account)
        self.assertEqual(liquidity_lines.date_maturity, due_date)
        self.assertEqual(liquidity_lines.debit, 10000.0)

        counterpart_lines = payment._seek_for_lines()[1]
        self.assertEqual(counterpart_lines.account_id.account_type, 'asset_receivable')
        self.assertEqual(counterpart_lines.credit, 10000.0)

        # Incoming cheques account is debited by the cheque amount.
        account_balances = sum(payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.incoming_account).mapped('balance'))
        self.assertEqual(account_balances, 10000.0)

    def test_incoming_cheque_required_fields(self):
        """Cheque number, bank and due date are mandatory."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 500.0)
        with self.assertRaisesRegex(ValidationError, 'required'):
            self.env['account.payment'].create({
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': self.partner_a.id,
                'amount': 500.0,
                'journal_id': self.company_data['default_journal_bank'].id,
                'payment_method_line_id': self.cheque_inbound_line.id,
                'destination_account_id': self.company_data['default_account_receivable'].id,
            })

    def test_incoming_cheque_maturity_overdue(self):
        """A cheque due yesterday is overdue but still outstanding."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 800.0)
        payment = self._register_cheque(
            invoice,
            cheque_number='CHK-1002',
            cheque_bank_id=self.cheque_bank.id,
            cheque_due_date=fields.Date.today() - timedelta(days=1),
        )
        self.assertEqual(payment.cheque_status, 'received')
        self.assertEqual(payment.cheque_maturity_status, 'overdue')
        self.assertLess(payment.days_to_maturity, 0)
        self.assertTrue(self.env['account.payment'].search([
            ('id', '=', payment.id),
            ('cheque_due_date', '<', fields.Date.today()),
            ('cheque_status', 'not in', ('cleared', 'bounced', 'cancelled')),
        ]))

    def test_incoming_cheque_deposit(self):
        """Mark as Deposited is operational tracking only: no new entry."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 900.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-1003'))
        move_count_before = self.env['account.move'].search_count([])

        deposit_wizard = self.env['cheque.deposit.wizard'].with_context(
            default_payment_id=payment.id,
            active_id=payment.id,
        ).create({
            'deposit_date': fields.Date.today(),
            'deposit_journal_id': self.company_data['default_journal_bank'].id,
        })
        deposit_wizard.action_mark_deposited()

        self.assertEqual(payment.cheque_status, 'deposited')
        self.assertEqual(payment.cheque_deposit_date, fields.Date.today())
        self.assertEqual(payment.cheque_deposit_journal_id, self.company_data['default_journal_bank'])
        self.assertFalse(payment.is_matched)
        # Depositing must not move any money.
        self.assertEqual(self.env['account.move'].search_count([]), move_count_before)

        # Depositing twice is refused.
        with self.assertRaisesRegex(Exception, 'deposited'):
            deposit_wizard.action_mark_deposited()

    def test_incoming_cheque_duplicate_warning(self):
        """Registering the same cheque number/bank shows the duplicate link."""
        bank = self.cheque_bank
        invoice1 = self._create_invoice('out_invoice', self.partner_a, 100.0)
        self._register_cheque(
            invoice1, cheque_number='CHK-DUP', cheque_bank_id=bank.id,
            cheque_due_date=fields.Date.today() + timedelta(days=10))
        invoice2 = self._create_invoice('out_invoice', self.partner_b, 200.0)
        payment2 = self._register_cheque(
            invoice2, cheque_number='CHK-DUP', cheque_bank_id=bank.id,
            cheque_due_date=fields.Date.today() + timedelta(days=10))
        duplicates = payment2.cheque_duplicate_ids
        self.assertEqual(len(duplicates), 1)
        self.assertNotEqual(duplicates, payment2)
        self.assertEqual(duplicates.cheque_number, 'CHK-DUP')
