# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.pool import Pool
from .purchase import *
from .company import *
from .user import *

def register():
    Pool.register(
        Purchase,
        PurchaseLine,
        PurchasePaymentForm,
        Company,
        PrintReportPurchasesStart,
        User,
        module='nodux_purchase_one', type_='model')
    Pool.register(
        WizardPurchasePayment,
        PrintReportPurchases,
        module='nodux_purchase_one', type_='wizard')
    Pool.register(
        PurchaseReport,
        ReportPurchases,
        module='nodux_purchase_one', type_='report')
