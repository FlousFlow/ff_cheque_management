# -*- coding: utf-8 -*-
from odoo import fields, tests
from odoo.exceptions import UserError

from .common import ChequeCommon


@tests.tagged('post_install', '-at_install')
class TestChequeDiscountEndorseRecourse(ChequeCommon):

    @classmethod
    def _get_fees_account(cls):
        return cls.env['account.account'].create({
            'name': 'Bank Fees INT',
            'code': '520090',
            'account_type': 'expense',
        })

    def _make_incoming_cheque(self, number):
        invoice = self._create_invoice('out_invoice', self.partner_a, 10000.0)
        return self._register_cheque(invoice, **self._cheque_vals(number))

    def test_discount_flow(self):
        """توريق: Dr Bank (net) + Dr fees / Cr cheques; status Discounted."""
        payment = self._make_incoming_cheque('CHK-DISC-1')
        bank_b = self.env['account.journal'].create({
            'name': 'Discount Bank', 'code': 'BNKDSC', 'type': 'bank',
            'company_id': self.env.company.id,
        })
        fees_account = self._get_fees_account()
        wizard = self.env['cheque.discount.wizard'].with_context(
            default_payment_id=payment.id,
        ).create({
            'discount_date': fields.Date.today(),
            'discount_journal_id': bank_b.id,
            'fees_amount': 200.0,
            'fees_account_id': fees_account.id,
        })
        wizard.action_discount_cheque()

        self.assertEqual(payment.cheque_status, 'discounted')
        move = payment.cheque_discount_move_id
        self.assertTrue(move.state == 'posted')
        self.assertEqual(move.journal_id, bank_b)
        bank_lines = move.line_ids.filtered(
            lambda line: line.account_id == bank_b.default_account_id)
        self.assertEqual(sum(bank_lines.mapped('debit')), 9800.0)
        fees_lines = move.line_ids.filtered(lambda line: line.account_id == fees_account)
        self.assertEqual(sum(fees_lines.mapped('debit')), 200.0)
        # The cheque account nets back to zero and the payment line is settled.
        balance = sum(self._account_move_lines(self.incoming_account).mapped('balance'))
        self.assertTrue(self.env.company.currency_id.is_zero(balance))
        liquidity_lines = payment._seek_for_lines()[0]
        self.assertTrue(liquidity_lines.reconciled)

    def test_discount_guards(self):
        payment = self._make_incoming_cheque('CHK-DISC-2')
        bank = self.company_data['default_journal_bank']
        # fees above the amount are refused
        wizard = self.env['cheque.discount.wizard'].with_context(
            default_payment_id=payment.id).create({
            'discount_journal_id': bank.id,
            'fees_amount': 20000.0,
        })
        with self.assertRaisesRegex(UserError, 'cannot exceed'):
            wizard.action_discount_cheque()
        # outbound cheques are never discountable
        bill = self._create_invoice('in_invoice', self.partner_a, 100.0)
        out_payment = self._register_cheque(
            bill, payment_type='outbound', **self._cheque_vals('CHK-DISC-3'))
        with self.assertRaisesRegex(UserError, 'incoming'):
            self.env['cheque.discount.wizard'].with_context(
                default_payment_id=out_payment.id).create({
                'discount_journal_id': bank.id,
            }).action_discount_cheque()

    def test_discount_then_bounce_recourse(self):
        """Bouncing a discounted cheque re-debits the customer and restores
        the bank/fees taken by the discount entry."""
        payment = self._make_incoming_cheque('CHK-DISC-4')
        bank_b = self.env['account.journal'].create({
            'name': 'Discount Bank 2', 'code': 'BNKDSC2', 'type': 'bank',
            'company_id': self.env.company.id,
        })
        fees_account = self._get_fees_account()
        self.env['cheque.discount.wizard'].with_context(
            default_payment_id=payment.id).create({
            'discount_date': fields.Date.today(),
            'discount_journal_id': bank_b.id,
            'fees_amount': 200.0,
            'fees_account_id': fees_account.id,
        }).action_discount_cheque()

        self.env['cheque.bounce.wizard'].with_context(
            default_payment_id=payment.id).create({
            'bounce_date': fields.Date.today(),
            'reason': 'Discounted cheque returned by bank',
        }).action_mark_bounced()

        self.assertTrue(payment.cheque_bounced)
        self.assertEqual(payment.cheque_status, 'bounced')
        recourse = payment.cheque_bounce_move_id
        self.assertEqual(recourse.journal_id, bank_b)
        receivable = self.partner_a.with_company(self.env.company).property_account_receivable_id
        recourse_receivable = recourse.line_ids.filtered(
            lambda line: line.account_id == receivable)
        self.assertEqual(sum(recourse_receivable.mapped('debit')), 10000.0)
        # The bank and fees accounts net back to zero.
        self.assertTrue(self.env.company.currency_id.is_zero(sum(
            self._account_move_lines(bank_b.default_account_id).mapped('balance'))))
        self.assertTrue(self.env.company.currency_id.is_zero(sum(
            self._account_move_lines(fees_account).mapped('balance'))))

    def test_endorse_flow(self):
        """تظهير: Dr Vendor Payable / Cr cheques; status Endorsed."""
        payment = self._make_incoming_cheque('CHK-END-1')
        vendor = self.partner_b
        self.env['cheque.endorse.wizard'].with_context(
            default_payment_id=payment.id,
        ).create({
            'endorse_date': fields.Date.today(),
            'vendor_id': vendor.id,
        }).action_endorse_cheque()

        self.assertEqual(payment.cheque_status, 'endorsed')
        move = payment.cheque_endorsed_move_id
        self.assertTrue(move.state == 'posted')
        payable = vendor.with_company(self.env.company).property_account_payable_id
        payable_lines = move.line_ids.filtered(lambda line: line.account_id == payable)
        self.assertEqual(sum(payable_lines.mapped('debit')), 10000.0)
        balance = sum(self._account_move_lines(self.incoming_account).mapped('balance'))
        self.assertTrue(self.env.company.currency_id.is_zero(balance))

    def test_endorse_guards(self):
        payment = self._make_incoming_cheque('CHK-END-2')
        # same partner refused
        with self.assertRaisesRegex(UserError, 'same partner'):
            self.env['cheque.endorse.wizard'].with_context(
                default_payment_id=payment.id).create({
                'vendor_id': self.partner_a.id,
            }).action_endorse_cheque()
        # cannot endorse after discounting
        bank = self.company_data['default_journal_bank']
        fees_account = self._get_fees_account()
        self.env['cheque.discount.wizard'].with_context(
            default_payment_id=payment.id).create({
            'discount_journal_id': bank.id,
            'fees_amount': 0.0,
        }).action_discount_cheque()
        with self.assertRaisesRegex(UserError, 'Received or Deposited'):
            self.env['cheque.endorse.wizard'].with_context(
                default_payment_id=payment.id).create({
                'vendor_id': self.partner_b.id,
            }).action_endorse_cheque()

    def test_cleared_cheque_bounce_recourse(self):
        """Bouncing a cleared cheque: Dr Receivable / Cr Bank, reconciled with
        the statement bank line; the customer owes again."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 7000.0)
        payment = self._register_cheque(invoice, **self._cheque_vals('CHK-RC-1'))
        self._match_with_bank_statement(payment, amount=7000.0)
        self.assertEqual(payment.cheque_status, 'cleared')
        bank_account = self.company_data['default_journal_bank'].default_account_id
        receivable = self.partner_a.with_company(self.env.company).property_account_receivable_id

        self.env['cheque.bounce.wizard'].with_context(
            default_payment_id=payment.id).create({
            'bounce_date': fields.Date.today(),
            'reason': 'Returned after collection',
        }).action_mark_bounced()

        self.assertTrue(payment.cheque_bounced)
        self.assertEqual(payment.cheque_status, 'bounced')
        recourse = payment.cheque_bounce_move_id
        recourse_bank = recourse.line_ids.filtered(
            lambda line: line.account_id == bank_account)
        self.assertEqual(sum(recourse_bank.mapped('credit')), 7000.0)
        recourse_receivable = recourse.line_ids.filtered(
            lambda line: line.account_id == receivable)
        self.assertEqual(sum(recourse_receivable.mapped('debit')), 7000.0)
        # The bank nets back to zero and no line stays dangling.
        self.assertTrue(self.env.company.currency_id.is_zero(sum(
            self._account_move_lines(bank_account).mapped('balance'))))
        self.assertTrue(recourse_receivable.amount_residual, 7000.0)

    def test_outgoing_cleared_cheque_bounce_recourse(self):
        """Outgoing cleared cheque bounces: Dr Bank / Cr Vendor Payable."""
        bill = self._create_invoice('in_invoice', self.partner_a, 6000.0)
        payment = self._register_cheque(
            bill, payment_type='outbound', **self._cheque_vals('CHK-RC-2'))
        self._match_with_bank_statement(payment, amount=-6000.0)
        self.assertEqual(payment.cheque_status, 'cleared')
        bank_account = self.company_data['default_journal_bank'].default_account_id
        payable = self.partner_a.with_company(self.env.company).property_account_payable_id

        self.env['cheque.bounce.wizard'].with_context(
            default_payment_id=payment.id).create({
            'bounce_date': fields.Date.today(),
            'reason': 'Vendor cheque returned',
        }).action_mark_bounced()

        self.assertEqual(payment.cheque_status, 'bounced')
        recourse = payment.cheque_bounce_move_id
        recourse_bank = recourse.line_ids.filtered(
            lambda line: line.account_id == bank_account)
        self.assertEqual(sum(recourse_bank.mapped('debit')), 6000.0)
        recourse_payable = recourse.line_ids.filtered(
            lambda line: line.account_id == payable)
        self.assertEqual(sum(recourse_payable.mapped('credit')), 6000.0)
        self.assertTrue(self.env.company.currency_id.is_zero(sum(
            self._account_move_lines(bank_account).mapped('balance'))))

    def test_drawer_partner_link_and_smart_button(self):
        """The drawer partner is stored and the partner form shows the count."""
        third_party = self.env['res.partner'].create({'name': 'Third Party Drawer'})
        payment = self.env['account.payment'].with_context(
            default_payment_type='inbound',
            default_partner_type='customer',
            ff_default_cheque=1,
        ).create({
            'partner_id': self.partner_a.id,
            'amount': 500.0,
            'journal_id': self.company_data['default_journal_bank'].id,
            'cheque_partner_id': third_party.id,
            **self._cheque_vals('CHK-DRW-1'),
        })
        self.assertEqual(payment.cheque_partner_id, third_party)
        self.assertEqual(third_party.cheque_count, 1)
        # The payment partner (customer) also sees the cheque.
        self.assertGreaterEqual(self.partner_a.cheque_count, 1)
