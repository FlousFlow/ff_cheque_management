# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ChequeDepositWizard(models.TransientModel):
    _name = 'cheque.deposit.wizard'
    _description = 'Mark Cheque as Deposited'

    payment_id = fields.Many2one(
        comodel_name='account.payment', string="Cheque Payment",
        required=True, domain="[('is_cheque_payment', '=', True)]")
    deposit_date = fields.Date(
        string="Deposit Date", required=True,
        default=fields.Date.context_today)
    deposit_journal_id = fields.Many2one(
        comodel_name='account.journal', string="Deposit Bank Journal",
        required=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]")
    company_id = fields.Many2one(related='payment_id.company_id')
    currency_id = fields.Many2one(related='payment_id.currency_id')
    amount = fields.Monetary(related='payment_id.amount', currency_field='currency_id')

    def action_mark_deposited(self):
        self.ensure_one()
        payment = self.payment_id
        if not payment.is_cheque_payment:
            raise UserError(_("This payment is not a cheque payment."))
        if payment.payment_type != 'inbound':
            raise UserError(_("Only incoming cheques can be marked as deposited."))
        if payment.cheque_bounced:
            raise UserError(_("This cheque has already bounced."))
        if payment.state == 'canceled':
            raise UserError(_("This cheque payment has been cancelled."))
        if payment.is_matched:
            raise UserError(_("This cheque is already cleared through the bank reconciliation."))
        if payment.cheque_deposit_date:
            raise UserError(_("This cheque has already been marked as deposited on %s.",
                              payment.cheque_deposit_date))
        if self.deposit_journal_id.company_id != payment.company_id:
            raise UserError(_("The deposit journal must belong to the same company as the cheque."))

        payment.write({
            'cheque_deposit_date': self.deposit_date,
            'cheque_deposit_journal_id': self.deposit_journal_id.id,
        })
        payment.message_post(body=_(
            "Cheque marked as <b>Deposited</b> on %(date)s in %(journal)s.<br/>"
            "No accounting impact: the cheque remains awaiting collection through the "
            "bank reconciliation.",
            date=fields.Date.to_string(self.deposit_date),
            journal=self.deposit_journal_id.display_name))
        return {'type': 'ir.actions.act_window_close'}
