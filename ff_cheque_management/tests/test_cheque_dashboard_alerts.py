# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, tests

from .common import ChequeCommon


@tests.tagged('post_install', '-at_install')
class TestChequeDashboardAndAlerts(ChequeCommon):

    def test_new_from_issued_menu_defaults_to_cheque(self):
        """Creating a payment from the Issued Cheques menu is an outgoing
        cheque right away: outbound + supplier + cheque method line."""
        payment = self.env['account.payment'].with_context(
            default_payment_type='outbound',
            default_partner_type='supplier',
            ff_default_cheque=1,
        ).create({
            'partner_id': self.partner_a.id,
            'amount': 100.0,
            'journal_id': self.company_data['default_journal_bank'].id,
            **self._cheque_vals('CHK-NEW-OUT'),
        })
        self.assertEqual(payment.payment_type, 'outbound')
        self.assertEqual(payment.partner_type, 'supplier')
        self.assertEqual(payment.payment_method_line_id, self.cheque_outbound_line)
        self.assertTrue(payment.is_cheque_payment)
        # The received menu behaves the same way, on the inbound side.
        payment_in = self.env['account.payment'].with_context(
            default_payment_type='inbound',
            default_partner_type='customer',
            ff_default_cheque=1,
        ).create({
            'partner_id': self.partner_a.id,
            'amount': 100.0,
            'journal_id': self.company_data['default_journal_bank'].id,
            **self._cheque_vals('CHK-NEW-IN'),
        })
        self.assertEqual(payment_in.payment_method_line_id, self.cheque_inbound_line)

    def test_cron_due_alerts_lifecycle(self):
        """The cron keeps exactly one 'Cheque Due' activity per alerting
        cheque, skips non-alerting ones, and cleans up after clearing."""
        Payment = self.env['account.payment']
        activity_type = self.env.ref('ff_cheque_management.mail_activity_type_cheque_due')

        def cheque_with_due(days):
            invoice = self._create_invoice('out_invoice', self.partner_a, 300.0)
            return self._register_cheque(
                invoice, **self._cheque_vals(f'CHK-ALERT-{days}', due_in_days=days))

        due_soon = cheque_with_due(5)
        due_later = cheque_with_due(40)

        Payment._cron_cheque_due_alerts()

        activities = Payment._cron_cheque_due_alerts() and self.env['mail.activity'].search([
            ('res_model', '=', 'account.payment'),
            ('activity_type_id', '=', activity_type.id),
        ])
        self.assertEqual(len(activities.filtered(lambda a: a.res_id == due_soon.id)), 1)
        self.assertFalse(activities.filtered(lambda a: a.res_id == due_later.id))
        # Idempotent: running twice never duplicates.
        self.assertEqual(len(activities), 1)

        # After the cheque is cleared, the alert is removed by the next run.
        self._match_with_bank_statement(due_soon, amount=300.0)
        Payment._cron_cheque_due_alerts()
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'account.payment'),
            ('activity_type_id', '=', activity_type.id),
        ])
        self.assertFalse(activities.filtered(lambda a: a.res_id == due_soon.id))

    def test_cron_alert_overdue_summary(self):
        """An overdue cheque gets an OVERDUE summary and today's deadline."""
        invoice = self._create_invoice('out_invoice', self.partner_a, 300.0)
        payment = self._register_cheque(
            invoice, **self._cheque_vals('CHK-ALERT-LATE', due_in_days=-2))
        self.env['account.payment']._cron_cheque_due_alerts()

        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'account.payment'),
            ('res_id', '=', payment.id),
        ])
        self.assertEqual(len(activity), 1)
        self.assertIn('OVERDUE', activity.summary)
        self.assertEqual(activity.date_deadline, fields.Date.today())
