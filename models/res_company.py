# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    incoming_cheque_account_id = fields.Many2one(
        comodel_name='account.account', string="Incoming Cheques Account",
        copy=False, tracking=True,
        domain="[('deprecated', '=', False)]",
        help="Account where cheques received from customers are parked until they are "
             "collected through bank reconciliation (e.g. Cheques Under Collection). "
             "Must be reconcilable.")
    outgoing_cheque_account_id = fields.Many2one(
        comodel_name='account.account', string="Outgoing Cheques Account",
        copy=False, tracking=True,
        domain="[('deprecated', '=', False)]",
        help="Account where cheques issued to vendors are parked until they are cashed "
             "through bank reconciliation (e.g. Issued Cheques / Cheques Payable). "
             "Must be reconcilable.")

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    @api.constrains('incoming_cheque_account_id', 'outgoing_cheque_account_id')
    def _check_cheque_accounts(self):
        for company in self:
            for field_name, label in (
                ('incoming_cheque_account_id', _("Incoming Cheques Account")),
                ('outgoing_cheque_account_id', _("Outgoing Cheques Account")),
            ):
                account = company[field_name]
                if not account:
                    continue
                # Note: in Odoo 18 account.account is company-independent (the
                # chart is shared between companies). Isolation comes from each
                # company configuring its own accounts and journals, so there
                # is no company check on the account itself.
                if account.deprecated:
                    raise ValidationError(_(
                        "The %s (%s) is deprecated and cannot be used.",
                        label, account.display_name))
                if account.account_type in ('asset_receivable', 'liability_payable'):
                    raise ValidationError(_(
                        "The %s cannot be a receivable or payable account (%s).",
                        label, account.display_name))
                if not account.reconcile:
                    raise ValidationError(_(
                        "The %s (%s) must be set as reconcilable: cheques stay 'In Process' "
                        "on this account until the bank reconciliation clears them.",
                        label, account.display_name))
                if account in self.env['account.journal'].search([
                    *self.env['account.journal']._check_company_domain(company),
                    ('type', 'in', ('bank', 'cash', 'credit')),
                ]).default_account_id:
                    raise ValidationError(_(
                        "The %s cannot be the default account of a bank, cash or credit journal (%s).",
                        label, account.display_name))

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------

    def write(self, vals):
        res = super().write(vals)
        if 'incoming_cheque_account_id' in vals or 'outgoing_cheque_account_id' in vals:
            # Keep the standard payment method lines in sync with the settings.
            self._sync_cheque_payment_method_lines()
        return res

    def _sync_cheque_payment_method_lines(self, journals=None):
        """Create/update the cheque payment method lines on bank journals.

        The company settings are only a configuration layer: the payment method
        line `payment_account_id` stays the accounting source of truth when
        creating payments.

        :param journals: optional restriction to specific bank journals.
        Idempotent: running it several times never creates duplicates.
        """
        methods = {
            'inbound': self.env.ref('ff_cheque_management.payment_method_ff_cheque_inbound', raise_if_not_found=False),
            'outbound': self.env.ref('ff_cheque_management.payment_method_ff_cheque_outbound', raise_if_not_found=False),
        }
        if not all(methods.values()):
            return
        for company in self:
            accounts = {
                'inbound': company.incoming_cheque_account_id,
                'outbound': company.outgoing_cheque_account_id,
            }
            journal_domain = [
                *self.env['account.journal']._check_company_domain(company),
                ('type', '=', 'bank'),
            ]
            company_journals = (self.env['account.journal'].search(journal_domain) if journals is None
                                else journals.filtered(lambda j, co=company: j.type == 'bank' and j.company_id == co))
            for payment_type in ('inbound', 'outbound'):
                account = accounts[payment_type]
                for journal in company_journals:
                    cheque_method = methods[payment_type]
                    existing_lines = journal[f'{payment_type}_payment_method_line_ids'].filtered(
                        lambda line, method=cheque_method: line.payment_method_id == method)
                    if account:
                        if existing_lines:
                            existing_lines.filtered(
                                lambda line, acc=account: line.payment_account_id != acc
                            ).payment_account_id = account
                        else:
                            self.env['account.payment.method.line'].create({
                                'name': methods[payment_type].name,
                                'payment_method_id': methods[payment_type].id,
                                'journal_id': journal.id,
                                'payment_account_id': account.id,
                            })
                    else:
                        # No account configured: remove the lines unless payments
                        # still reference them (standard unlink keeps those and
                        # only detaches the journal).
                        existing_lines.unlink()


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)
        journals.filtered(lambda journal: journal.type == 'bank').company_id\
            ._sync_cheque_payment_method_lines(journals)
        return journals

    def write(self, vals):
        res = super().write(vals)
        if vals.get('type') == 'bank' or 'currency_id' in vals:
            for company in self.mapped('company_id'):
                company._sync_cheque_payment_method_lines(
                    self.filtered(lambda j, co=company: j.company_id == co))
        return res

    def _default_inbound_payment_methods(self):
        # OVERRIDE: every bank journal automatically gets the incoming cheque
        # method line, managed by the standard journal compute. Only once the
        # company configured its cheque account, so no line can ever point to
        # a missing outstanding account.
        methods = super()._default_inbound_payment_methods()
        if self.type == 'bank' and self.company_id.incoming_cheque_account_id:
            methods |= self.env.ref('ff_cheque_management.payment_method_ff_cheque_inbound', raise_if_not_found=False)
        return methods

    def _default_outbound_payment_methods(self):
        # OVERRIDE: every bank journal automatically gets the outgoing cheque
        # method line, managed by the standard journal compute. Only once the
        # company configured its cheque account, so no line can ever point to
        # a missing outstanding account.
        methods = super()._default_outbound_payment_methods()
        if self.type == 'bank' and self.company_id.outgoing_cheque_account_id:
            methods |= self.env.ref('ff_cheque_management.payment_method_ff_cheque_outbound', raise_if_not_found=False)
        return methods
