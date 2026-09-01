# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """Populate cheque payment method lines for already configured companies."""
    env['res.company'].search([])._sync_cheque_payment_method_lines()


def uninstall_hook(env):
    """Remove cheque payment method lines so no dangling record is left behind.

    The payment methods themselves are removed automatically with the module
    data (XML IDs). The standard `unlink()` of account.payment.method.line
    already detaches lines still used by payments instead of deleting them.
    """
    lines = env['account.payment.method.line'].with_context(active_test=False).search([
        ('payment_method_id.code', '=', 'ff_cheque'),
    ])
    lines.unlink()
