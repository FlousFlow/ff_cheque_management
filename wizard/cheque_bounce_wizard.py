# -*- coding: utf-8 -*-
from markupsafe import escape

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class ChequeBounceWizard(models.TransientModel):
    _name = 'cheque.bounce.wizard'
    _description = 'Mark Cheque as Bounced'

    payment_id = fields.Many2one(
        comodel_name='account.payment', string="Cheque Payment",
        required=True, check_company=True,
        domain="[('is_cheque_payment', '=', True)]")
    bounce_date = fields.Date(
        string="Bounce Date", required=True,
        default=fields.Date.context_today)
    reason = fields.Text(string="Bounce Reason", required=True)
    company_id = fields.Many2one(related='payment_id.company_id')
    currency_id = fields.Many2one(related='payment_id.currency_id')
    amount = fields.Monetary(related='payment_id.amount', currency_field='currency_id')

    def action_mark_bounced(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only Accounting Administrators can mark a cheque as bounced."))
        payment = self.payment_id
        if not payment.is_cheque_payment:
            raise UserError(_("This payment is not a cheque payment."))
        if payment.cheque_bounced:
            raise UserError(_("This cheque has already been marked as bounced."))
        if payment.state == 'canceled':
            raise UserError(_("This cheque payment has already been cancelled."))

        if payment.cheque_status in ('cleared', 'discounted', 'endorsed'):
            # The cheque already left the cheques account: book the recourse
            # entry instead of cancelling (bank take-back / vendor return).
            move = payment._create_cheque_recourse_entry(self.bounce_date)
            payment.write({
                'cheque_bounced': True,
                'cheque_bounce_date': self.bounce_date,
                'cheque_bounce_reason': self.reason,
                'cheque_bounce_move_id': move.id,
            })
            payment.message_post(body=_(
                "Cheque marked as <b>Bounced</b> on %(date)s AFTER settlement.<br/>"
                "Reason: %(reason)s<br/>"
                "Recourse entry: %(move)s — the partner is debited again and the "
                "counterpart (bank / vendor) is restored.",
                date=fields.Date.to_string(self.bounce_date),
                reason=escape(self.reason),
                move=move.name))
            return {'type': 'ir.actions.act_window_close'}

        if payment.is_matched:
            raise UserError(_(
                "The cheque is already matched with a bank transaction. "
                "Unreconcile/reverse the bank transaction first."))

        if payment.move_id:
            # Detach every partial reconcile in the matching group (invoice
            # reconciliation, statement partials, FX exchange lines) so
            # cancelling restores the partner balance without orphans.
            payment.move_id.line_ids._all_reconciled_lines().remove_move_reconcile()
        # Standard Odoo cancellation: sets the payment to 'canceled' and
        # cancels (or unlinks when draft) the journal entry. No custom entry.
        payment.action_cancel()
        payment.write({
            'cheque_bounced': True,
            'cheque_bounce_date': self.bounce_date,
            'cheque_bounce_reason': self.reason,
        })
        payment.message_post(body=_(
            "Cheque marked as <b>Bounced</b> on %(date)s.<br/>"
            "Reason: %(reason)s<br/>"
            "The payment has been cancelled with the standard mechanism and all "
            "reconciliations have been removed: the partner balance is due again.",
            date=fields.Date.to_string(self.bounce_date),
            reason=escape(self.reason)))
        return {'type': 'ir.actions.act_window_close'}
