# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ChequeEndorseWizard(models.TransientModel):
    _name = 'cheque.endorse.wizard'
    _description = 'Endorse Cheque (تظهير)'

    payment_id = fields.Many2one(
        comodel_name='account.payment', string="Cheque Payment",
        required=True, check_company=True,
        domain="[('is_cheque_payment', '=', True)]")
    endorse_date = fields.Date(
        string="Endorsement Date", required=True,
        default=fields.Date.context_today)
    vendor_id = fields.Many2one(
        comodel_name='res.partner', string="Endorsed To (Vendor)",
        required=True,
        help="The vendor receiving the cheque to settle a payable.")
    company_id = fields.Many2one(related='payment_id.company_id')
    currency_id = fields.Many2one(related='payment_id.currency_id')
    amount = fields.Monetary(related='payment_id.amount', currency_field='currency_id')

    def action_endorse_cheque(self):
        self.ensure_one()
        payment = self.payment_id
        if not payment.is_cheque_payment:
            raise UserError(_("This payment is not a cheque payment."))
        if payment.payment_type != 'inbound':
            raise UserError(_("Only incoming cheques can be endorsed."))
        if payment.cheque_status not in ('received', 'deposited'):
            raise UserError(_("Only a Received or Deposited cheque can be endorsed (current status: %s).",
                              payment.cheque_status))
        if self.vendor_id == payment.partner_id:
            raise UserError(_("The cheque cannot be endorsed to the same partner who issued it."))

        move = payment._create_cheque_endorse_entry(self.vendor_id, self.endorse_date)
        payment.write({
            'cheque_endorsed_partner_id': self.vendor_id.id,
            'cheque_endorsed_move_id': move.id,
        })
        payment.message_post(body=_(
            "Cheque <b>Endorsed</b> (تظهير) on %(date)s to %(vendor)s.<br/>"
            "Entry: %(move)s. The vendor payable is settled with this cheque; "
            "if it bounces later, 'Mark as Bounced' books the recourse.",
            date=fields.Date.to_string(self.endorse_date),
            vendor=self.vendor_id.display_name,
            move=move.name))
        return {'type': 'ir.actions.act_window_close'}
