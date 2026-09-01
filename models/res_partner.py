# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    cheque_count = fields.Integer(
        string="Cheques", compute='_compute_cheque_count')

    def _get_cheque_payments_domain(self):
        self.ensure_one()
        return [
            '|',
            ('cheque_partner_id', '=', self.id),
            '&',
            ('is_cheque_payment', '=', True),
            ('partner_id', '=', self.id),
        ]

    def _compute_cheque_count(self):
        for partner in self:
            partner.cheque_count = self.env['account.payment'].search_count(
                partner._get_cheque_payments_domain())

    def action_view_cheque_payments(self):
        self.ensure_one()
        return {
            'name': _("Cheques"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form,kanban,graph,pivot',
            'search_view_id': self.env.ref('ff_cheque_management.ff_cheque_payment_search').id,
            'domain': self._get_cheque_payments_domain(),
            'context': {
                'list_view_ref': 'ff_cheque_management.ff_cheque_received_list',
            },
        }
