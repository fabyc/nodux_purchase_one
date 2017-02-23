#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
#! -*- coding: utf8 -*-
from trytond.pool import *
from trytond.model import fields
from trytond.pyson import Eval
from trytond.pyson import Id
import base64
__all__ = ['User']
__metaclass__ = PoolMeta


class User:
    __name__ = 'res.user'

    limit_purchase = fields.Integer('Purchase Limit', states={
        'readonly': Eval('unlimited_purchase', True)
    })
    unlimited_purchase = fields.Boolean('Unlimited Purchase')

    @classmethod
    def __setup__(cls):
        super(User, cls).__setup__()

    @staticmethod
    def default_limit_purchase():
        return 10

    @staticmethod
    def default_unlimited_purchase():
        return False

    @classmethod
    def view_attributes(cls):
        return super(User, cls).view_attributes() + [
            ('//page[@id="purchase"]', 'states', {
                    'invisible': ~Eval('id').in_([1]),
                    })]
