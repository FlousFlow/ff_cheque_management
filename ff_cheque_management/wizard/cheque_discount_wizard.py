# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ChequeDiscountWizard(models.TransientModel):
    _name = 'cheque.discount.wizard'
    _description = 'Discount Cheque (توريق)'

    payment_id = fields.Many2one(
        comodel_name='account.payment', string="Cheque Payment",
        required=True, check_company=True,
        domain="[('is_cheque_payment', '=', True)]")
    discount_date = fields.Date(
        string="Discount Date", required=True,
        default=fields.Date.context_today)
    discount_journal_id = fields.Many2one(
        comodel_name='account.journal', string="Discount Bank Journal",
        required=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]")
    fees_amount = fields.Monetary(
        string="Bank Fees", currency_field='currency_id',
        help="Commission and/or interest kept by the bank.")
    fees_account_id = fields.Many2one(
        comodel_name='account.account', string="Fees Account",
        domain="[('deprecated', '=', False), ('account_type', 'not in', ('asset_receivable', 'liability_payable'))]")
    company_id = fields.Many2one(related='payment_id.company_id')
    currency_id = fields.Many2one(related='payment_id.currency_id')
    amount = fields.Monetary(related='payment_id.amount', currency_field='currency_id')

    @api.onchange('fees_amount')
    def _onchange_fees_amount(self):
        if self.fees_amount and not self.fees_account_id:
            # Note: account.account is company-independent in Odoo 18.
            self.fees_account_id = self.env['account.account'].search([
                ('account_type', '=', 'expense'),
                ('deprecated', '=', False),
            ], limit=1)

    def action_discount_cheque(self):
        self.ensure_one()
        payment = self.payment_id
        if not payment.is_cheque_payment:
            raise UserError(_("This payment is not a cheque payment."))
        if payment.payment_type != 'inbound':
            raise UserError(_("Only incoming cheques can be discounted."))
        if payment.cheque_status not in ('received', 'deposited'):
            raise UserError(_("Only a Received or Deposited cheque can be discounted (current status: %s).",
                              payment.cheque_status))
        if self.discount_journal_id.company_id != payment.company_id:
            raise UserError(_("The discount journal must belong to the same company as the cheque."))
        if self.fees_amount < 0:
            raise UserError(_("Bank fees cannot be negative."))
        if self.fees_amount >= payment.amount:
            raise UserError(_("Bank fees cannot exceed the cheque amount."))
        if self.fees_amount and not self.fees_account_id:
            raise UserError(_("Select a fees account or set the fees to zero."))

        move = payment._create_cheque_discount_entry(
            self.discount_journal_id, self.fees_account_id, self.fees_amount, self.discount_date)
        payment.write({
            'cheque_discount_date': self.discount_date,
            'cheque_discount_journal_id': self.discount_journal_id.id,
            'cheque_discount_fees': self.fees_amount,
            'cheque_discount_move_id': move.id,
        })
        payment.message_post(body=_(
            "Cheque <b>Discounted</b> (توريق) on %(date)s in %(journal)s.<br/>"
            "Net collected: %(net)s %(currency)s — fees: %(fees)s %(currency)s.<br/>"
            "Entry: %(move)s. If the cheque bounces later, use 'Mark as Bounced' "
            "to book the recourse against the customer.",
            date=fields.Date.to_string(self.discount_date),
            journal=self.discount_journal_id.display_name,
            net=payment.amount - self.fees_amount,
            fees=self.fees_amount,
            currency=payment.currency_id.name,
            move=move.name))
        return {'type': 'ir.actions.act_window_close'}
