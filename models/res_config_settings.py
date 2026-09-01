# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    incoming_cheque_account_id = fields.Many2one(
        related='company_id.incoming_cheque_account_id', readonly=False,
        string="Incoming Cheques Account",
        domain="[('deprecated', '=', False)]")
    outgoing_cheque_account_id = fields.Many2one(
        related='company_id.outgoing_cheque_account_id', readonly=False,
        string="Outgoing Cheques Account",
        domain="[('deprecated', '=', False)]")
