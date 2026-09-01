# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.ff_cheque_management.models.account_payment import CHEQUE_PAYMENT_METHOD_CODE


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    is_cheque_payment = fields.Boolean(
        string="Is Cheque Payment", compute='_compute_is_cheque_payment',
        help="Technical field, True when the selected payment method uses the cheque code.")
    cheque_number = fields.Char(string="Cheque Number")
    cheque_bank_id = fields.Many2one(
        comodel_name='res.bank', string="Bank",
        help="The bank the cheque is drawn on.")
    cheque_date = fields.Date(
        string="Cheque Date", compute='_compute_cheque_date', store=True, readonly=False,
        help="Defaults to the payment date.")
    cheque_due_date = fields.Date(string="Cheque Due Date")
    cheque_drawer_name = fields.Char(
        string="Drawer", compute='_compute_cheque_drawer_name', store=True, readonly=False,
        help="Incoming: the customer who gave the cheque. Outgoing: the company issuing the cheque.")
    cheque_partner_id = fields.Many2one(
        comodel_name='res.partner', string="Drawer (Partner)",
        help="Partner behind the cheque; defaults to the customer/vendor. "
             "Change it for third-party cheques.")
    cheque_notes = fields.Text(string="Notes")
    cheque_duplicate_ids = fields.Many2many(
        comodel_name='account.payment', string="Similar Cheques",
        compute='_compute_cheque_duplicate_ids')

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('payment_method_line_id.payment_method_id.code')
    def _compute_is_cheque_payment(self):
        for wizard in self:
            wizard.is_cheque_payment = wizard.payment_method_line_id.code == CHEQUE_PAYMENT_METHOD_CODE

    @api.depends('payment_date')
    def _compute_cheque_date(self):
        for wizard in self:
            if not wizard.cheque_date:
                wizard.cheque_date = wizard.payment_date

    @api.depends('partner_id', 'payment_type', 'company_id', 'cheque_date')
    def _compute_cheque_drawer_name(self):
        for wizard in self:
            if wizard.cheque_drawer_name:
                continue
            if wizard.payment_type == 'inbound' and wizard.partner_id:
                wizard.cheque_drawer_name = wizard.partner_id.name
            elif wizard.payment_type == 'outbound':
                wizard.cheque_drawer_name = wizard.company_id.name
            else:
                wizard.cheque_drawer_name = False

    @api.depends('is_cheque_payment', 'cheque_number', 'cheque_bank_id', 'payment_type', 'company_id')
    def _compute_cheque_duplicate_ids(self):
        for wizard in self:
            if not wizard.is_cheque_payment or not wizard.cheque_number or not wizard.cheque_bank_id:
                wizard.cheque_duplicate_ids = False
                continue
            wizard.cheque_duplicate_ids = self.env['account.payment'].search([
                ('is_cheque_payment', '=', True),
                ('cheque_number', '=', wizard.cheque_number),
                ('cheque_bank_id', '=', wizard.cheque_bank_id.id),
                ('payment_type', '=', wizard.payment_type),
                ('company_id', '=', wizard.company_id.id),
                ('state', '!=', 'canceled'),
            ])

    # -------------------------------------------------------------------------
    # LOW-LEVEL METHODS
    # -------------------------------------------------------------------------

    def _get_missing_cheque_labels(self):
        self.ensure_one()
        missing = []
        if not self.cheque_number:
            missing.append(_("Cheque Number"))
        if not self.cheque_bank_id:
            missing.append(_("Bank"))
        if not self.cheque_due_date:
            missing.append(_("Cheque Due Date"))
        return missing

    def _create_payment_vals_from_wizard(self, batch_result):
        # OVERRIDE: carry the cheque details to the payment.
        payment_vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.is_cheque_payment:
            payment_vals.update({
                'cheque_number': self.cheque_number,
                'cheque_bank_id': self.cheque_bank_id.id,
                'cheque_date': self.cheque_date or self.payment_date,
                'cheque_due_date': self.cheque_due_date,
                'cheque_drawer_name': self.cheque_drawer_name,
                'cheque_partner_id': self.cheque_partner_id.id or self.partner_id.id,
                'cheque_notes': self.cheque_notes,
            })
        return payment_vals

    def _create_payment_vals_from_batch(self, batch_result):
        # OVERRIDE: one cheque = one payment. Reaching this helper means several
        # payments would be created from the wizard while a single set of cheque
        # details can only describe one cheque.
        if self.is_cheque_payment:
            raise UserError(_(
                "One cheque must match exactly one payment. Register one cheque at a time "
                "by selecting a single document, or enable 'Group Payments' to pay several "
                "documents with the same cheque."))
        return super()._create_payment_vals_from_batch(batch_result)

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------

    def action_create_payments(self):
        # OVERRIDE: enforce the cheque details whatever the calling path.
        if self.is_cheque_payment and self.can_edit_wizard:
            missing = self._get_missing_cheque_labels()
            if missing:
                raise UserError(_(
                    "The following cheque details are required: %s.",
                    ", ".join(missing)))
        return super().action_create_payments()
