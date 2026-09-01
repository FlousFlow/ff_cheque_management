# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class ChequeCommon(AccountTestInvoicingCommon):

    @classmethod
    def _use_chart_template(cls, company, chart_template_ref=None):
        # Pin the chart to the Egyptian localization ('eg' is the chart code of
        # the l10n_eg module): it matches the target market of the module.
        super()._use_chart_template(company, chart_template_ref or 'eg')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        cls.incoming_account = cls.env['account.account'].create({
            'name': 'Incoming Cheques',
            'code': '115010',
            'account_type': 'asset_current',
            'reconcile': True,
        })
        cls.outgoing_account = cls.env['account.account'].create({
            'name': 'Outgoing Cheques',
            'code': '215010',
            'account_type': 'liability_current',
            'reconcile': True,
        })
        cls.env.company.write({
            'incoming_cheque_account_id': cls.incoming_account.id,
            'outgoing_cheque_account_id': cls.outgoing_account.id,
        })
        cls.cheque_bank = cls.env['res.bank'].create({
            'name': 'Test Cheque Bank',
            'bic': 'TESTEGCX',
        })
        cls.cheque_inbound_line = cls._get_cheque_method_line('inbound')
        cls.cheque_outbound_line = cls._get_cheque_method_line('outbound')

    @classmethod
    def _get_cheque_method_line(cls, payment_type):
        journal = cls.company_data['default_journal_bank']
        return journal[f'{payment_type}_payment_method_line_ids'].filtered(
            lambda line: line.payment_method_id.code == 'ff_cheque')

    @classmethod
    def _create_invoice(cls, move_type, partner, amount, post=True):
        account = (
            cls.company_data['default_account_revenue']
            if move_type == 'out_invoice'
            else cls.company_data['default_account_expense']
        )
        today = fields.Date.today()
        invoice = cls.env['account.move'].create({
            'move_type': move_type,
            'partner_id': partner.id,
            'date': today,
            'invoice_date': today,
            'invoice_line_ids': [(0, 0, {
                'name': 'test',
                'price_unit': amount,
                'quantity': 1,
                'account_id': account.id,
            })],
        })
        if post:
            invoice.action_post()
        return invoice

    def _register_cheque(self, move, payment_type='inbound', amount=None, **cheque_vals):
        """Register a cheque through the standard Register Payment wizard."""
        method_line = self.cheque_inbound_line if payment_type == 'inbound' else self.cheque_outbound_line
        receivable_lines = move.line_ids.filtered(
            lambda line: line.account_type in ('asset_receivable', 'liability_payable'))
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move.line',
            active_ids=receivable_lines.ids,
        ).create({
            'payment_method_line_id': method_line.id,
            'amount': amount if amount is not None else move.amount_total,
            **cheque_vals,
        })
        wizard.action_create_payments()
        return move.reconciled_payment_ids[-1]

    def _match_with_bank_statement(self, payment, amount=None, journal=None):
        """Simulate the bank reconciliation without the enterprise widget.

        Same pattern as odoo/addons/account/tests/test_account_payment.py:
        move the statement suspense line to the payment's cheque account and
        reconcile both lines together.
        """
        liquidity_lines = payment._seek_for_lines()[0]
        statement_line = self.env['account.bank.statement.line'].create({
            'payment_ref': payment.cheque_number or 'cheque',
            'journal_id': (journal or self.company_data['default_journal_bank']).id,
            'partner_id': payment.partner_id.id,
            'amount': amount if amount is not None else (
                payment.amount if payment.payment_type == 'inbound' else -payment.amount),
        })
        _st_liquidity, st_suspense, _st_other = statement_line\
            .with_context(skip_account_move_synchronization=True)\
            ._seek_for_lines()
        st_suspense.account_id = liquidity_lines.account_id
        (st_suspense + liquidity_lines).reconcile()
        return statement_line

    @staticmethod
    def _account_move_lines(account):
        """Move lines of an account.

        In Odoo 18 account.account is company-independent and has no
        `line_ids` One2many anymore, so search instead.
        """
        return account.env['account.move.line'].search([('account_id', '=', account.id)])

    def _cheque_vals(self, number='CHK-0001', due_in_days=30):
        return {
            'cheque_number': number,
            'cheque_bank_id': self.cheque_bank.id,
            'cheque_due_date': fields.Date.today() + timedelta(days=due_in_days),
        }
