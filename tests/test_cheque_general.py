# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, tests
from odoo.exceptions import ValidationError, UserError

from .common import ChequeCommon


@tests.tagged('post_install', '-at_install')
class TestChequeGeneral(ChequeCommon):

    def test_non_cheque_payment_unchanged(self):
        """A standard manual payment passes through with no cheque impact."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 1000.0)
        receivable_lines = invoice.line_ids.filtered(
            lambda line: line.account_type == 'asset_receivable')
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move.line',
            active_ids=receivable_lines.ids,
        ).create({})
        wizard.action_create_payments()
        payment = invoice.reconciled_payment_ids[-1]

        self.assertFalse(payment.is_cheque_payment)
        self.assertFalse(payment.cheque_number)
        self.assertFalse(payment.cheque_bank_id)
        self.assertFalse(payment.cheque_status)
        # Vanilla behaviour, untouched by us. The payment state timing
        # ('paid' vs 'in_process') is pure core logic on the Egyptian chart -
        # the cheque layer adds nothing and removes nothing.
        self.assertIn(payment.state, ('paid', 'in_process'))
        self.assertFalse(self.env['account.payment'].search([
            ('id', '=', payment.id), ('is_cheque_payment', '=', True)]))

    def test_cheque_accounts_validation(self):
        """Receivable or non-reconcilable accounts are refused."""
        payable_account = self.company_data['default_account_payable']
        with self.assertRaises(ValidationError):
            self.env.company.incoming_cheque_account_id = payable_account

        unreconcilable = self.env['account.account'].create({
            'name': 'Not Reconcilable',
            'code': '115020',
            'account_type': 'asset_current',
            'reconcile': False,
        })
        with self.assertRaises(ValidationError):
            self.env.company.incoming_cheque_account_id = unreconcilable

    def test_method_lines_are_company_scoped(self):
        """Each company configures its own cheque accounts on its own journals.

        In Odoo 18 account.account records are company-independent (shared
        chart), so isolation comes from the per-company settings feeding the
        per-journal payment method lines.
        """
        company2 = self.env['res.company'].create({'name': 'Cheque Co B'})
        self._use_chart_template(company2)
        journal2 = self.env['account.journal'].create({
            'name': 'Bank B',
            'code': 'BNKB',
            'type': 'bank',
            'company_id': company2.id,
        })
        incoming2 = self.env['account.account'].create({
            'name': 'Incoming Cheques B',
            'code': '115030',
            'account_type': 'asset_current',
            'reconcile': True,
        })
        company2.write({'incoming_cheque_account_id': incoming2.id})

        line_a = self.company_data['default_journal_bank'].inbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id.code == 'ff_cheque')
        line_b = journal2.inbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id.code == 'ff_cheque')
        self.assertEqual(line_a.payment_account_id, self.incoming_account)
        self.assertEqual(line_b.payment_account_id, incoming2)
        self.assertNotEqual(line_a, line_b)

    def test_new_bank_journal_gets_cheque_lines(self):
        """Cheques created after install on a fresh bank journal are handled."""
        bank_journal = self.env['account.journal'].create({
            'name': 'Second Bank',
            'code': 'BNK2',
            'type': 'bank',
            'company_id': self.env.company.id,
        })
        for payment_type, account in (
            ('inbound', self.incoming_account),
            ('outbound', self.outgoing_account),
        ):
            line = bank_journal[f'{payment_type}_payment_method_line_ids'].filtered(
                lambda l, pt=payment_type: l.payment_method_id.code == 'ff_cheque')
            self.assertEqual(len(line), 1)
            self.assertEqual(line.payment_account_id, account)

        # Cash journals never carry cheque lines.
        cash_journal = self.env['account.journal'].create({
            'name': 'Cash Test',
            'code': 'CSHT',
            'type': 'cash',
            'company_id': self.env.company.id,
        })
        self.assertFalse(cash_journal.inbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id.code == 'ff_cheque'))

    def test_wizard_rejects_multi_payment_cheque(self):
        """Registering one cheque over several documents is refused."""
        invoice1 = self._create_invoice('out_invoice', self.partner_a, 100.0)
        invoice2 = self._create_invoice('out_invoice', self.partner_b, 200.0)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=(invoice1 + invoice2).ids,
        ).create({
            'payment_method_line_id': self.cheque_inbound_line.id,
            'cheque_number': 'CHK-6000',
            'cheque_bank_id': self.cheque_bank.id,
            'cheque_due_date': fields.Date.today() + timedelta(days=5),
        })
        self.assertFalse(wizard.can_edit_wizard)
        with self.assertRaisesRegex(UserError, 'One cheque must match exactly one payment'):
            wizard.action_create_payments()
