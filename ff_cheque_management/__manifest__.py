# -*- coding: utf-8 -*-
# Part of ff_cheque_management. See LICENSE file for full copyright and licensing details.
{
    'name': 'Egyptian Cheque Management',
    'version': '18.0.1.2.0',
    'category': 'Accounting/Accounting',
    'summary': 'Manage incoming and outgoing cheques inside the standard Odoo payments and bank reconciliation flow.',
    'description': """
Egyptian Cheque Management adds professional cheque support (incoming from
customers, outgoing to vendors) on top of the standard account.payment flow:
cheque details on the Register Payment wizard, due-date driven maturity,
operating deposit tracking, automatic clearing through the standard bank
reconciliation and an accounting-sound bounce flow. One cheque is always one
account.payment using the standard outstanding accounts, so reconciliation,
partial payments, audit trail and bank matching keep working exactly as in
vanilla Odoo. See the module page (static/description/index.html) for the
full feature list.
    """,
    'author': 'FlousFlow',
    'website': 'https://github.com/FlousFlow',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'data/payment_method_data.xml',
        'data/cheque_cron_data.xml',
        'security/ir.model.access.csv',
        'views/account_payment_views.xml',
        'views/account_payment_register_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/cheque_menu_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
