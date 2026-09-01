# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError

# Stable technical code used to detect cheque payments. Never rely on the
# payment method *name* (it is translatable and editable).
CHEQUE_PAYMENT_METHOD_CODE = 'ff_cheque'

TERMINAL_CHEQUE_STATUSES = ('cleared', 'discounted', 'endorsed', 'bounced', 'cancelled')

# Cheque details are frozen once the payment is confirmed.
CHEQUE_DETAIL_FIELDS = (
    'cheque_number', 'cheque_bank_id', 'cheque_date', 'cheque_due_date', 'cheque_drawer_name',
)

# Context flag used by the cheque menus so a manually created payment picks
# the cheque method line (and shows the Cheque tab) right away.
FF_DEFAULT_CHEQUE_CONTEXT_KEY = 'ff_default_cheque'


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    is_cheque_payment = fields.Boolean(
        string="Is Cheque Payment",
        compute='_compute_is_cheque_payment', store=True,
        help="Technical field, True when the selected payment method uses the cheque code.")
    cheque_number = fields.Char(
        string="Cheque Number", index='btree', tracking=True, copy=False)
    cheque_bank_id = fields.Many2one(
        comodel_name='res.bank', string="Cheque Bank",
        index='btree', tracking=True,
        help="The bank the cheque is drawn on.")
    cheque_date = fields.Date(
        string="Cheque Date", tracking=True, copy=False,
        default=lambda self: fields.Date.context_today(self),
        help="Incoming: date the cheque was received. Outgoing: date the cheque was issued.")
    cheque_due_date = fields.Date(
        string="Cheque Due Date", index='btree', tracking=True, copy=False,
        help="Also used as the date maturity of the cheque account journal item.")
    cheque_drawer_name = fields.Char(
        string="Drawer Name", tracking=True, copy=False,
        help="Incoming: the customer who gave the cheque. Outgoing: the company issuing the cheque.")
    cheque_notes = fields.Text(string="Cheque Notes", copy=False)
    cheque_deposit_date = fields.Date(
        string="Deposit Date", tracking=True, copy=False,
        help="Filled by 'Mark as Deposited'. Operational tracking only, no accounting impact.")
    cheque_deposit_journal_id = fields.Many2one(
        comodel_name='account.journal', string="Deposit Bank Journal",
        check_company=True, copy=False,
        help="Bank journal where the cheque was deposited. Tracking only.")
    cheque_bounced = fields.Boolean(string="Cheque Bounced", copy=False)
    cheque_bounce_date = fields.Date(string="Bounce Date", copy=False)
    cheque_bounce_reason = fields.Text(string="Bounce Reason", tracking=True, copy=False)
    cheque_bounce_move_id = fields.Many2one(
        comodel_name='account.move', string="Bounce Recourse Entry", copy=False,
        help="Recourse journal entry created when an already settled cheque "
             "(cleared, discounted or endorsed) bounces.")
    cheque_partner_id = fields.Many2one(
        comodel_name='res.partner', string="Drawer (Partner)",
        tracking=True, copy=False, check_company=True,
        help="Partner behind the cheque. Defaults to the customer/vendor; "
             "change it for third-party cheques (شيكات جهة خارجية).")
    cheque_discount_date = fields.Date(string="Discount Date", copy=False)
    cheque_discount_journal_id = fields.Many2one(
        comodel_name='account.journal', string="Discount Bank Journal",
        check_company=True, copy=False)
    cheque_discount_fees = fields.Monetary(
        string="Discount Fees", currency_field='currency_id', copy=False,
        help="Bank commission and interest charged when discounting the cheque.")
    cheque_discount_move_id = fields.Many2one(
        comodel_name='account.move', string="Discount Entry", copy=False)
    cheque_endorsed_partner_id = fields.Many2one(
        comodel_name='res.partner', string="Endorsed To", check_company=True, copy=False,
        help="Vendor the cheque was endorsed to.")
    cheque_endorsed_move_id = fields.Many2one(
        comodel_name='account.move', string="Endorsement Entry", copy=False)
    cheque_status = fields.Selection(
        selection=[
            ('received', "Received"),
            ('deposited', "Deposited"),
            ('cleared', "Cleared"),
            ('discounted', "Discounted"),
            ('endorsed', "Endorsed"),
            ('bounced', "Bounced"),
            ('cancelled', "Cancelled"),
            ('issued', "Issued"),
        ],
        string="Cheque Status",
        compute='_compute_cheque_status', store=True,
        help="Derived from the payment state, bank matching and the cheque lifecycle. "
             "A cheque is only 'Cleared' once it has been matched through bank reconciliation. "
             "'Discounted' (توريق) and 'Endorsed' (تظهير) are post-issuance transfers of the cheque.")
    cheque_maturity_status = fields.Selection(
        selection=[
            ('not_due', "Not Due"),
            ('due_today', "Due Today"),
            ('overdue', "Overdue"),
            ('settled', "Settled"),
        ],
        string="Maturity Status",
        compute='_compute_cheque_maturity_status',
        help="Based on the cheque due date compared to today.")
    days_to_maturity = fields.Integer(
        string="Days To Maturity",
        compute='_compute_cheque_maturity_status',
        help="Days remaining until the cheque due date. Negative when overdue.")
    cheque_duplicate_ids = fields.Many2many(
        comodel_name='account.payment', string="Similar Cheques",
        compute='_compute_cheque_duplicate_ids',
        help="Cheques already registered with the same number, bank and payment type.")

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('payment_method_line_id.payment_method_id.code')
    def _compute_is_cheque_payment(self):
        for payment in self:
            payment.is_cheque_payment = payment.payment_method_line_id.code == CHEQUE_PAYMENT_METHOD_CODE

    @api.depends('state', 'is_matched', 'is_cheque_payment', 'cheque_bounced', 'cheque_deposit_date',
                 'payment_type', 'cheque_discount_move_id', 'cheque_endorsed_move_id')
    def _compute_cheque_status(self):
        for payment in self:
            if not payment.is_cheque_payment:
                payment.cheque_status = False
            elif payment.cheque_bounced:
                # Bounced wins over 'cancelled' because the bounce flow cancels
                # the payment through the standard mechanism.
                payment.cheque_status = 'bounced'
            elif payment.state in ('canceled', 'rejected'):
                payment.cheque_status = 'cancelled'
            elif payment.cheque_discount_move_id:
                payment.cheque_status = 'discounted'
            elif payment.cheque_endorsed_move_id:
                payment.cheque_status = 'endorsed'
            elif payment.is_matched:
                payment.cheque_status = 'cleared'
            elif payment.payment_type == 'inbound':
                payment.cheque_status = 'deposited' if payment.cheque_deposit_date else 'received'
            else:
                payment.cheque_status = 'issued'

    @api.depends('is_cheque_payment', 'cheque_due_date', 'cheque_status')
    def _compute_cheque_maturity_status(self):
        today = fields.Date.context_today(self)
        for payment in self:
            if not payment.is_cheque_payment:
                payment.cheque_maturity_status = False
                payment.days_to_maturity = 0
            elif payment.cheque_status in TERMINAL_CHEQUE_STATUSES:
                payment.cheque_maturity_status = 'settled'
                payment.days_to_maturity = 0
            elif not payment.cheque_due_date:
                payment.cheque_maturity_status = False
                payment.days_to_maturity = 0
            else:
                delta = (payment.cheque_due_date - today).days
                payment.days_to_maturity = delta
                if delta > 0:
                    payment.cheque_maturity_status = 'not_due'
                elif delta == 0:
                    payment.cheque_maturity_status = 'due_today'
                else:
                    payment.cheque_maturity_status = 'overdue'

    @api.depends('is_cheque_payment', 'cheque_number', 'cheque_bank_id', 'payment_type', 'company_id')
    def _compute_cheque_duplicate_ids(self):
        for payment in self:
            if not payment.is_cheque_payment or not payment.cheque_number or not payment.cheque_bank_id:
                payment.cheque_duplicate_ids = False
                continue
            payment.cheque_duplicate_ids = self.search([
                ('is_cheque_payment', '=', True),
                ('cheque_number', '=', payment.cheque_number),
                ('cheque_bank_id', '=', payment.cheque_bank_id.id),
                ('payment_type', '=', payment.payment_type),
                ('company_id', '=', payment.company_id.id),
                ('state', '!=', 'canceled'),
                ('id', '!=', payment._origin.id),
            ])

    @api.depends('available_payment_method_line_ids')
    def _compute_payment_method_line_id(self):
        """OVERRIDE: the cheque menus create payments that are cheques by
        design, so prefer the cheque method line over the partner/manual
        default when the `ff_default_cheque` context flag is set."""
        super()._compute_payment_method_line_id()
        for pay in self:
            if (
                not pay.payment_method_line_id
                or pay.payment_method_line_id.code == CHEQUE_PAYMENT_METHOD_CODE
                or not pay.env.context.get(FF_DEFAULT_CHEQUE_CONTEXT_KEY)
            ):
                continue
            cheque_lines = pay.available_payment_method_line_ids.filtered(
                lambda line, code=CHEQUE_PAYMENT_METHOD_CODE: line.code == code)
            if cheque_lines:
                pay.payment_method_line_id = cheque_lines[0]._origin

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    @api.constrains('payment_method_line_id', 'cheque_number', 'cheque_bank_id', 'cheque_due_date')
    def _check_cheque_required_fields(self):
        for payment in self:
            if not payment.is_cheque_payment:
                continue
            missing = []
            if not payment.cheque_number:
                missing.append(_("Cheque Number"))
            if not payment.cheque_bank_id:
                missing.append(_("Bank"))
            if not payment.cheque_due_date:
                missing.append(_("Cheque Due Date"))
            if missing:
                raise ValidationError(_(
                    "The following cheque details are required on cheque payment %s: %s.",
                    payment.display_name, ", ".join(missing),
                ))

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange('date')
    def _onchange_date_cheque_date(self):
        """Default the cheque date to the payment date."""
        if self.is_cheque_payment and self.date and not self.cheque_date:
            self.cheque_date = self.date

    @api.onchange('partner_id', 'company_id', 'payment_type')
    def _onchange_cheque_drawer_name(self):
        if not self.is_cheque_payment or self.cheque_drawer_name:
            return
        if self.payment_type == 'inbound' and self.partner_id:
            self.cheque_drawer_name = self.partner_id.name
        elif self.payment_type == 'outbound':
            self.cheque_drawer_name = self.company_id.name

    @api.onchange('journal_id', 'payment_type')
    def _onchange_cheque_bank_id(self):
        """For outgoing cheques, default the bank to the journal's own bank."""
        if self.is_cheque_payment and self.payment_type == 'outbound' and not self.cheque_bank_id:
            self.cheque_bank_id = self.journal_id.bank_id

    @api.onchange('partner_id', 'payment_type')
    def _onchange_cheque_partner_id(self):
        """Default the drawer partner to the payment partner; change it for
        third-party cheques (شيكات جهة خارجية)."""
        if self.is_cheque_payment and not self.cheque_partner_id and self.partner_id:
            self.cheque_partner_id = self.partner_id

    # -------------------------------------------------------------------------
    # LOW-LEVEL METHODS
    # -------------------------------------------------------------------------

    def write(self, vals):
        # OVERRIDE: freeze the cheque details once the payment is confirmed so
        # the journal entry (already carrying the due date as maturity) cannot
        # diverge from the cheque record.
        if (
            any(field_name in vals for field_name in CHEQUE_DETAIL_FIELDS)
            and any(payment.is_cheque_payment and payment.state in ('in_process', 'paid') for payment in self)
        ):
            raise UserError(_(
                "Cheque details cannot be modified after the payment is confirmed. "
                "Cancel the payment and register a new cheque instead."))
        return super().write(vals)

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------

    def action_open_cheque_deposit_wizard(self):
        self.ensure_one()
        return {
            'name': _("Mark as Deposited"),
            'type': 'ir.actions.act_window',
            'res_model': 'cheque.deposit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_id': self.id,
            },
        }

    def action_open_cheque_bounce_wizard(self):
        self.ensure_one()
        return {
            'name': _("Mark as Bounced"),
            'type': 'ir.actions.act_window',
            'res_model': 'cheque.bounce.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_id': self.id,
            },
        }

    def action_open_cheque_discount_wizard(self):
        self.ensure_one()
        return {
            'name': _("Discount Cheque"),
            'type': 'ir.actions.act_window',
            'res_model': 'cheque.discount.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_id': self.id,
            },
        }

    def action_open_cheque_endorse_wizard(self):
        self.ensure_one()
        return {
            'name': _("Endorse Cheque"),
            'type': 'ir.actions.act_window',
            'res_model': 'cheque.endorse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_id': self.id,
            },
        }

    # -------------------------------------------------------------------------
    # DISCOUNT / ENDORSE / RECOURSE ENTRIES
    # -------------------------------------------------------------------------

    def _cheque_get_general_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].search([
            *self.env['account.journal']._check_company_domain(self.company_id),
            ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_("No general journal found in company %s.", self.company_id.display_name))
        return journal

    def _create_cheque_discount_entry(self, discount_journal, fees_account, fees, discount_date):
        """توريق: hand the cheque to the bank and get paid today.

        Entry in the discount bank journal:
            Dr Bank (net) + Dr fees account / Cr cheques account
        The credit line is reconciled with the payment's liquidity line so the
        cheque account is freed while the payment keeps its audit trail.
        """
        self.ensure_one()
        if self.currency_id != self.company_id.currency_id:
            raise UserError(_("Cheque discounting is only available for cheques in the company currency."))
        bank_account = discount_journal.default_account_id
        cheque_account = self.outstanding_account_id
        net = self.amount - fees
        lines = [Command.create({
            'name': _("Cheque %s collected by bank", self.cheque_number),
            'partner_id': self.partner_id.id,
            'account_id': bank_account.id,
            'debit': net,
        })]
        if fees:
            lines.append(Command.create({
                'name': _("Bank fees on cheque %s", self.cheque_number),
                'account_id': fees_account.id,
                'debit': fees,
            }))
        lines.append(Command.create({
            'name': _("Cheque %s discounted", self.cheque_number),
            'partner_id': self.partner_id.id,
            'account_id': cheque_account.id,
            'credit': self.amount,
        }))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': discount_journal.id,
            'date': discount_date,
            'ref': _("Cheque discount %s - %s", self.cheque_number, self.partner_id.display_name),
            'line_ids': lines,
        })
        move.action_post()
        cheque_lines = move.line_ids.filtered(lambda line: line.account_id == cheque_account)
        liquidity_lines = self._seek_for_lines()[0].filtered(
            lambda line: line.account_id == cheque_account)
        (cheque_lines + liquidity_lines).reconcile()
        return move

    def _create_cheque_endorse_entry(self, vendor, endorse_date):
        """تظهير: hand the cheque to a vendor to settle a payable.

        Entry in the general journal:
            Dr Vendor Payable / Cr cheques account (reconciled)
        """
        self.ensure_one()
        journal = self._cheque_get_general_journal()
        payable_account = vendor.with_company(self.company_id).property_account_payable_id
        cheque_account = self.outstanding_account_id
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': endorse_date,
            'ref': _("Cheque endorsed to %s (%s)", vendor.display_name, self.cheque_number),
            'line_ids': [
                Command.create({
                    'name': _("Cheque %s received by endorsement", self.cheque_number),
                    'partner_id': vendor.id,
                    'account_id': payable_account.id,
                    'debit': self.amount,
                }),
                Command.create({
                    'name': _("Cheque %s endorsed", self.cheque_number),
                    'partner_id': self.partner_id.id,
                    'account_id': cheque_account.id,
                    'credit': self.amount,
                }),
            ],
        })
        move.action_post()
        cheque_lines = move.line_ids.filtered(lambda line: line.account_id == cheque_account)
        liquidity_lines = self._seek_for_lines()[0].filtered(
            lambda line: line.account_id == cheque_account)
        (cheque_lines + liquidity_lines).reconcile()
        return move

    def _create_cheque_recourse_entry(self, bounce_date):
        """Recourse entry for a cheque that bounces AFTER leaving the cheque
        account (cleared through a statement, discounted or endorsed):

        * cleared  : Dr Receivable / Cr Bank  (bank took the money back)
        * discounted: Dr Receivable / Cr Bank (net) + Cr fees reversal
        * endorsed : Dr Receivable / Cr Vendor Payable (vendor returned it)
        * outbound : Dr Bank / Cr Vendor Payable (bank returned the cheque)

        The counterpart lines are reconciled with the original flow so no
        orphan open item is left behind.
        """
        self.ensure_one()
        company = self.company_id
        amount = self.amount
        partner = self.partner_id
        lines = []
        if self.payment_type == 'inbound':
            receivable_account = partner.with_company(company).property_account_receivable_id
            lines.append(Command.create({
                'name': _("Cheque %s bounced: %s is debited again", self.cheque_number, partner.display_name),
                'partner_id': partner.id,
                'account_id': receivable_account.id,
                'debit': amount,
            }))
            if self.cheque_discount_move_id:
                discount_journal = self.cheque_discount_journal_id
                bank_account = discount_journal.default_account_id
                discount_fees_line = self.cheque_discount_move_id.line_ids.filtered(
                    lambda line: line.debit
                    and line.account_id != bank_account
                    and line.account_id != self.outstanding_account_id)
                fees_amount = sum(discount_fees_line.mapped('debit'))
                lines.append(Command.create({
                    'name': _("Bank take-back on bounced cheque %s", self.cheque_number),
                    'account_id': bank_account.id,
                    'credit': amount - fees_amount,
                }))
                if discount_fees_line:
                    lines.append(Command.create({
                        'name': _("Fees returned on bounced cheque %s", self.cheque_number),
                        'account_id': discount_fees_line[0].account_id.id,
                        'credit': fees_amount,
                    }))
                journal = discount_journal
            elif self.cheque_endorsed_move_id:
                vendor = self.cheque_endorsed_partner_id
                payable_account = vendor.with_company(company).property_account_payable_id
                lines.append(Command.create({
                    'name': _("Endorsed cheque %s returned by %s", self.cheque_number, vendor.display_name),
                    'partner_id': vendor.id,
                    'account_id': payable_account.id,
                    'credit': amount,
                }))
                journal = self.cheque_endorsed_move_id.journal_id
            else:
                statement_lines = self.reconciled_statement_line_ids
                bank_journal = statement_lines.journal_id[:1] or self.journal_id
                bank_account = bank_journal.default_account_id
                lines.append(Command.create({
                    'name': _("Bank take-back on bounced cheque %s", self.cheque_number),
                    'account_id': bank_account.id,
                    'credit': amount,
                }))
                journal = bank_journal
        else:
            payable_account = partner.with_company(company).property_account_payable_id
            bank_account = self.journal_id.default_account_id
            lines = [
                Command.create({
                    'name': _("Bank returned cheque %s", self.cheque_number),
                    'account_id': bank_account.id,
                    'debit': amount,
                }),
                Command.create({
                    'name': _("Cheque %s bounced: %s is credited again", self.cheque_number, partner.display_name),
                    'partner_id': partner.id,
                    'account_id': payable_account.id,
                    'credit': amount,
                }),
            ]
            journal = self.journal_id

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': bounce_date,
            'ref': _("Recourse on bounced cheque %s", self.cheque_number),
            'line_ids': lines,
        })
        move.action_post()

        # Reconcile the recourse counterpart with the original flow so nothing
        # stays dangling: bank line against the statement bank line, bank/fees
        # lines against the discount entry, payable line against the
        # endorsement entry.
        counterpart_account_ids = set()
        for line in move.line_ids:
            if line.account_id.id in (
                partner.with_company(company).property_account_receivable_id.id,
                partner.with_company(company).property_account_payable_id.id,
            ):
                continue
            counterpart_account_ids.add(line.account_id.id)
        open_lines = self._cheque_recourse_counterpart_lines(move, counterpart_account_ids)
        profit_and_loss_types = ('income', 'income_other', 'expense', 'expense_direct_cost', 'expense_depreciation')
        for account_id, rec_lines in open_lines.items():
            account = self.env['account.account'].browse(account_id)
            if account.account_type in profit_and_loss_types:
                # P&L flows (e.g. discount fees) are not reconcilable: the
                # recourse simply books the reverse expense.
                continue
            counterpart_lines = self._cheque_original_counterpart_lines(account_id)
            (rec_lines + counterpart_lines).reconcile()
        return move

    def _cheque_recourse_counterpart_lines(self, move, account_ids):
        """Group the recourse entry's bank/fees/payable lines per account."""
        result = {}
        for line in move.line_ids.filtered(lambda l: l.account_id.id in account_ids):
            result.setdefault(line.account_id.id, self.env['account.move.line'])
            result[line.account_id.id] += line
        return result

    def _cheque_original_counterpart_lines(self, account_id):
        """Open original lines on `account_id` coming from the statement, the
        discount entry or the endorsement entry of this payment."""
        domain_move_ids = []
        if self.cheque_discount_move_id:
            domain_move_ids.append(self.cheque_discount_move_id.id)
        if self.cheque_endorsed_move_id:
            domain_move_ids.append(self.cheque_endorsed_move_id.id)
        origin_lines = self.env['account.move.line'].search([
            ('move_id', 'in', domain_move_ids),
            ('account_id', '=', account_id),
        ])
        statement_lines = self.reconciled_statement_line_ids.move_id.line_ids.filtered(
            lambda line: line.account_id.id == account_id)
        return (origin_lines + statement_lines).filtered(lambda line: not line.reconciled)

    # -------------------------------------------------------------------------
    # DUE DATE ALERTS
    # -------------------------------------------------------------------------

    @api.model
    def _cron_cheque_due_alerts(self, alert_days=7):
        """Daily cron: keep a 'Cheque Due' activity on every outstanding cheque
        whose due date is within `alert_days` (or overdue), assigned to the
        company's Accounting Administrators. Activities of cheques that left
        the alert window (cleared, bounced, cancelled, postponed) are removed,
        so the activity list always mirrors reality. Idempotent by design.
        """
        today = fields.Date.context_today(self)
        cheques = self.search([
            ('is_cheque_payment', '=', True),
            ('state', 'not in', ('canceled', 'rejected')),
            ('cheque_bounced', '=', False),
            ('is_matched', '=', False),
            ('cheque_due_date', '<=', today + timedelta(days=alert_days)),
        ])
        activity_type = self.env.ref(
            'ff_cheque_management.mail_activity_type_cheque_due')
        existing_activities = self.env['mail.activity'].search([
            ('res_model', '=', self._name),
            ('activity_type_id', '=', activity_type.id),
        ])
        payments_with_activity = set(existing_activities.mapped('res_id'))

        # One active manager per company, computed once (no search in loop).
        managers = self.env.ref('account.group_account_manager').users.filtered('active')
        manager_by_company = {
            company: (managers.filtered(lambda u, co=company: co in u.company_ids)[:1]
                      or managers[:1])
            for company in cheques.company_id
        }

        activities_vals = []
        for cheque in cheques.filtered(lambda c: c.id not in payments_with_activity):
            days = (cheque.cheque_due_date - today).days
            if days < 0:
                summary = _("Cheque %s is OVERDUE since %s (%s day(s))",
                            cheque.cheque_number, fields.Date.to_string(cheque.cheque_due_date), -days)
            elif days == 0:
                summary = _("Cheque %s is DUE TODAY (%s)",
                            cheque.cheque_number, fields.Date.to_string(cheque.cheque_due_date))
            else:
                summary = _("Cheque %s is due on %s (in %s day(s))",
                            cheque.cheque_number, fields.Date.to_string(cheque.cheque_due_date), days)
            activities_vals.append({
                'res_model_id': self.env['ir.model']._get_id(self._name),
                'res_id': cheque.id,
                'activity_type_id': activity_type.id,
                'summary': summary,
                'user_id': manager_by_company[cheque.company_id].id,
                'date_deadline': max(cheque.cheque_due_date, today),
            })
        self.env['mail.activity'].create(activities_vals)

        # Drop activities of cheques that no longer qualify (cleared, bounced,
        # cancelled, or due date moved beyond the alert window).
        (existing_activities - existing_activities.filtered(
            lambda activity: activity.res_id in cheques.ids
        )).unlink()
        return True

    # -------------------------------------------------------------------------
    # ACCOUNTING HOOKS
    # -------------------------------------------------------------------------

    def _prepare_move_liquidity_lines(self, default_values):
        # OVERRIDE: a cheque is only due at its due date, not at the payment date.
        lines = super()._prepare_move_liquidity_lines(default_values)
        if self.is_cheque_payment and self.cheque_due_date:
            for line_vals in lines:
                line_vals['date_maturity'] = self.cheque_due_date
        return lines

    def _get_payment_method_codes_to_exclude(self):
        # OVERRIDE: cheque methods only make sense on bank journals; the method
        # lines are never created on cash journals anyway, this is a safety net.
        codes = super()._get_payment_method_codes_to_exclude()
        if self.journal_id.type == 'cash':
            codes = [*codes, CHEQUE_PAYMENT_METHOD_CODE]
        return codes
