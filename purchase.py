#! -*- coding: utf8 -*-

# This file is part of purchase_pos module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
from datetime import datetime
from trytond.model import Workflow, ModelView, ModelSQL, fields
from trytond.pool import PoolMeta, Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, Not, If, PYSONEncoder, Id
from trytond.wizard import (Wizard, StateView, StateAction, StateTransition,
    Button)
from trytond.modules.company import CompanyReport
from trytond.pyson import If, Eval, Bool, PYSONEncoder, Id
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond.report import Report
conversor = None
try:
    from numword import numword_es
    conversor = numword_es.NumWordES()
except:
    print("Warning: Does not possible import numword module!")
    print("Please install it...!")
import pytz
from datetime import datetime,timedelta
import time

__all__ = ['Purchase', 'PurchaseLine','PurchasePaymentForm',
'WizardPurchasePayment', 'PurchaseReport', 'PrintReportPurchasesStart',
'PrintReportPurchases', 'ReportPurchases']
__metaclass__ = PoolMeta

_ZERO = Decimal(0)
_NOPAGOS = [
    ('1', '1 Pago'),
    ('2', '2 Pagos'),
    ('3', '3 Pagos'),
    ('4', '4 Pagos'),
]

class Purchase(Workflow, ModelSQL, ModelView):
    'Purchase'
    __name__ = 'purchase.purchase'
    _rec_name = 'reference'

    company = fields.Many2One('company.company', 'Company', required=True,
        states={
            'readonly': (Eval('state') != 'draft') | Eval('lines', [0]),
            },
        domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ],
        depends=['state'], select=True)
    reference = fields.Char('Number', readonly=True, select=True)
    description = fields.Char('Description',
        states={
            'readonly': Eval('state') != 'draft',
            },
        depends=['state'])
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('anulled', 'Anulled'),
    ], 'State', readonly=True, required=True)
    purchase_date = fields.Date('Purchase Date', required= True,
        states={
            'readonly': ~Eval('state').in_(['draft']),
            },
        depends=['state'])

    purchase_date_end = fields.Date('Purchase Date End', required=True,
        states={
            'readonly': ~Eval('state').in_(['draft']),
            },
        depends=['state'])

    party = fields.Many2One('party.party', 'Supplier', required=True, select=True,
        states={
            'readonly': ((Eval('state') != 'draft')),
            },
        depends=['state'])

    party_lang = fields.Function(fields.Char('Party Language'),
        'on_change_with_party_lang')

    currency = fields.Many2One('currency.currency', 'Currency', required=True,
        states={
            'readonly': (Eval('state') != 'draft') |
                (Eval('lines', [0]) & Eval('currency', 0)),
            },
        depends=['state'])
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    lines = fields.One2Many('purchase.line', 'purchase', 'Lines', states={
            'readonly': Eval('state') != 'draft',
            },
        depends=['party', 'state'])
    comment = fields.Text('Comment')
    untaxed_amount = fields.Function(fields.Numeric('Untaxed',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']), 'get_amount')
    untaxed_amount_cache = fields.Numeric('Untaxed Cache',
        digits=(16, Eval('currency_digits', 2)),
        readonly=True,
        depends=['currency_digits'])
    tax_amount = fields.Function(fields.Numeric('Tax',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']), 'get_amount')
    tax_amount_cache = fields.Numeric('Tax Cache',
        digits=(16, Eval('currency_digits', 2)),
        readonly=True,
        depends=['currency_digits'])
    total_amount = fields.Function(fields.Numeric('Total',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']), 'get_amount')
    total_amount_cache = fields.Numeric('Total Tax',
        digits=(16, Eval('currency_digits', 2)),
        readonly=True,
        depends=['currency_digits'])
    paid_amount = fields.Numeric('Paid Amount', readonly=True)
    residual_amount = fields.Numeric('Residual Amount', readonly=True)
    state_date = fields.Function(fields.Char('State dy Date', readonly=True), 'get_state_date')

    @classmethod
    def __register__(cls, module_name):
        cursor = Transaction().cursor
        sql_table = cls.__table__()

        super(Purchase, cls).__register__(module_name)
        cls._order.insert(0, ('purchase_date', 'DESC'))
        cls._order.insert(1, ('id', 'DESC'))


    @classmethod
    def __setup__(cls):
        super(Purchase, cls).__setup__()

        cls._transitions |= set((
                ('draft', 'confirmed'),
                ('draft', 'done'),
                ('confirmed', 'done'),
                ('done', 'anulled'),
                ))

        cls._buttons.update({
                'wizard_purchase_payment': {
                    'invisible': (Eval('state').in_(['done', 'anulled'])),
                    'readonly': Not(Bool(Eval('lines'))),
                    },
                'confirm': {
                    'invisible': Eval('state') != 'draft',
                    'readonly': ~Eval('lines', []),
                    },
                'anull': {
                    'invisible': (Eval('state').in_(['draft', 'anulled', 'confirm'])),
                    'readonly': Not(Bool(Eval('lines'))),
                    },

                })
        cls._states_cached = ['confirmed', 'done', 'cancel']

    @classmethod
    def copy(cls, purchases, default=None):
        if default is None:
            default = {}
        Date = Pool().get('ir.date')
        date = Date.today()

        default = default.copy()
        default['state'] = 'draft'
        default['reference'] = None
        default['paid_amount'] = Decimal(0.0)
        default['residual_amount'] = None
        default['purchase_date'] = date
        #default.setdefault('', None)
        return super(Purchase, cls).copy(purchases, default=default)

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_paid_amount():
        return Decimal(0.0)

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_currency():
        Company = Pool().get('company.company')
        company = Transaction().context.get('company')
        if company:
            return Company(company).currency.id

    @staticmethod
    def default_currency_digits():
        Company = Pool().get('company.company')
        company = Transaction().context.get('company')
        if company:
            return Company(company).currency.digits
        return 2

    @classmethod
    def get_state_date(cls, purchases, names):
        pool = Pool()
        Date = pool.get('ir.date')
        date = Date.today()
        result = {n: {p.id: Decimal(0) for p in purchases} for n in names}
        for name in names:
            for purchase in purchases:
                if purchase.purchase_date_end < date:
                    result[name][purchase.id] = 'vencida'
                else:
                    result[name][purchase.id] = ''

        return result

    @fields.depends('currency')
    def on_change_with_currency_digits(self, name=None):
        if self.currency:
            return self.currency.digits
        return 2

    @fields.depends('party')
    def on_change_with_party_lang(self, name=None):
        Config = Pool().get('ir.configuration')
        if self.party and self.party.lang:
            return self.party.lang.code
        return Config.get_language()

    @fields.depends('lines', 'currency', 'party')
    def on_change_lines(self):
        res = {
            'untaxed_amount': Decimal('0.0'),
            'tax_amount': Decimal('0.0'),
            'total_amount': Decimal('0.0'),
            }
        if self.lines:
            res['untaxed_amount'] = reduce(lambda x, y: x + y,
                [(getattr(l, 'amount', None) or Decimal(0))
                    for l in self.lines if l.type == 'line'], Decimal(0)
                )
            res['total_amount'] = reduce(lambda x, y: x + y,
                [(getattr(l, 'amount_w_tax', None) or Decimal(0))
                    for l in self.lines if l.type == 'line'], Decimal(0)
                )
        if self.currency:
            res['untaxed_amount'] = self.currency.round(res['untaxed_amount'])
            res['total_amount'] = self.currency.round(res['total_amount'])
        res['tax_amount'] = res['total_amount'] - res['untaxed_amount']
        if self.currency:
            res['tax_amount'] = self.currency.round(res['tax_amount'])
        return res


    def get_tax_amount(self):
        tax = _ZERO
        taxes = _ZERO

        for line in self.lines:
            if line.type != 'line':
                continue
            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes
            if impuesto == 'iva0':
                value = Decimal(0.0)
            elif impuesto == 'no_iva':
                value = Decimal(0.0)
            elif impuesto == 'iva12':
                value = Decimal(0.12)
            elif impuesto == 'iva14':
                value = Decimal(0.14)
            else:
                value = Decimal(0.0)
            tax = line.unit_price * value
            taxes += tax

        return (self.currency.round(taxes))

    @classmethod
    def get_amount(cls, purchases, names):
        untaxed_amount = {}
        tax_amount = {}
        total_amount = {}

        if {'tax_amount', 'total_amount'} & set(names):
            compute_taxes = True
        else:
            compute_taxes = False
        # Sort cached first and re-instanciate to optimize cache management
        purchases = sorted(purchases, key=lambda s: s.state in cls._states_cached,
            reverse=True)
        purchases = cls.browse(purchases)
        for purchase in purchases:
            if (purchase.state in cls._states_cached
                    and purchase.untaxed_amount_cache is not None
                    and purchase.tax_amount_cache is not None
                    and purchase.total_amount_cache is not None):
                untaxed_amount[purchase.id] = purchase.untaxed_amount_cache
                if compute_taxes:
                    tax_amount[purchase.id] = purchase.tax_amount_cache
                    total_amount[purchase.id] = purchase.total_amount_cache
            else:
                untaxed_amount[purchase.id] = sum(
                    (line.amount for line in purchase.lines
                        if line.type == 'line'), _ZERO)
                if compute_taxes:
                    tax_amount[purchase.id] = purchase.get_tax_amount()
                    total_amount[purchase.id] = (
                        untaxed_amount[purchase.id] + tax_amount[purchase.id])

        result = {
            'untaxed_amount': untaxed_amount,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }
        for key in result.keys():
            if key not in names:
                del result[key]
        return result

    def get_amount2words(self, value):
        if conversor:
            return (conversor.cardinal(int(value))).upper()
        else:
            return ''

    @classmethod
    @ModelView.button
    @Workflow.transition('anulled')
    def anull(cls, purchases):
        for purchase in purchases:
            for line in purchase.lines:
                product = line.product.template
                if product.type == "goods":
                    product.total = line.product.template.total - line.quantity
                    product.save()
        cls.write([p for p in purchases], {
                'state': 'anulled',
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('confirmed')
    def confirm(cls, purchases):
        Company = Pool().get('company.company')
        company = Company(Transaction().context.get('company'))
        for purchase in purchases:

            if purchase.party.supplier == True:
                pass
            else:
                party = purchase.party
                party.supplier = True
                party.save()

            for line in purchase.lines:
                product = line.product.template
                if product.type == "goods":
                    if line.product.template.total == None:
                        product.total = line.quantity
                    else:
                        product.total = line.product.template.total + line.quantity
                product.cost_price = line.unit_price
                product.save()

            if not purchase.reference:
                reference = company.sequence_purchase
                company.sequence_purchase = company.sequence_purchase + 1
                company.save()

                if len(str(reference)) == 1:
                    reference_end = 'FP-00000000' + str(reference)
                elif len(str(reference)) == 2:
                    reference_end = 'FP-0000000' + str(reference)
                elif len(str(reference)) == 3:
                    reference_end = 'FP-000000' + str(reference)
                elif len(str(reference)) == 4:
                    reference_end = 'FP-00000' + str(reference)
                elif len(str(reference)) == 5:
                    reference_end = 'FP-0000' + str(reference)
                elif len(str(reference)) == 6:
                    reference_end = 'FP-000' + str(reference)
                elif len(str(reference)) == 7:
                    reference_end = 'FP-00' + str(reference)
                elif len(str(reference)) == 8:
                    reference_end = 'FP-0' + str(reference)
                elif len(str(reference)) == 9:
                    reference_end = 'FP-' + str(reference)

                purchase.reference = str(reference_end)
                purchase.state = 'confirmed'
                purchase.save()
        cls.write([p for p in purchases], {
                'state': 'confirmed',
                })


    @classmethod
    @ModelView.button_action('nodux_purchase_one.wizard_purchase_payment')
    def wizard_purchase_payment(cls, purchases):
        pass

class PurchaseLine(ModelSQL, ModelView):
    'Purchase Line'
    __name__ = 'purchase.line'
    _rec_name = 'description'
    purchase = fields.Many2One('purchase.purchase', 'Purchase', ondelete='CASCADE',
        select=True)
    sequence = fields.Integer('Sequence')
    type = fields.Selection([
        ('line', 'Line'),
        ], 'Type', select=True, required=True)
    quantity = fields.Float('Quantity',
        digits=(16, Eval('unit_digits', 2)),
        states={
            'invisible': Eval('type') != 'line',
            'required': Eval('type') == 'line',
            'readonly': ~Eval('_parent_purchase', {}),
            },
        depends=['type', 'unit_digits'])
    unit = fields.Many2One('product.uom', 'Unit',
            states={
                'required': Bool(Eval('product')),
                'invisible': Eval('type') != 'line',
                'readonly': ~Eval('_parent_purchase', {}),
            },
        domain=[
            If(Bool(Eval('product_uom_category')),
                ('category', '=', Eval('product_uom_category')),
                ('category', '!=', -1)),
            ],
        depends=['product', 'type', 'product_uom_category'])
    unit_digits = fields.Function(fields.Integer('Unit Digits'),
        'on_change_with_unit_digits')
    product = fields.Many2One('product.product', 'Product',
        states={
            'invisible': Eval('type') != 'line',
            'readonly': ~Eval('_parent_purchase', {}),
            }, depends=['type'])
    product_uom_category = fields.Function(
        fields.Many2One('product.uom.category', 'Product Uom Category'),
        'on_change_with_product_uom_category')
    unit_price = fields.Numeric('Unit Price', digits=(16, 4),
        states={
            'invisible': Eval('type') != 'line',
            'required': Eval('type') == 'line',
            }, depends=['type'])
    amount = fields.Function(fields.Numeric('Amount',
            digits=(16, Eval('_parent_purchase', {}).get('currency_digits', 2)),
            states={
                'invisible': ~Eval('type').in_(['line', 'subtotal']),
                'readonly': ~Eval('_parent_purchase'),
                },
            depends=['type']), 'get_amount')
    description = fields.Text('Description', size=None, required=True)

    unit_price_w_tax = fields.Function(fields.Numeric('Unit Price with Tax',
            digits=(16, Eval('_parent_purchase', {}).get('currency_digits',
                    Eval('currency_digits', 2))),
            states={
                'invisible': Eval('type') != 'line',
                },
            depends=['type', 'currency_digits']), 'get_price_with_tax')
    amount_w_tax = fields.Function(fields.Numeric('Amount with Tax',
            digits=(16, Eval('_parent_purchase', {}).get('currency_digits',
                    Eval('currency_digits', 2))),
            states={
                'invisible': ~Eval('type').in_(['line', 'subtotal']),
                },
            depends=['type', 'currency_digits']), 'get_price_with_tax')
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    currency = fields.Many2One('currency.currency', 'Currency',
        states={
            'required': ~Eval('purchase'),
            },
        depends=['purchase'])

    @classmethod
    def __setup__(cls):
        super(PurchaseLine, cls).__setup__()

        for fname in ('product', 'quantity', 'unit'):
            field = getattr(cls, fname)
            if field.states.get('readonly'):
                del field.states['readonly']

    @staticmethod
    def default_type():
        return 'line'

    @staticmethod
    def default_purchase():
        if Transaction().context.get('purchase'):
            return Transaction().context.get('purchase')
        return None

    @staticmethod
    def default_currency_digits():
        Company = Pool().get('company.company')
        if Transaction().context.get('company'):
            company = Company(Transaction().context['company'])
            return company.currency.digits
        return 2

    @staticmethod
    def default_currency():
        Company = Pool().get('company.company')
        if Transaction().context.get('company'):
            company = Company(Transaction().context['company'])
            return company.currency.id

    @fields.depends('unit')
    def on_change_with_unit_digits(self, name=None):
        if self.unit:
            return self.unit.digits
        return 2

    @fields.depends('product')
    def on_change_with_product_uom_category(self, name=None):
        if self.product:
            return self.product.default_uom_category.id

    def _get_context_purchase_price(self):
        context = {}
        if getattr(self, 'purchase', None):
            if getattr(self.purchase, 'currency', None):
                context['currency'] = self.purchase.currency.id
            if getattr(self.purchase, 'party', None):
                context['customer'] = self.purchase.party.id
            if getattr(self.purchase, 'purchase_date', None):
                context['purchase_date'] = self.purchase.purchase_date
        if self.unit:
            context['uom'] = self.unit.id
        else:
            context['uom'] = self.product.default_uom.id
        return context

    @fields.depends('currency')
    def on_change_with_currency_digits(self, name=None):
        if self.currency:
            return self.currency.digits
        return 2

    def get_amount(self, name):
        if self.type == 'line':
            return self.on_change_with_amount()
        elif self.type == 'subtotal':
            amount = Decimal('0.0')
            for line2 in self.purchase.lines:
                if line2.type == 'line':
                    amount += line2.purchase.currency.round(
                        Decimal(str(line2.quantity)) * line2.unit_price)
                elif line2.type == 'subtotal':
                    if self == line2:
                        break
                    amount = Decimal('0.0')
            return amount
        return Decimal('0.0')

    @fields.depends('product', 'unit', 'quantity', 'description',
        '_parent_purchase.party', '_parent_purchase.currency',
        '_parent_purchase.purchase_date')
    def on_change_product(self):
        Product = Pool().get('product.product')
        if not self.product:
            return {}
        res = {}

        party = None
        party_context = {}
        if self.purchase and self.purchase.party:
            party = self.purchase.party
            if party.lang:
                party_context['language'] = party.lang.code

        category = self.product.default_uom.category
        if not self.unit or self.unit not in category.uoms:
            res['unit'] = self.product.default_uom.id
            self.unit = self.product.default_uom
            res['unit.rec_name'] = self.product.default_uom.rec_name
            res['unit_digits'] = self.product.default_uom.digits

        with Transaction().set_context(self._get_context_purchase_price()):
            res['unit_price'] = Product.get_purchase_price([self.product],
                    self.quantity or 0)[self.product.id]
            if res['unit_price']:
                res['unit_price'] = res['unit_price'].quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])

        self.unit_price = res['unit_price']
        self.type = 'line'
        res['amount'] = self.on_change_with_amount()
        res['description'] =  self.product.name
        return res


    @fields.depends('product', 'quantity', 'unit',
        '_parent_purchase.currency', '_parent_purchase.party',
        '_parent_purchase.purchase_date')
    def on_change_quantity(self):
        Product = Pool().get('product.product')

        if not self.product:
            return {}
        res = {}

        with Transaction().set_context(
                self._get_context_purchase_price()):
            res['unit_price'] = Product.get_purchase_price([self.product],
                self.quantity or 0)[self.product.id]
            if res['unit_price']:
                res['unit_price'] = res['unit_price'].quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
        return res

    @fields.depends('type', 'quantity', 'unit_price', 'unit',
        '_parent_purchase.currency')
    def on_change_with_amount(self):
        if self.type == 'line':
            currency = self.purchase.currency if self.purchase else None
            amount = Decimal(str(self.quantity or '0.0')) * \
                (self.unit_price or Decimal('0.0'))
            if currency:
                return currency.round(amount)
            return amount
        return Decimal('0.0')

    @classmethod
    def get_price_with_tax(cls, lines, names):
        pool = Pool()
        amount_w_tax = {}
        unit_price_w_tax = {}

        def compute_amount_with_tax(line):

            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes
            if impuesto == 'iva0':
                value = Decimal(0.0)
            elif impuesto == 'no_iva':
                value = Decimal(0.0)
            elif impuesto == 'iva12':
                value = Decimal(0.12)
            elif impuesto == 'iva14':
                value = Decimal(0.14)
            else:
                value = Decimal(0.0)

            tax_amount = line.unit_price * value
            return line.get_amount(None) + tax_amount

        for line in lines:
            amount = Decimal('0.0')
            unit_price = Decimal('0.0')
            currency = (line.purchase.currency if line.purchase else line.currency)

            if line.type == 'line':
                if line.quantity and line.product:
                    amount = compute_amount_with_tax(line)
                    unit_price = amount / Decimal(str(line.quantity))
                elif line.product:
                    old_quantity = line.quantity
                    line.quantity = 1.0
                    unit_price = compute_amount_with_tax(line)
                    line.quantity = old_quantity

            # Only compute subtotals if the two fields are provided to speed up

            if currency:
                amount = currency.round(amount)
            amount_w_tax[line.id] = amount
            unit_price_w_tax[line.id] = unit_price

        result = {
            'amount_w_tax': amount_w_tax,
            'unit_price_w_tax': unit_price_w_tax,
            }
        for key in result.keys():
            if key not in names:
                del result[key]
        return result

    @fields.depends('type', 'unit_price', 'quantity', 'taxes', 'purchase',
        '_parent_purchase.currency', 'currency', 'product')
    def on_change_with_unit_price_w_tax(self, name=None):
        if not self.purchase:
            self.purchase = Transaction().context.get('purchase')
        return PurchaseLine.get_price_with_tax([self],
            ['unit_price_w_tax'])['unit_price_w_tax'][self.id]

    @fields.depends('type', 'unit_price', 'quantity', 'taxes', 'purchase',
        '_parent_purchase.currency', 'currency', 'product')
    def on_change_with_amount_w_tax(self, name=None):
        if not self.purchase:
            self.purchase = Transaction().context.get('purchase')
        return PurchaseLine.get_price_with_tax([self],
            ['amount_w_tax'])['amount_w_tax'][self.id]

class PurchasePaymentForm(ModelView, ModelSQL):
    'Purchase Payment Form'
    __name__ = 'purchase.payment.form'

    payment_amount = fields.Numeric('Payment amount', required=True,
        digits=(16, Eval('currency_digits', 2)),
        depends=['currency_digits'])
    currency_digits = fields.Integer('Currency Digits')
    party = fields.Many2One('party.party', 'Party', readonly=True)


class WizardPurchasePayment(Wizard):
    'Wizard Purchase Payment'
    __name__ = 'purchase.payment'
    start = StateView('purchase.payment.form',
        'nodux_purchase_one.purchase_payment_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Pay', 'pay_', 'tryton-ok', default=True),
        ])
    pay_ = StateTransition()

    @classmethod
    def __setup__(cls):
        super(WizardPurchasePayment, cls).__setup__()

    def default_start(self, fields):
        pool = Pool()
        Purchase = pool.get('purchase.purchase')
        purchase = Purchase(Transaction().context['active_id'])

        if purchase.residual_amount > Decimal(0.0):
            payment_amount = purchase.residual_amount
        else:
            payment_amount = purchase.total_amount
        return {
            'payment_amount': payment_amount,
            'currency_digits': purchase.currency_digits,
            'party': purchase.party.id,
            }

    def transition_pay_(self):
        pool = Pool()
        Date = pool.get('ir.date')
        Purchase = pool.get('purchase.purchase')
        Company = pool.get('company.company')
        active_id = Transaction().context.get('active_id', False)
        purchase = Purchase(active_id)
        company = Company(Transaction().context.get('company'))
        form = self.start

        if purchase.residual_amount > Decimal(0.0):
            if form.payment_amount > purchase.residual_amount:
                self.raise_user_error('No puede pagar un monto mayor al valor pendiente %s', str(purchase.residual_amount ))

        if form.payment_amount > purchase.total_amount:
            self.raise_user_error('No puede pagar un monto mayor al monto total %s', str(purchase.total_amount ))

        if purchase.party.supplier == True:
            pass
        else:
            party = purchase.party
            party.supplier = True
            party.save()

        User = pool.get('res.user')
        user = User(Transaction().user)
        limit = user.limit_purchase

        purchases = Purchase.search_count([('state', '=', 'confirmed')])
        if purchases > limit and user.unlimited_purchase != True:
            self.raise_user_error(u'Ha excedido el límite de Compras, contacte con el Administrador de NODUX')

        if not purchase.reference:
            for line in purchase.lines:
                product = line.product.template
                if product.type == "goods":
                    if line.product.template.total == None:
                        product.total = line.quantity
                    else:
                        product.total = line.product.template.total + line.quantity
                product.cost_price = line.unit_price
                product.save()

            reference = company.sequence_purchase
            company.sequence_purchase = company.sequence_purchase + 1
            company.save()

            if len(str(reference)) == 1:
                reference_end = 'FP-00000000' + str(reference)
            elif len(str(reference)) == 2:
                reference_end = 'FP-0000000' + str(reference)
            elif len(str(reference)) == 3:
                reference_end = 'FP-000000' + str(reference)
            elif len(str(reference)) == 4:
                reference_end = 'FP-00000' + str(reference)
            elif len(str(reference)) == 5:
                reference_end = 'FP-0000' + str(reference)
            elif len(str(reference)) == 6:
                reference_end = 'FP-000' + str(reference)
            elif len(str(reference)) == 7:
                reference_end = 'FP-00' + str(reference)
            elif len(str(reference)) == 8:
                reference_end = 'FP-0' + str(reference)
            elif len(str(reference)) == 9:
                reference_end = 'FP-' + str(reference)

            purchase.reference = str(reference_end)
            purchase.save()




        if purchase.paid_amount > Decimal(0.0):
            purchase.paid_amount = purchase.paid_amount + form.payment_amount
        else:
            purchase.paid_amount = form.payment_amount

        purchase.residual_amount = purchase.total_amount - purchase.paid_amount
        purchase.description = purchase.reference
        if purchase.residual_amount == Decimal(0.0):
            purchase.state = 'done'
        else:
            purchase.state = 'confirmed'
        purchase.save()


        return 'end'


class PurchaseReport(Report):
    __name__ = 'purchase.purchase_pos'

    @classmethod
    def parse(cls, report, records, data, localcontext):
        pool = Pool()
        User = pool.get('res.user')
        Purchase = pool.get('purchase.purchase')
        purchase = records[0]
        if purchase.total_amount:
            d = str(purchase.total_amount).split('.')
            decimales = d[1]
            decimales = decimales[0:2]
        else:
            decimales='0.0'

        user = User(Transaction().user)
        localcontext['user'] = user
        localcontext['company'] = user.company
        localcontext['subtotal_0'] = cls._get_subtotal_0(Purchase, purchase)
        localcontext['subtotal_12'] = cls._get_subtotal_12(Purchase, purchase)
        localcontext['subtotal_14'] = cls._get_subtotal_14(Purchase, purchase)
        localcontext['amount2words']=cls._get_amount_to_pay_words(Purchase, purchase)
        localcontext['decimales'] = decimales
        return super(PurchaseReport, cls).parse(report, records, data,
                localcontext=localcontext)

    @classmethod
    def _get_amount_to_pay_words(cls, Purchase, purchase):
        amount_to_pay_words = Decimal(0.0)
        if purchase.total_amount and conversor:
            amount_to_pay_words = purchase.get_amount2words(purchase.total_amount)
        return amount_to_pay_words

    @classmethod
    def _get_subtotal_14(cls, Purchase, purchase):
        subtotal14 = Decimal(0.00)
        pool = Pool()

        for line in purchase.lines:

            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes

            if impuesto == 'iva14':
                subtotal14= subtotal14 + (line.amount)

        return subtotal14

    @classmethod
    def _get_subtotal_12(cls, Purchase, purchase):
        subtotal12 = Decimal(0.00)

        for line in purchase.lines:

            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes

            if impuesto == 'iva12':
                subtotal12= subtotal12 + (line.amount)

        return subtotal12

    @classmethod
    def _get_subtotal_0(cls, Purchase, purchase):
        subtotal0 = Decimal(0.00)

        for line in purchase.lines:

            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes

            if impuesto == 'iva0' or impuesto == 'no_iva':
                subtotal0= subtotal0 + (line.amount)

        return subtotal0

class PrintReportPurchasesStart(ModelView):
    'Print Report Purchases Start'
    __name__ = 'nodux_purchase_one.print_report_purchase.start'

    company = fields.Many2One('company.company', 'Company', required=True)
    date = fields.Date("Purchase Date", required= True)
    date_end = fields.Date("Purchase Date End", required= True)

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_date():
        date = Pool().get('ir.date')
        return date.today()

    @staticmethod
    def default_date_end():
        date = Pool().get('ir.date')
        return date.today()

class PrintReportPurchases(Wizard):
    'Print Report Purchases'
    __name__ = 'nodux_purchase_one.print_report_purchase'
    start = StateView('nodux_purchase_one.print_report_purchase.start',
        'nodux_purchase_one.print_purchase_report_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateAction('nodux_purchase_one.report_purchases')

    def do_print_(self, action):
        data = {
            'company': self.start.company.id,
            'date' : self.start.date,
            'date_end' : self.start.date_end,
            }
        return action, data

    def transition_print_(self):
        return 'end'

class ReportPurchases(Report):
    __name__ = 'nodux_purchase_one.report_purchases'

    @classmethod
    def parse(cls, report, objects, data, localcontext):
        pool = Pool()
        User = pool.get('res.user')
        user = User(Transaction().user)
        Date = pool.get('ir.date')
        Company = pool.get('company.company')
        Purchase = pool.get('purchase.purchase')
        fecha = data['date']
        fecha_fin = data['date_end']
        total_compras =  Decimal(0.0)
        total_iva =  Decimal(0.0)
        subtotal_total =  Decimal(0.0)
        subtotal14 = Decimal(0.0)
        subtotal0 = Decimal(0.0)
        subtotal12 = Decimal(0.0)
        total_pagado = Decimal(0.0)
        total_por_pagar = Decimal(0.0)
        company = Company(data['company'])
        purchases = Purchase.search([('purchase_date', '>=', fecha), ('purchase_date', '<=', fecha_fin), ('state','!=', 'draft')])

        if purchases:
            for s in purchases:
                if s.total_amount > Decimal(0.0):
                    total_compras += s.total_amount
                    total_iva += s.tax_amount
                    subtotal_total += s.untaxed_amount
                    total_pagado += s.paid_amount
                    if s.residual_amount != None:
                        total_por_pagar += s.residual_amount

                    for line in s.lines:
                        if line.product.taxes_category == True:
                            impuesto = line.product.category.taxes
                        else:
                            impuesto = line.product.taxes

                        if impuesto == 'iva0' or impuesto == 'no_iva':
                            subtotal0= subtotal0 + (line.amount)
                        if impuesto == 'iva14':
                            subtotal14= subtotal14 + (line.amount)
                        if impuesto == 'iva12':
                            subtotal12= subtotal12 + (line.amount)

        if company.timezone:
            timezone = pytz.timezone(company.timezone)
            dt = datetime.now()
            hora = datetime.astimezone(dt.replace(tzinfo=pytz.utc), timezone)
        else:
            company.raise_user_error('Configure la zona Horaria de la empresa')

        localcontext['company'] = company
        localcontext['fecha'] = fecha.strftime('%d/%m/%Y')
        localcontext['fecha_fin'] = fecha_fin.strftime('%d/%m/%Y')
        localcontext['hora'] = hora.strftime('%H:%M:%S')
        localcontext['fecha_im'] = hora.strftime('%d/%m/%Y')
        localcontext['total_ventas'] = total_compras
        localcontext['sales'] = purchases
        localcontext['total_iva'] = total_iva
        localcontext['subtotal_total'] = subtotal_total
        localcontext['subtotal14'] = subtotal14
        localcontext['subtotal0'] = subtotal0

        return super(ReportPurchases, cls).parse(report, objects, data, localcontext)
